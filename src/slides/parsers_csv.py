"""CSV loader that produces SlideDeck objects.

Groups CSV rows into bullet slides by a title column, or renders the whole
file as a single table slide when no title/text columns are present.
"""

from __future__ import annotations

import csv
from pathlib import Path

from slides._parse_text import (
    DEFAULT_BULLET_LIMIT,
    _chunk_slides,
    _extract_highlights,
)
from slides.constants import DEFAULT_TITLE
from slides.schema import (
    BulletItem,
    DeckMetadata,
    DeckOptions,
    SlideContent,
    SlideDeck,
    TableSlide,
)


def load_deck_from_csv(
    csv_path: str | Path,
    *,
    options: DeckOptions | None = None,
    title_column: str = "slide_title",
    text_column: str = "summary",
    bullet_limit: int = DEFAULT_BULLET_LIMIT,
) -> SlideDeck:
    """Parse a CSV file into a SlideDeck.

    Groups rows by title column, with text column values becoming bullets.
    If the CSV has columns that look like table data (3+ columns, no
    slide_title), creates a single table slide instead.

    Args:
        csv_path: Path to CSV file
        options: Common deck-metadata options (title, author, template_path,
            template_slide_index, theme_color); defaults applied when None.
        title_column: Column name for slide titles
        text_column: Column name for bullet text
        bullet_limit: Max bullets per slide before auto-pagination

    Returns:
        SlideDeck with parsed slides
    """
    opts = options or DeckOptions()
    # `is None`, not `or`: this loader's title default used to be a concrete
    # DEFAULT_TITLE parameter, so an explicitly passed empty string reached the
    # deck unchanged. `or` would silently rewrite it to "Untitled".
    title = DEFAULT_TITLE if opts.title is None else opts.title
    author = opts.author
    template_path = opts.template_path
    template_slide_index = opts.template_slide_index
    theme_color = opts.theme_color

    path = Path(csv_path)

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        metadata = DeckMetadata(title=title, author=author,
                                template_slide_index=template_slide_index,
                                theme_color=theme_color)
        return SlideDeck(metadata=metadata, slides=[], template_path=template_path)

    headers = list(rows[0].keys())

    # If CSV has title/text columns, group into bullet slides
    if title_column in headers and text_column in headers:
        slides = _csv_to_bullet_slides(rows, title_column, text_column)
    else:
        # Treat as table data
        slides = [_csv_to_table_slide(title, headers, rows)]

    slides = _chunk_slides(slides, bullet_limit)

    metadata = DeckMetadata(
        title=title,
        author=author,
        template_slide_index=template_slide_index,
        theme_color=theme_color,
    )

    return SlideDeck(
        metadata=metadata,
        slides=slides,
        template_path=template_path,
    )


def _csv_to_bullet_slides(
    rows: list[dict[str, str]],
    title_column: str,
    text_column: str,
) -> list[SlideContent]:
    """Group CSV rows by title into bullet slides."""
    slide_map: dict[str, list[str | BulletItem]] = {}
    order: list[str] = []

    for row in rows:
        slide_title = str(row.get(title_column) or "Slide").strip() or "Slide"
        text = str(row.get(text_column) or "").strip()
        if not text:
            continue

        if slide_title not in slide_map:
            slide_map[slide_title] = []
            order.append(slide_title)

        cleaned, highlights = _extract_highlights(text)
        slide_map[slide_title].append(BulletItem(
            text=cleaned,
            highlight=highlights,
        ))

    return [
        SlideContent(title=t, bullets=slide_map[t])
        for t in order
    ]


def _csv_to_table_slide(
    title: str,
    headers: list[str],
    rows: list[dict[str, str]],
) -> TableSlide:
    """Convert CSV data into a single table slide."""
    table_rows: list[list[object]] = [
        [str(row.get(h) or "") for h in headers]
        for row in rows
    ]
    return TableSlide(
        title=title,
        headers=headers,
        rows=table_rows,
    )
