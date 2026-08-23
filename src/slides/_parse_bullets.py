"""Bullet parsing primitives shared by the slide deck input parsers.

Converts dict, list/tuple, string, and multiline-body bullet definitions into
typed BulletItem objects.
"""

from __future__ import annotations

from slides.constants import (
    DEFAULT_BULLET_LEVEL,
    YAML_BOLD,
    YAML_HIGHLIGHT,
    YAML_LEVEL,
    YAML_TEXT,
    YAML_URL,
)
from slides.schema import BulletItem


def _validate_bullet_level(raw: object, context: str = "") -> int:
    """Validate and coerce a bullet level value to int.

    Rejects bools (YAML true/false) and negative values.
    """
    if isinstance(raw, bool):
        raise ValueError(
            f"Bullet level must be an integer, got bool {raw!r}"
            + (f" for {context}" if context else "")
        )
    try:
        level = int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"Bullet level must be an integer, got {type(raw).__name__} {raw!r}"
            + (f" for {context}" if context else "")
        ) from None
    if level < 0:
        raise ValueError(
            f"Bullet level must be non-negative, got {level}"
            + (f" for {context}" if context else "")
        )
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


def _parse_bullets(raw_bullets: list[object]) -> list[BulletItem]:
    """Parse bullet items from YAML data into BulletItem objects."""
    bullets: list[BulletItem] = []
    for b in raw_bullets:
        if isinstance(b, dict):
            bullets.append(_parse_dict_bullet(b))
        elif isinstance(b, (list, tuple)):
            bullets.append(_parse_list_bullet(b))
        elif isinstance(b, str):
            bullets.append(_parse_str_bullet(b))
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
        stripped = line.rstrip()
        if not stripped:
            continue
        lstripped = stripped.lstrip()
        indent = len(stripped) - len(lstripped)
        if lstripped.startswith("- ") and indent >= 2:
            text = lstripped[2:]
            if text:
                items.append(BulletItem(text=text, level=2))
        elif lstripped.startswith("- "):
            text = lstripped[2:]
            if text:
                items.append(BulletItem(text=text, level=1))
        else:
            items.append(BulletItem(text=stripped, level=0))
    return items
