"""Lenient type coercion for loosely typed input (YAML, JSON, CLI strings)."""

from __future__ import annotations

from typing import Any

__all__ = ["FALSE_STRINGS", "TRUE_STRINGS", "coerce_bool", "coerce_int", "parse_bool"]

TRUE_STRINGS = frozenset({"1", "true", "yes", "on"})
FALSE_STRINGS = frozenset({"0", "false", "no", "off"})


def coerce_int(value: Any, default: int = 0) -> int:
    """Return ``int(value)``, or ``default`` when the conversion fails.

    Follows ``int()`` exactly on success: floats truncate, bools become 0/1,
    and numeric strings must be integral ("3.5" falls back to ``default``).
    """
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def parse_bool(value: object, *, extra_false: frozenset[str] = frozenset()) -> bool | None:
    """Tri-state boolean parse: True, False, or None when unrecognised.

    Accepts bools, the ints 0/1, and strings (case-insensitive, stripped) in
    TRUE_STRINGS / FALSE_STRINGS. Other ints, floats, None and unknown strings
    return None. ``extra_false`` adds caller-specific false spellings
    (e.g. ``frozenset({"none"})``).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value) if value in (0, 1) else None
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    if s in TRUE_STRINGS:
        return True
    if s in FALSE_STRINGS or s in extra_false:
        return False
    return None


def coerce_bool(value: object, default: bool) -> bool:
    """Return ``parse_bool(value)``, or ``default`` when it is unrecognised."""
    parsed = parse_bool(value)
    return default if parsed is None else parsed
