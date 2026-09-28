"""Count a concern sweep's regex hits under repo-relative paths, in-process.

update-review-concerns derives each sweep pattern from reviewer-authored
thread text. Running it through ``grep`` in a shell is an injection path, so
the stage calls ``./bin/workflow count-sweep`` instead: the pattern is compiled
with :mod:`re`, every path passes the same guard as ``check-paths``, and the
files are read here with no subprocess.

Work is bounded so a broad or pathological sweep fails the stage instead of
hanging it: binary files and files over :data:`MAX_FILE_BYTES` are skipped,
each line is matched on its first :data:`MAX_LINE_CHARS` characters, and a
scan that passes :data:`MAX_TOTAL_BYTES` or :data:`MAX_SECONDS` stops and is
reported as truncated. A single ``re.search`` cannot be interrupted, so the
line cap is what bounds one pathological match.
"""

from __future__ import annotations

import os
import re
import stat
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

MAX_PATTERN_CHARS = 500
MAX_FILE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 64_000_000
MAX_LINE_CHARS = 2_000
MAX_SECONDS = 30.0
#: Never descended into: repository/tool state rather than source.
_SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache"})
_BINARY_SNIFF = 8192
#: Characters a single-quoted shell argument cannot carry intact.
_UNQUOTABLE = re.compile(r"['\n\r]")
#: The only path shape accepted: the same allowlist the workflow's jq gates
#: apply. It excludes every shell metacharacter, whitespace, quotes and a
#: leading ``-`` or ``.``, so a path that reaches a shell unquoted is inert.
_SAFE_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]*")
#: Reason a path was refused for a character or segment outside the allowlist.
UNSAFE_PATH = "unsafe-path"


class SweepError(ValueError):
    """The pattern or a path is unusable; nothing was counted."""


@dataclass(frozen=True)
class SweepCount:
    hits: int
    files: int
    truncated: bool

    def as_dict(self) -> dict[str, int | bool]:
        out: dict[str, int | bool] = {"hits": self.hits, "files": self.files}
        if self.truncated:
            out["truncated"] = True
        return out


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile ``pattern``, raising :class:`SweepError` when it is empty, too long or invalid."""
    if not pattern:
        raise SweepError("pattern is empty")
    if len(pattern) > MAX_PATTERN_CHARS:
        raise SweepError(f"pattern is longer than {MAX_PATTERN_CHARS} characters")
    if _UNQUOTABLE.search(pattern):
        # The workflow passes the pattern single-quoted; one containing a quote
        # or newline means the quoting already broke, so it is refused.
        raise SweepError("pattern contains a single quote or newline")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise SweepError(f"invalid pattern: {exc}") from exc


def check_path(raw: str) -> str:
    """Return ``raw`` normalised, or raise :class:`SweepError`; no filesystem access.

    The check-paths guard runs first so its reason codes stay stable, then the
    strict allowlist: ``classify_repo_path`` alone accepts ``$(id)`` and
    ``a;b``, which are harmless to Python but not to the shell text that
    builds this command.
    """
    from core.copilot_overview import classify_repo_path

    normalised, reason = classify_repo_path(raw)
    if reason is not None or normalised is None:
        raise SweepError(f"refused path ({reason}): {raw!r}")
    if not _SAFE_PATH.fullmatch(raw) or any(seg in (".", "..") for seg in raw.split("/")):
        raise SweepError(f"refused path ({UNSAFE_PATH}): {raw!r}")
    return normalised


def resolve_paths(root: Path, paths: list[str]) -> list[Path]:
    """Validate every path (see :func:`check_path`), then resolve each under ``root``."""
    if not paths:
        raise SweepError("no --path given")
    # All paths are checked before any is touched, so a refusal is exit 2
    # with no IO at all.
    normalised_paths = [check_path(raw) for raw in paths]
    try:
        root_real = root.resolve(strict=True)
    except OSError as exc:
        raise SweepError(f"repository root is unusable: {exc}") from exc
    return [_resolve_one(root_real, raw, normalised)
            for raw, normalised in zip(paths, normalised_paths, strict=True)]


def _resolve_one(root_real: Path, raw: str, normalised: str) -> Path:
    """Resolve one checked path, refusing it when any component is a symlink.

    A symlink anywhere in the path is refused, whether it points outside the
    repository or inside it. Following in-repo links would make the result
    depend on where each link points, and the walk never follows one, so a
    listed path and a walked path obey the same rule.
    """
    target = root_real / normalised
    try:
        real = target.resolve(strict=True)
    except (OSError, RuntimeError) as exc:  # RuntimeError: a symlink loop
        raise SweepError(f"no such file or directory: {raw!r}") from exc
    if real != target or not real.is_relative_to(root_real):
        raise SweepError(f"refused path (symlink): {raw!r}; symlinks are refused")
    mode = _lstat_mode(real)
    if mode is None or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise SweepError(f"refused path (not a regular file or directory): {raw!r}")
    return real


def _lstat_mode(path: Path) -> int | None:
    try:
        return os.lstat(path).st_mode
    except OSError:
        return None


def _inside(path: Path, root_real: Path) -> bool:
    return Path(os.path.realpath(path)).is_relative_to(root_real)


def _is_regular(path: Path, root_real: Path) -> bool:
    """True for a regular file (not a link, FIFO, socket or device) under the root.

    Decided from ``lstat`` before anything opens the file: opening a FIFO
    blocks until a writer appears, and a device can be read forever.
    """
    mode = _lstat_mode(path)
    return mode is not None and stat.S_ISREG(mode) and _inside(path, root_real)


def _is_walkable_dir(path: Path, root_real: Path) -> bool:
    mode = _lstat_mode(path)  # lstat: a symlinked directory is not S_ISDIR
    return mode is not None and stat.S_ISDIR(mode) and _inside(path, root_real)


def _iter_files(target: Path, root_real: Path) -> Iterator[Path]:
    if _is_regular(target, root_real):
        yield target
        return
    for dirpath, dirnames, filenames in os.walk(target):  # followlinks=False: symlinked dirs are not entered
        base = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and _is_walkable_dir(base / d, root_real))
        for name in sorted(filenames):
            candidate = base / name
            if _is_regular(candidate, root_real):
                yield candidate


def _read_text(path: Path) -> str | None:
    """Return a file's text, or None for a binary, oversized, non-regular or unreadable file.

    The open refuses a symlink and never blocks, and ``fstat`` re-checks the
    opened file, so a file swapped for a FIFO or link after the walk's
    ``lstat`` is still skipped.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as fh:
        try:
            info = os.fstat(fh.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                return None
            data = fh.read(MAX_FILE_BYTES + 1)
        except OSError:
            return None
    if len(data) > MAX_FILE_BYTES or b"\0" in data[:_BINARY_SNIFF]:
        return None
    return data.decode("utf-8", errors="replace")


def _count_lines(regex: re.Pattern[str], text: str) -> int:
    return sum(1 for line in text.splitlines() if regex.search(line[:MAX_LINE_CHARS]))


def _unique_files(targets: list[Path], root_real: Path) -> Iterator[Path]:
    """Every file under ``targets`` once, even when listed paths overlap.

    Targets are already resolved and no symlink is ever followed, so each
    file's walked path is its real path and serves as the identity key.
    """
    seen: set[Path] = set()
    for target in targets:
        for path in _iter_files(target, root_real):
            if path not in seen:
                seen.add(path)
                yield path


def count_sweep(pattern: str, paths: list[str], *, root: Path) -> SweepCount:
    """Count lines matching ``pattern`` under ``paths``, like ``grep -rc`` summed.

    ``files`` is the number of files with at least one hit. A path listed
    twice, or nested inside another listed path, is counted once.
    """
    regex = compile_pattern(pattern)
    targets = resolve_paths(root, paths)
    root_real = root.resolve(strict=True)
    deadline = time.monotonic() + MAX_SECONDS
    hits = files = total = 0
    for path in _unique_files(targets, root_real):
        text = _read_text(path)
        if text is None:
            continue
        total += len(text)
        if total > MAX_TOTAL_BYTES or time.monotonic() > deadline:
            return SweepCount(hits, files, truncated=True)
        n = _count_lines(regex, text)
        hits += n
        files += 1 if n else 0
    return SweepCount(hits, files, truncated=False)
