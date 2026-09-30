"""Lenient type coercion for loosely typed input (YAML, JSON, CLI strings)."""
from __future__ import annotations

from typing import Any

__all__ = ["coerce_int"]


def coerce_int(value: Any, default: int = 0) -> int:
    """Return ``int(value)``, or ``default`` when the conversion fails.

    Follows ``int()`` exactly on success: floats truncate, bools become 0/1,
    and numeric strings must be integral ("3.5" falls back to ``default``).
    """
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default
