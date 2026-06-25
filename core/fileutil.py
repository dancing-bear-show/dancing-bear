"""File utilities: atomic JSON writes and safe JSON reads."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

__all__ = ["atomic_write_json", "write_once", "safe_load_json", "load_json_or_exit"]


def atomic_write_json(
    path: str | Path,
    data: dict[str, Any] | list[Any],
    *,
    indent: int = 2,
) -> None:
    """Write JSON atomically via temp file + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


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
    """Load JSON from path; call sys.exit(1) with an error message if it fails."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"File not found: {path}")
    except json.JSONDecodeError as exc:
        sys.exit(f"Invalid JSON in {path}: {exc}")
    except Exception as exc:  # nosec B110 - catch-all for unexpected read errors
        sys.exit(f"Failed to load {path}: {exc}")
