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


def resolve_paths(root: Path, paths: list[str]) -> list[Path]:
    """Validate each repo-relative path with the check-paths guard and resolve it under ``root``."""
    from core.copilot_overview import classify_repo_path

    if not paths:
        raise SweepError("no --path given")
    resolved: list[Path] = []
    for raw in paths:
        normalised, reason = classify_repo_path(raw)
        if reason is not None or normalised is None:
            raise SweepError(f"refused path ({reason}): {raw!r}")
        target = root / normalised
        if target.is_symlink() or not target.exists():
            raise SweepError(f"no such file or directory (symlinks are refused): {raw!r}")
        resolved.append(target)
    return resolved


def _iter_files(target: Path) -> Iterator[Path]:
    if target.is_file():
        yield target
        return
    for dirpath, dirnames, filenames in os.walk(target):  # followlinks=False: symlinked dirs are not entered
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            candidate = Path(dirpath) / name
            if not candidate.is_symlink():
                yield candidate


def _read_text(path: Path) -> str | None:
    """Return a file's text, or None for a binary, oversized or unreadable file."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:_BINARY_SNIFF]:
        return None
    return data.decode("utf-8", errors="replace")


def _count_lines(regex: re.Pattern[str], text: str) -> int:
    return sum(1 for line in text.splitlines() if regex.search(line[:MAX_LINE_CHARS]))


def _unique_files(targets: list[Path]) -> Iterator[Path]:
    """Every file under ``targets`` once, even when listed paths overlap."""
    seen: set[Path] = set()
    for target in targets:
        for path in _iter_files(target):
            key = path.resolve()
            if key not in seen:
                seen.add(key)
                yield path


def count_sweep(pattern: str, paths: list[str], *, root: Path) -> SweepCount:
    """Count lines matching ``pattern`` under ``paths``, like ``grep -rc`` summed.

    ``files`` is the number of files with at least one hit. A path listed
    twice, or nested inside another listed path, is counted once.
    """
    regex = compile_pattern(pattern)
    targets = resolve_paths(root, paths)
    deadline = time.monotonic() + MAX_SECONDS
    hits = files = total = 0
    for path in _unique_files(targets):
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
