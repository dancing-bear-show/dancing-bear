"""File utilities: atomic JSON writes and safe JSON reads."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from core.cli_errors import CLIError, ExitCode
from core.pathguard import require_path

__all__ = [
    "atomic_copy",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "SymlinkDestinationError",
    "file_sha256",
    "find_rotated_files",
    "iter_jsonl_file",
    "iter_rotated_jsonl",
    "load_json_object",
    "load_json_or_exit",
    "safe_load_json",
    "write_once",
]


def atomic_write_json(
    path: str | Path,
    data: dict[str, Any] | list[Any],
    *,
    indent: int | None = 2,
) -> None:
    """Write JSON atomically via unique temp file + rename; the result is always 0600.

    An existing file is narrowed to 0600 rather than keeping its mode, so a
    token or queue record never stays readable by other accounts.
    """
    atomic_write_text(
        path,
        json.dumps(data, indent=indent, ensure_ascii=False),
        new_file_mode=0o600,
        keep_existing_mode=False,
    )


class SymlinkDestinationError(OSError):
    """Raised when a write is asked to refuse a symlink and the target is one."""


def _current_umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def _existing_file_mode(path: Path, *, refuse_symlink: bool) -> int | None:
    """Permission bits of a regular file at ``path``; None when absent or replaceable."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode):
        if refuse_symlink:
            raise SymlinkDestinationError(f"refusing to write through symlink: {path}")
        return None
    if not stat.S_ISREG(st.st_mode):
        raise IsADirectoryError(f"destination is not a regular file: {path}")
    return stat.S_IMODE(st.st_mode)


def atomic_write_bytes(
    path: str | Path,
    data: bytes,
    *,
    refuse_symlink: bool = False,
    new_file_mode: int = 0o666,
    keep_existing_mode: bool = True,
    fsync: bool = False,
) -> None:
    """Write ``data`` atomically via a uniquely named temp file + rename.

    Overwriting a regular file keeps its permission bits; a new file gets
    ``new_file_mode & ~umask``. With ``keep_existing_mode=False`` every write
    gets ``new_file_mode & ~umask``, narrowing an existing file. ``fsync``
    flushes the temp file to disk before the rename. A symlink at ``path`` is
    replaced by a regular file, never written through — or refused with
    ``SymlinkDestinationError`` when ``refuse_symlink`` is set. On failure the
    temp file is removed and the previous content of ``path`` is left untouched.
    """
    path = require_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = _existing_file_mode(path, refuse_symlink=refuse_symlink)
    if mode is None or not keep_existing_mode:
        mode = new_file_mode & ~_current_umask()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            os.fchmod(fh.fileno(), mode)
            fh.write(data)
            if fsync:
                fh.flush()
                os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    refuse_symlink: bool = False,
    new_file_mode: int = 0o666,
    keep_existing_mode: bool = True,
    fsync: bool = False,
) -> None:
    """Write ``text`` (UTF-8) atomically; see ``atomic_write_bytes`` for semantics."""
    atomic_write_bytes(
        path,
        text.encode("utf-8"),
        refuse_symlink=refuse_symlink,
        new_file_mode=new_file_mode,
        keep_existing_mode=keep_existing_mode,
        fsync=fsync,
    )


def atomic_copy(src: str | Path, dest: str | Path) -> None:
    """Copy ``src`` bytes to ``dest`` atomically; ``dest`` keeps its existing mode."""
    atomic_write_bytes(dest, Path(src).read_bytes())


def file_sha256(path: str | Path) -> str:
    """Hex SHA-256 of the file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_once(path: str | Path, data: str | bytes) -> None:
    """Write to path only if it does not exist; raises FileExistsError if it does."""
    path = Path(path)
    if isinstance(data, str):
        data = data.encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def safe_load_json(
    path: str | Path,
    default: Any = None,
) -> Any:
    """Load JSON from path; return default on any error."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # nosec B110 - intentional fallback; caller supplies default
        return default


def load_json_object(path: str | Path) -> dict[str, Any] | None:
    """Load a JSON object from path; None when missing, unreadable, invalid, or not an object.

    Unlike ``safe_load_json(path, default={})``, a file holding valid JSON of
    another type (``null``, ``[]``, a scalar) never reaches the caller, so the
    result is always safe to index as a dict.
    """
    data = safe_load_json(path)
    return data if isinstance(data, dict) else None


def load_json_or_exit(path: str | Path) -> Any:
    """Load JSON from path; raise CLIError so callers decide the exit strategy.

    Raises:
        CLIError: with ExitCode.NOT_FOUND when the file is missing,
                  ExitCode.ERROR for JSON parse or other read failures.
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CLIError(f"File not found: {path}", ExitCode.NOT_FOUND)
    except json.JSONDecodeError as exc:
        raise CLIError(f"Invalid JSON in {path}: {exc}", ExitCode.ERROR)
    except Exception as exc:  # catch-all for unexpected read errors
        raise CLIError(f"Failed to load {path}: {exc}", ExitCode.ERROR)


def find_rotated_files(base_path: Path) -> list[Path]:
    """Return the main JSONL file plus numbered and timestamped rotation files.

    Returns files in a deterministic order: base first, then numbered suffixes
    (.1, .2, …) in sorted order, then stem-dated variants (metrics-2024-01-01.jsonl).
    """
    files: list[Path] = []
    if base_path.exists():
        files.append(base_path)

    filename = base_path.name
    parent = base_path.parent

    for rotated in sorted(
        parent.glob(f"{filename}.*"),
        key=lambda p: int(p.name.removeprefix(f"{filename}."))
        if p.name.removeprefix(f"{filename}.").isdigit()
        else -1,
    ):
        suffix = rotated.name.removeprefix(f"{filename}.")
        if suffix.isdigit():
            files.append(rotated)

    stem = filename.removesuffix(".jsonl")
    for rotated in sorted(parent.glob(f"{stem}-*.jsonl")):
        if rotated != base_path and rotated not in files:
            files.append(rotated)

    return files


_SKIP_LINE = object()  # sentinel: line was blank or an intentionally-swallowed parse error


def _parse_jsonl_line(line: str, *, tolerant: bool) -> Any:
    """Parse one JSONL line, returning _SKIP_LINE for blank or (tolerant) malformed lines."""
    if not line.strip():
        return _SKIP_LINE
    try:
        return json.loads(line)
    except (ValueError, TypeError):
        if not tolerant:
            raise
        return _SKIP_LINE


def iter_jsonl_file(fpath: Path, *, tolerant: bool) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON objects from a single JSONL file.

    Args:
        fpath: Path to the JSONL file.
        tolerant: When True, skip unreadable files and malformed lines silently.
                  When False, raise on any I/O or parse error.
    """
    try:
        f = open(fpath, encoding="utf-8")  # noqa: SIM115
    except OSError:
        if tolerant:
            return
        raise
    with f:
        for line in f:
            parsed = _parse_jsonl_line(line, tolerant=tolerant)
            if parsed is not _SKIP_LINE:
                yield parsed


def iter_rotated_jsonl(
    base_path: Path,
    *,
    tolerant: bool = True,
) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from *base_path* and its numbered/timestamped rotation files."""
    for fpath in find_rotated_files(base_path):
        yield from iter_jsonl_file(fpath, tolerant=tolerant)
