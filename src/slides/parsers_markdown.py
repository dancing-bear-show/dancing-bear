"""Markdown and outline loaders that produce SlideDeck objects.

Parses `---`-separated markdown sections and legacy "Slide N — Title" outline
files into typed SlideDeck/SlideContent objects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from slides._parse_text import (
    DEFAULT_BULLET_LIMIT,
    _chunk_slides,
    _extract_highlights,
    _normalize_title,
    _parse_bullet_line,
)
from slides.constants import (
    DEFAULT_TITLE,
    LAYOUT_BULLET,
    LAYOUT_SECTION,
)
from slides.schema import (
    BulletItem,
    DeckMetadata,
    DeckOptions,
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

# **Layout:** values that select the section layout, after normalization.
_SECTION_LAYOUT_ALIASES = frozenset({"section", "section_header"})


def load_deck_from_markdown(
    md_path: str | Path,
    *,
    options: DeckOptions | None = None,
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
        options: Common deck-metadata options (title, author, template_path,
            template_slide_index, theme_color); defaults applied when None.
            title falls back to the first slide's title when None OR empty
            (a truthiness check), unlike the CSV loader, which keeps an
            explicitly empty title.
        bullet_limit: Max bullets per slide before auto-pagination

    Returns:
        SlideDeck with parsed slides
    """
    opts = options or DeckOptions()

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

    deck_title = opts.title or (slides[0].title if slides else DEFAULT_TITLE)

    metadata = DeckMetadata(
        title=deck_title,
        author=opts.author,
        template_slide_index=opts.template_slide_index,
        theme_color=opts.theme_color,
    )

    return SlideDeck(
        metadata=metadata,
        slides=slides,
        template_path=opts.template_path,
    )


@dataclass(frozen=True)
class _SectionState:
    """Accumulated state while parsing one markdown section."""

    title: str = ""
    subtitle: str | None = None
    layout: str = LAYOUT_BULLET
    heading_level: int = 0


def _evolve(state: _SectionState, **changes: object) -> _SectionState:
    """Typed wrapper for dataclasses.replace.

    `replace` is stubbed as returning `DataclassInstance`, so callers lose the
    concrete type. The cast pins it back to `_SectionState` -- without it the
    declared return type contradicts the stub and the checker flags every call.
    """
    return cast(_SectionState, replace(state, **changes))


@dataclass(frozen=True)
class _Directive:
    """A matched markdown directive and the state change it implies."""

    kind: str
    value: str | None = None
    layout_override: str | None = None
    heading_level: int = 0

    def apply(self, state: _SectionState) -> _SectionState:
        """Return a new state with this directive applied."""
        if self.kind == "title":
            return _evolve(state, title=self.value or "")
        if self.kind == "subtitle":
            return _evolve(state, subtitle=self.value)
        if self.kind == "layout" and self.layout_override:
            return _evolve(state, layout=self.layout_override)
        if self.kind == "heading":
            return _evolve(state, title=self.value or "", heading_level=self.heading_level)
        return state


def _try_parse_directive(stripped: str, slide_title: str) -> _Directive | None:
    """Match a line against the known directives, or return None."""
    m = _TITLE_DIRECTIVE_RE.match(stripped)
    if m:
        return _Directive("title", _normalize_title(m.group(1).strip()))

    m = _SUBTITLE_DIRECTIVE_RE.match(stripped)
    if m:
        return _Directive("subtitle", m.group(1).strip())

    m = _LAYOUT_DIRECTIVE_RE.match(stripped)
    if m:
        layout_value = m.group(1).strip().lower().replace(" ", "_").replace("-", "_")
        layout_override = LAYOUT_SECTION if layout_value in _SECTION_LAYOUT_ALIASES else None
        return _Directive("layout", layout_override=layout_override)

    m = _HEADING_RE.match(stripped)
    if m and not slide_title:
        return _Directive(
            "heading", _normalize_title(m.group(2).strip()), heading_level=len(m.group(1))
        )

    return None


def _parse_markdown_section(lines: list[str]) -> SlideContent | None:
    """Parse a single markdown section into a SlideContent."""
    state = _SectionState()
    bullets: list[str | BulletItem] = []

    for line in lines:
        directive = _try_parse_directive(line.strip(), state.title)
        if directive is not None:
            state = directive.apply(state)
            continue

        bullet = _parse_bullet_line(line)
        if bullet:
            bullets.append(bullet)

    if not state.title and not bullets:
        return None

    # An H2 with no bullets is a section divider, not a content slide.
    layout = LAYOUT_SECTION if state.heading_level == 2 and not bullets else state.layout

    return SlideContent(
        title=state.title or DEFAULT_TITLE,
        subtitle=state.subtitle,
        bullets=bullets,
        layout=layout,
    )


def _outline_prompt_bullet(stripped: str) -> BulletItem | None:
    """Return the BulletItem for a "Prompt (on slide):" line, or None."""
    m = _OUTLINE_PROMPT_RE.match(stripped)
    if not m:
        return None
    prompt_text = m.group(1).strip()
    if not prompt_text:
        return None
    cleaned, highlights = _extract_highlights(prompt_text)
    return BulletItem(text=cleaned, highlight=highlights)


def _parse_outline_slides(text: str) -> list[SlideContent]:
    """Split outline text into SlideContent objects.

    A "- Slide N — Title" line opens a slide; subsequent prompt lines become
    its bullets. The slide in progress is emitted when the next one opens and
    again at end of input.
    """
    slides: list[SlideContent] = []
    current_title: str | None = None
    current_bullets: list[str | BulletItem] = []

    def flush() -> None:
        if current_title:
            slides.append(SlideContent(title=current_title, bullets=current_bullets))

    for line in text.splitlines():
        stripped = line.strip()

        m = _OUTLINE_SLIDE_RE.match(stripped)
        if m:
            flush()
            current_title = m.group(1).strip()
            current_bullets = []
            continue

        if current_title is not None:
            bullet = _outline_prompt_bullet(stripped)
            if bullet is not None:
                current_bullets.append(bullet)

    flush()
    return slides


def load_deck_from_outline(
    outline_path: str | Path,
    *,
    options: DeckOptions | None = None,
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
        options: Common deck-metadata options (title, author, template_path,
            template_slide_index, theme_color); defaults applied when None.
            title falls back to the first slide's title when None OR empty
            (a truthiness check), unlike the CSV loader, which keeps an
            explicitly empty title.

    Returns:
        SlideDeck with parsed slides
    """
    opts = options or DeckOptions()

    path = Path(outline_path)
    slides = _parse_outline_slides(path.read_text(encoding="utf-8"))

    deck_title = opts.title or (slides[0].title if slides else DEFAULT_TITLE)

    metadata = DeckMetadata(
        title=deck_title,
        author=opts.author,
        template_slide_index=opts.template_slide_index,
        theme_color=opts.theme_color,
    )

    return SlideDeck(
        metadata=metadata,
        slides=slides,
        template_path=opts.template_path,
    )
