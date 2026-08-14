"""File utilities: atomic JSON writes and safe JSON reads."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from core.cli_errors import CLIError, ExitCode

__all__ = [
    "atomic_write_json",
    "find_rotated_files",
    "iter_jsonl_file",
    "iter_rotated_jsonl",
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
    """Write JSON atomically via unique temp file + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
        encoding="utf-8",
    )
    try:
        json.dump(data, fd, indent=indent, ensure_ascii=False)
        fd.close()
        os.replace(fd.name, path)
    except Exception:
        fd.close()
        try:
            os.unlink(fd.name)
        except OSError:  # nosec B110 - cleanup failure is non-fatal; original exception re-raised below
            pass
        raise


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
