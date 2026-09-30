"""Small text IO helpers shared across assistant CLIs."""
from __future__ import annotations

from pathlib import Path

from core.pathguard import require_path

__all__ = ["read_text", "write_text"]


def read_text(
    path: str | Path,
    default: str | None = "",
    *,
    suppress: type[Exception] | tuple[type[Exception], ...] = Exception,
) -> str | None:
    """Read UTF-8 text, returning `default` when reading raises `suppress`.

    The default suppresses any read failure (missing, unreadable, undecodable).
    Pass ``suppress=FileNotFoundError`` to fall back only for a missing file and
    let every other error propagate.
    """
    try:
        return Path(path).read_text(encoding="utf-8")
    except suppress:  # nosec B110 - intentional fallback; caller chooses default and scope
        return default


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text, creating parent directories automatically."""
    path = require_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
