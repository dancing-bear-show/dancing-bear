"""Bullet parsing primitives shared by the slide deck input parsers.

Converts dict, list/tuple, string, and multiline-body bullet definitions into
typed BulletItem objects.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from slides.constants import (
    DEFAULT_BULLET_LEVEL,
    YAML_BOLD,
    YAML_HIGHLIGHT,
    YAML_LEVEL,
    YAML_TEXT,
    YAML_URL,
)
from slides.schema import BulletItem

# Marker that promotes a body line to a sub-bullet; indent depth picks level 1 vs 2.
_BODY_SUB_BULLET_PREFIX = "- "


def _validate_bullet_level(raw: object, context: str = "") -> int:
    """Validate and coerce a bullet level value to int.

    Rejects bools (YAML true/false) and negative values.
    """
    suffix = f" for {context}" if context else ""
    if isinstance(raw, bool):
        raise ValueError(f"Bullet level must be an integer, got bool {raw!r}{suffix}")
    try:
        level = int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"Bullet level must be an integer, got {type(raw).__name__} {raw!r}{suffix}"
        ) from None
    if level < 0:
        raise ValueError(f"Bullet level must be non-negative, got {level}{suffix}")
    return level


def _parse_dict_bullet(b: dict) -> BulletItem:
    """Parse a dict-format bullet into a BulletItem."""
    highlight = b.get(YAML_HIGHLIGHT, [])
    if isinstance(highlight, str):
        highlight = [highlight]  # Allow single string
    raw_level = b.get(YAML_LEVEL, DEFAULT_BULLET_LEVEL)
    level = _validate_bullet_level(raw_level, context=f"dict bullet {b.get(YAML_TEXT, '')!r}")
    return BulletItem(
        text=b.get(YAML_TEXT, ""),
        level=level,
        highlight=highlight,
        bold=b.get(YAML_BOLD, False) is True,
        url=str(b[YAML_URL]) if YAML_URL in b and b[YAML_URL] is not None else None,
    )


def _parse_list_bullet(b: list | tuple) -> BulletItem:
    """Parse a list/tuple-format bullet into a BulletItem."""
    if not b or len(b) > 2:
        raise ValueError(
            f"Bullet list/tuple must have 1 or 2 elements [text, level?], got {len(b)}"
        )
    text = str(b[0])
    raw_level = b[1] if len(b) > 1 else DEFAULT_BULLET_LEVEL
    level = _validate_bullet_level(raw_level, context=f"list bullet {text!r}")
    return BulletItem(text=text, level=level)


def _parse_str_bullet(b: str) -> BulletItem:
    """Parse a string-format bullet, auto-detecting URLs."""
    url = b if b.startswith(("http://", "https://")) else None
    return BulletItem(text=b, url=url)


# Ordered type dispatch: the first matching entry parses the bullet.
_BULLET_PARSERS: tuple[tuple[type | tuple[type, ...], Callable[[Any], BulletItem]], ...] = (
    (dict, _parse_dict_bullet),
    ((list, tuple), _parse_list_bullet),
    (str, _parse_str_bullet),
)


def _parse_bullets(raw_bullets: list[object]) -> list[BulletItem]:
    """Parse bullet items from YAML data into BulletItem objects.

    Values of an unsupported type are skipped rather than raising.
    """
    bullets: list[BulletItem] = []
    for b in raw_bullets:
        for types, parser in _BULLET_PARSERS:
            if isinstance(b, types):
                bullets.append(parser(b))
                break
    return bullets


def _body_to_bullets(body: str) -> list[BulletItem]:
    """Convert a multiline body string into BulletItem objects.

    Level mapping:

    - Plain lines → level 0
    - Lines starting with ``- `` → level 1 (sub-bullet)
    - Lines with 2+ spaces before ``- `` → level 2 (sub-sub-bullet)
    - Blank lines are skipped.
    """
    items: list[BulletItem] = []
    for line in body.strip("\n").split("\n"):
        item = _body_line_to_bullet(line)
        if item is not None:
            items.append(item)
    return items


def _body_line_to_bullet(line: str) -> BulletItem | None:
    """Convert one body line into a BulletItem, or None if it contributes nothing."""
    stripped = line.rstrip()
    if not stripped:
        return None

    lstripped = stripped.lstrip()
    if not lstripped.startswith(_BODY_SUB_BULLET_PREFIX):
        return BulletItem(text=stripped, level=0)

    text = lstripped[len(_BODY_SUB_BULLET_PREFIX):]
    if not text:
        return None
    indent = len(stripped) - len(lstripped)
    return BulletItem(text=text, level=2 if indent >= 2 else 1)
