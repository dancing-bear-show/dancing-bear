"""File I/O utilities."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path: Path, data: object) -> None:
    """Write data as JSON to path atomically (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
        encoding="utf-8",
    )
    try:
        json.dump(data, fd, indent=2, default=str)
        fd.close()
        os.replace(fd.name, path)
    except Exception:
        fd.close()
        try:
            os.unlink(fd.name)
        except OSError:
            pass
        raise


def safe_load_json(path: Path) -> dict[str, object]:
    """Load JSON from path, returning {} on missing file or parse error."""
    try:
        with open(path, encoding="utf-8") as f:
            result = json.load(f)
            return result if isinstance(result, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
