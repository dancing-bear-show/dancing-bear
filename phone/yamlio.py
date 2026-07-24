"""Phone assistant YAML helpers backed by shared core utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.yamlio import dump_config as _dump_config
from core.yamlio import load_config as _load_config

Pathish = str | Path

__all__ = ["load_config", "dump_config"]


def load_config(path: Pathish | None) -> dict[str, Any]:
    """Load YAML from a path or Path (delegates to core)."""
    if path is None:
        return {}
    return _load_config(str(path))


def dump_config(path: Pathish, data: dict[str, Any]) -> None:
    """Write YAML to path or Path (delegates to core)."""
    _dump_config(str(path), data)
