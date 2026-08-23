"""Markdown and outline loaders that produce SlideDeck objects.

Parses `---`-separated markdown sections and legacy "Slide N — Title" outline
files into typed SlideDeck/SlideContent objects.
"""

from __future__ import annotations

import re
from pathlib import Path

from slides._parse_text import (
    DEFAULT_BULLET_LIMIT,
    _chunk_slides,
    _extract_highlights,
    _normalize_title,
    _parse_bullet_line,
)
from slides.constants import (
    DEFAULT_TEMPLATE_SLIDE_INDEX,
    DEFAULT_THEME_COLOR,
    LAYOUT_BULLET,
    LAYOUT_SECTION,
)
from slides.schema import (
    BulletItem,
    DeckMetadata,
    SlideContent,
    SlideDeck,
)

# Regex for slide section separator
_SECTION_SEP_RE = re.compile(r"^\s*---\s*$", re.MULTILINE)
# Regex for markdown headings
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
# Regex for **Title:** directive
_TITLE_DIRECTIVE_RE = re.compile(r"^\*\*Title:\*\*\s*(.+)$")
# Regex for **Subtitle:** directive
_SUBTITLE_DIRECTIVE_RE = re.compile(r"^\*\*Subtitle:\*\*\s*(.+)$")
# Regex for **Layout:** directive
_LAYOUT_DIRECTIVE_RE = re.compile(r"^\*\*Layout:\*\*\s*(.+)$")
# Outline slide pattern: "- Slide N — Title [optional]"
_OUTLINE_SLIDE_RE = re.compile(r"^-\s*Slide\s+\d+\s+—\s+(.*?)(\s*\[.*\])?\s*$")
# Outline prompt pattern: "- Prompt (on slide): text"
_OUTLINE_PROMPT_RE = re.compile(r"^-\s*Prompt \(on slide\):\s*(.*)$")


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
