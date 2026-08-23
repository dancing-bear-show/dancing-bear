"""Dict/YAML deck parsing into SlideDeck objects.

Converts pre-parsed dict structures (from YAML or JSON) into typed
SlideDeck/SlideContent/TableSlide objects.
"""

from __future__ import annotations

from typing import Any

from slides._parse_bullets import _body_to_bullets, _parse_bullets
from slides.constants import (
    DEFAULT_TEMPLATE_SLIDE_INDEX,
    DEFAULT_THEME_COLOR,
    DEFAULT_TITLE,
    LAYOUT_BULLET,
    LAYOUT_TABLE,
    RESERVED_LAYOUT_KEY,
    YAML_AUTHOR,
    YAML_BODY,
    YAML_BULLETS,
    YAML_DATE,
    YAML_FIRST_COL_WIDTH,
    YAML_HEADERS,
    YAML_IMAGE,
    YAML_LAYOUT,
    YAML_LAYOUT_MAP,
    YAML_MERMAID,
    YAML_NOTES,
    YAML_ROWS,
    YAML_SLIDES,
    YAML_SUBTITLE,
    YAML_TEMPLATE_PATH,
    YAML_TEMPLATE_SLIDE_INDEX,
    YAML_THEME_COLOR,
    YAML_TITLE,
)
from slides.schema import (
    BulletItem,
    DeckMetadata,
    SlideContent,
    SlideDeck,
    TableSlide,
)


def _parse_slide(slide_data: dict[str, Any]) -> SlideContent:
    """Parse a single slide definition from YAML data."""
    layout = slide_data.get(YAML_LAYOUT, LAYOUT_BULLET)

    # Support body: as alternative to bullets: (multiline string -> bullet items)
    raw_bullets = slide_data.get(YAML_BULLETS)
    if raw_bullets is None:
        raw_bullets = []
    elif not isinstance(raw_bullets, list):
        slide_title = slide_data.get(YAML_TITLE)
        context = f" for slide {slide_title!r}" if isinstance(slide_title, str) and slide_title else ""
        raise ValueError(
            f"{YAML_BULLETS} must be a list, got {type(raw_bullets).__name__}{context}"
        )
    body_text = slide_data.get(YAML_BODY)
    if not raw_bullets and body_text and isinstance(body_text, str):
        bullets: list[str | BulletItem] = list(_body_to_bullets(body_text))
    else:
        bullets = list(_parse_bullets(raw_bullets))

    subtitle = slide_data.get(YAML_SUBTITLE)

    if layout == LAYOUT_TABLE:
        return TableSlide(
            title=slide_data.get(YAML_TITLE, ""),
            subtitle=subtitle,
            bullets=bullets,
            notes=slide_data.get(YAML_NOTES),
            headers=slide_data.get(YAML_HEADERS, []),
            rows=slide_data.get(YAML_ROWS, []),
            first_col_width=slide_data.get(YAML_FIRST_COL_WIDTH),
        )
    return SlideContent(
        title=slide_data.get(YAML_TITLE, ""),
        subtitle=subtitle,
        bullets=bullets,
        notes=slide_data.get(YAML_NOTES),
        layout=layout,
        image=slide_data.get(YAML_IMAGE),
        mermaid=slide_data.get(YAML_MERMAID),
    )


def _parse_layout_map(raw: dict[str, object] | None) -> dict[str, int] | None:
    """Validate and convert a raw layout_map dict to typed form.

    Each value must be a non-negative integer representing a 0-indexed
    template slide position.

    Args:
        raw: Raw dict from YAML, or None

    Returns:
        Validated dict mapping layout names to slide indices, or None

    Raises:
        ValueError: If any index is not a non-negative integer
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(
            f"layout_map must be a mapping, got {type(raw).__name__}"
        )
    _RESERVED_KEYS = {RESERVED_LAYOUT_KEY}
    result: dict[str, int] = {}
    for key, val in raw.items():
        str_key = str(key)
        if str_key in _RESERVED_KEYS:
            raise ValueError(
                f"layout_map key {str_key!r} is reserved and cannot be used"
            )
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise ValueError(
                f"layout_map[{key!r}] must be a non-negative integer, got {val!r}"
            )
        result[str_key] = val
    return result


def load_deck_from_dict(
    data: dict[str, Any],
    *,
    template_path: str | None = None,
) -> SlideDeck:
    """Parse a dict/JSON structure into a SlideDeck.

    Expected structure:
    ```json
    {
        "title": "Deck Title",
        "author": "Author Name",
        "theme_color": "LIGHT_2",
        "template_path": "path/to/template.pptx",
        "template_slide_index": 0,
        "slides": [
            {
                "title": "Slide 1",
                "subtitle": "Optional",
                "layout": "bullet",
                "bullets": ["Item 1", "Item 2"],
                "notes": "Speaker notes"
            },
            {
                "title": "Data Table",
                "layout": "table",
                "headers": ["Name", "Value"],
                "rows": [["A", "1"], ["B", "2"]]
            }
        ]
    }
    ```

    This is equivalent to load_deck_from_yaml but accepts a pre-parsed dict.

    Args:
        data: Dictionary with deck structure
        template_path: Override template path

    Returns:
        SlideDeck with parsed slides
    """
    layout_map = _parse_layout_map(data.get(YAML_LAYOUT_MAP))

    metadata = DeckMetadata(
        title=data.get(YAML_TITLE, DEFAULT_TITLE),
        author=data.get(YAML_AUTHOR),
        date=str(data[YAML_DATE]) if data.get(YAML_DATE) is not None else None,
        template_slide_index=data.get(YAML_TEMPLATE_SLIDE_INDEX, DEFAULT_TEMPLATE_SLIDE_INDEX),
        theme_color=data.get(YAML_THEME_COLOR, DEFAULT_THEME_COLOR),
        layout_map=layout_map,
    )

    raw_slides = data.get(YAML_SLIDES)
    if raw_slides is None:
        raw_slides = []
    elif not isinstance(raw_slides, list):
        deck_title = data.get(YAML_TITLE)
        context = f" (deck: {deck_title!r})" if isinstance(deck_title, str) and deck_title else ""
        raise ValueError(
            f"{YAML_SLIDES} must be a YAML list of slide mappings, "
            f"got {type(raw_slides).__name__}{context}"
        )
    slides = [_parse_slide(sd) for sd in raw_slides]

    return SlideDeck(
        metadata=metadata,
        slides=slides,
        template_path=template_path or data.get(YAML_TEMPLATE_PATH),
    )
