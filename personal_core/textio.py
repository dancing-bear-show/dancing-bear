from __future__ import annotations

"""Small text IO helpers shared across assistant CLIs."""

from pathlib import Path
from typing import Optional

__all__ = ["read_text", "write_text"]


def read_text(path: Path, default: Optional[str] = "") -> Optional[str]:
    """Read UTF-8 text, returning `default` when the file is missing/unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return default


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text, creating parent directories automatically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
