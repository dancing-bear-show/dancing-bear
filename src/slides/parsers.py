"""Input parsers that produce SlideDeck objects from various formats.

Converts markdown, CSV, outline files, and dict-list data into typed
SlideDeck/SlideContent/TableSlide/BulletItem objects for SlideGenerator.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from slides.constants import (
    DEFAULT_BULLET_LEVEL,
    DEFAULT_TEMPLATE_SLIDE_INDEX,
    DEFAULT_THEME_COLOR,
    DEFAULT_TITLE,
    LAYOUT_BULLET,
    LAYOUT_SECTION,
    RESERVED_LAYOUT_KEY,
    LAYOUT_TABLE,
    YAML_AUTHOR,
    YAML_BODY,
    YAML_BOLD,
    YAML_BULLETS,
    YAML_DATE,
    YAML_FIRST_COL_WIDTH,
    YAML_HEADERS,
    YAML_HIGHLIGHT,
    YAML_IMAGE,
    YAML_LAYOUT,
    YAML_LAYOUT_MAP,
    YAML_LEVEL,
    YAML_MERMAID,
    YAML_NOTES,
    YAML_ROWS,
    YAML_SLIDES,
    YAML_SUBTITLE,
    YAML_TEMPLATE_PATH,
    YAML_TEMPLATE_SLIDE_INDEX,
    YAML_TEXT,
    YAML_THEME_COLOR,
    YAML_TITLE,
    YAML_URL,
)
from slides.schema import (
    BulletItem,
    DeckMetadata,
    SlideContent,
    SlideDeck,
    TableSlide,
)

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


# Maximum bullets per slide before auto-pagination
DEFAULT_BULLET_LIMIT = 8

# Regex for inline markdown bold: **text**
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
# Regex for inline markdown code: `text`
_CODE_RE = re.compile(r"`(.+?)`")
# Regex for slide section separator
_SECTION_SEP_RE = re.compile(r"^\s*---\s*$", re.MULTILINE)
# Regex for markdown headings
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
# Regex for bullet lines (-, *, •, numbered)
_BULLET_RE = re.compile(r"^(\s*)([-*•]|\d+\.)\s+(.*)$")
# Regex for **Title:** directive
_TITLE_DIRECTIVE_RE = re.compile(r"^\*\*Title:\*\*\s*(.+)$")
# Regex for **Subtitle:** directive
_SUBTITLE_DIRECTIVE_RE = re.compile(r"^\*\*Subtitle:\*\*\s*(.+)$")
# Regex for **Layout:** directive
_LAYOUT_DIRECTIVE_RE = re.compile(r"^\*\*Layout:\*\*\s*(.+)$")
# Regex to strip "Slide N:" prefixes
_SLIDE_PREFIX_RE = re.compile(r"^\s*Slide\s+\d+\s*[:\-—–]\s*", re.IGNORECASE)
# Outline slide pattern: "- Slide N — Title [optional]"
_OUTLINE_SLIDE_RE = re.compile(r"^-\s*Slide\s+\d+\s+—\s+(.*?)(\s*\[.*\])?\s*$")
# Outline prompt pattern: "- Prompt (on slide): text"
_OUTLINE_PROMPT_RE = re.compile(r"^-\s*Prompt \(on slide\):\s*(.*)$")


def _normalize_title(title: str) -> str:
    """Strip 'Slide N:' prefixes from titles."""
    if not title:
        return title
    return _SLIDE_PREFIX_RE.sub("", title).strip()


def _extract_highlights(text: str) -> tuple[str, list[str]]:
    """Extract bold/code segments as highlights, return cleaned text and highlights list."""
    highlights: list[str] = []

    for match in _BOLD_RE.finditer(text):
        highlights.append(match.group(1))

    for match in _CODE_RE.finditer(text):
        highlights.append(match.group(1))

    # Remove markdown formatting, keep inner text
    cleaned = _BOLD_RE.sub(r"\1", text)
    cleaned = _CODE_RE.sub(r"\1", cleaned)

    return cleaned, highlights


def _parse_bullet_line(line: str) -> BulletItem | None:
    """Parse a single line as a bullet item with level detection."""
    m = _BULLET_RE.match(line)
    if not m:
        return None

    indent = len(m.group(1))
    raw_text = m.group(3).strip()
    if not raw_text:
        return None

    # Determine indent level from whitespace (0, 1, 2)
    level = min(indent // 2, 2) if indent > 0 else 0

    cleaned, highlights = _extract_highlights(raw_text)
    return BulletItem(text=cleaned, level=level, highlight=highlights)


def _split_slide_into_chunks(
    slide: SlideContent, bullet_limit: int,
) -> list[SlideContent]:
    """Split a single slide into continuation slides at the bullet limit."""
    chunks: list[SlideContent] = []
    for i in range(0, len(slide.bullets), bullet_limit):
        is_first = i == 0
        chunks.append(SlideContent(
            title=slide.title if is_first else f"{slide.title} (cont.)",
            subtitle=slide.subtitle if is_first else None,
            bullets=slide.bullets[i : i + bullet_limit],
            notes=slide.notes if is_first else None,
            layout=slide.layout,
        ))
    return chunks


def _chunk_slides(
    slides: list[SlideContent],
    bullet_limit: int = DEFAULT_BULLET_LIMIT,
) -> list[SlideContent]:
    """Split slides with too many bullets into continuation slides."""
    if bullet_limit <= 0:
        return list(slides)
    result: list[SlideContent] = []
    for slide in slides:
        # Table slides are not bullet-based; pass through unchanged
        if isinstance(slide, TableSlide):
            result.append(slide)
            continue
        if len(slide.bullets) <= bullet_limit:
            result.append(slide)
            continue
        result.extend(_split_slide_into_chunks(slide, bullet_limit))

    return result


def load_deck_from_markdown(
    md_path: str | Path,
    *,
    title: str | None = None,
    author: str | None = None,
    template_path: str | None = None,
    template_slide_index: int = DEFAULT_TEMPLATE_SLIDE_INDEX,
    theme_color: str = DEFAULT_THEME_COLOR,
    bullet_limit: int = DEFAULT_BULLET_LIMIT,
) -> SlideDeck:
    """Parse a markdown file into a SlideDeck.

    Markdown format: slides separated by `---` lines. Each section can have:
    - `# Heading` → slide title
    - `**Title:** text` → explicit title override
    - `**Subtitle:** text` → subtitle
    - `**Layout:** section` → layout override
    - `- bullet` / `* bullet` / `1. bullet` → bullet items
    - Indented bullets (2+ spaces) → sub-bullets (level 1, 2)
    - `**bold**` and `` `code` `` → highlights

    Args:
        md_path: Path to markdown file
        title: Deck title (default: first slide title)
        author: Deck author
        template_path: Path to template .pptx
        template_slide_index: Template slide index
        theme_color: Theme color name
        bullet_limit: Max bullets per slide before auto-pagination

    Returns:
        SlideDeck with parsed slides
    """
    path = Path(md_path)
    text = path.read_text(encoding="utf-8")
    sections = _SECTION_SEP_RE.split(text)

    slides: list[SlideContent] = []
    for section in sections:
        lines = [ln.rstrip() for ln in section.splitlines()]
        stripped = [ln for ln in lines if ln.strip()]
        if not stripped:
            continue

        slide = _parse_markdown_section(stripped)
        if slide:
            slides.append(slide)

    # Auto-paginate
    slides = _chunk_slides(slides, bullet_limit)

    deck_title = title or (slides[0].title if slides else "Untitled")

    metadata = DeckMetadata(
        title=deck_title,
        author=author,
        template_slide_index=template_slide_index,
        theme_color=theme_color,
    )

    return SlideDeck(
        metadata=metadata,
        slides=slides,
        template_path=template_path,
    )


def _try_parse_directive(
    stripped: str,
    slide_title: str,
) -> tuple[str, str | None, str | None, int] | None:
    """Try to match a line against known directives.

    Returns (directive_type, value, layout_override, heading_level) on match,
    or None if no directive matched.
    """
    m = _TITLE_DIRECTIVE_RE.match(stripped)
    if m:
        return ("title", _normalize_title(m.group(1).strip()), None, 0)

    m = _SUBTITLE_DIRECTIVE_RE.match(stripped)
    if m:
        return ("subtitle", m.group(1).strip(), None, 0)

    m = _LAYOUT_DIRECTIVE_RE.match(stripped)
    if m:
        layout_value = m.group(1).strip().lower().replace(" ", "_").replace("-", "_")
        layout_override = LAYOUT_SECTION if layout_value in ("section", "section_header") else None
        return ("layout", None, layout_override, 0)

    m = _HEADING_RE.match(stripped)
    if m and not slide_title:
        return ("heading", _normalize_title(m.group(2).strip()), None, len(m.group(1)))

    return None


def _parse_markdown_section(lines: list[str]) -> SlideContent | None:
    """Parse a single markdown section into a SlideContent."""
    slide_title = ""
    subtitle = None
    layout = LAYOUT_BULLET
    bullets: list[str | BulletItem] = []
    heading_level = 0

    for line in lines:
        stripped = line.strip()

        result = _try_parse_directive(stripped, slide_title)
        if result is not None:
            slide_title, subtitle, layout, heading_level = _apply_directive(
                result, slide_title, subtitle, layout, heading_level,
            )
            continue

        bullet = _parse_bullet_line(line)
        if bullet:
            bullets.append(bullet)

    if not slide_title and not bullets:
        return None

    slide_title = slide_title or "Untitled"

    # H2 headings default to section layout if no bullets
    if heading_level == 2 and not bullets:
        layout = LAYOUT_SECTION

    return SlideContent(
        title=slide_title,
        subtitle=subtitle,
        bullets=bullets,
        layout=layout,
    )


def _apply_directive(
    result: tuple[str, str | None, str | None, int],
    slide_title: str,
    subtitle: str | None,
    layout: str,
    heading_level: int,
) -> tuple[str, str | None, str, int]:
    """Apply a parsed directive to the current slide state."""
    dtype, value, layout_override, hlevel = result
    if dtype == "title":
        slide_title = value or ""
    elif dtype == "subtitle":
        subtitle = value
    elif dtype == "layout" and layout_override:
        layout = layout_override
    elif dtype == "heading":
        heading_level = hlevel
        slide_title = value or ""
    return slide_title, subtitle, layout, heading_level


def load_deck_from_outline(
    outline_path: str | Path,
    *,
    title: str | None = None,
    author: str | None = None,
    template_path: str | None = None,
    template_slide_index: int = DEFAULT_TEMPLATE_SLIDE_INDEX,
    theme_color: str = DEFAULT_THEME_COLOR,
) -> SlideDeck:
    """Parse an outline markdown file into a SlideDeck.

    Outline format (from presentation-publisher legacy):
    ```
    - Slide 1 — Introduction [optional tag]
    - Prompt (on slide): Welcome to the presentation
    - Prompt (on slide): Today we'll cover...
    ```

    Args:
        outline_path: Path to outline markdown file
        title: Deck title
        author: Deck author
        template_path: Path to template .pptx
        template_slide_index: Template slide index
        theme_color: Theme color name

    Returns:
        SlideDeck with parsed slides
    """
    path = Path(outline_path)
    text = path.read_text(encoding="utf-8")

    slides: list[SlideContent] = []
    current_title: str | None = None
    current_bullets: list[str | BulletItem] = []

    for line in text.splitlines():
        stripped = line.strip()

        # Check for slide definition
        m = _OUTLINE_SLIDE_RE.match(stripped)
        if m:
            # Save previous slide
            if current_title:
                slides.append(SlideContent(
                    title=current_title,
                    bullets=current_bullets,
                ))
            current_title = m.group(1).strip()
            current_bullets = []
            continue

        # Check for prompt
        m = _OUTLINE_PROMPT_RE.match(stripped)
        if m and current_title is not None:
            prompt_text = m.group(1).strip()
            if prompt_text:
                cleaned, highlights = _extract_highlights(prompt_text)
                current_bullets.append(BulletItem(
                    text=cleaned,
                    highlight=highlights,
                ))

    # Save last slide
    if current_title:
        slides.append(SlideContent(
            title=current_title,
            bullets=current_bullets,
        ))

    deck_title = title or (slides[0].title if slides else "Untitled")

    metadata = DeckMetadata(
        title=deck_title,
        author=author,
        template_slide_index=template_slide_index,
        theme_color=theme_color,
    )

    return SlideDeck(
        metadata=metadata,
        slides=slides,
        template_path=template_path,
    )


def load_deck_from_csv(
    csv_path: str | Path,
    *,
    title: str = "Untitled",
    author: str | None = None,
    template_path: str | None = None,
    template_slide_index: int = DEFAULT_TEMPLATE_SLIDE_INDEX,
    theme_color: str = DEFAULT_THEME_COLOR,
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
        title: Deck title
        author: Deck author
        template_path: Path to template .pptx
        template_slide_index: Template slide index
        theme_color: Theme color name
        title_column: Column name for slide titles
        text_column: Column name for bullet text
        bullet_limit: Max bullets per slide before auto-pagination

    Returns:
        SlideDeck with parsed slides
    """
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
