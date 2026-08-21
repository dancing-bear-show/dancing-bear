"""Dataclasses for slide deck definitions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BulletItem:
    """A single bullet point with optional indentation and highlights."""

    text: str
    level: int = 0  # 0 = top level, 1 = sub-bullet, 2 = sub-sub-bullet
    highlight: list[str] = field(default_factory=list)  # Text segments to highlight
    bold: bool = False
    url: str | None = None  # Clickable hyperlink target


@dataclass
class SlideContent:
    """Content for a single slide."""

    title: str
    subtitle: str | None = None
    bullets: list[str | BulletItem] = field(default_factory=list)
    notes: str | None = None
    layout: str = "bullet"  # bullet, table, title_only, section
    image: str | None = None  # Path to image file (PNG, JPG)
    mermaid: str | None = None  # Mermaid diagram source (rendered to PNG at generate time)


@dataclass
class TableSlide(SlideContent):
    """Table slide with header and rows."""

    headers: list[str] = field(default_factory=list)
    rows: list[list[object]] = field(default_factory=list)
    layout: str = "table"
    first_col_width: float | None = None  # Width of first column in inches


@dataclass
class DeckMetadata:
    """Metadata for a slide deck."""

    title: str
    author: str | None = None
    date: str | None = None  # May be str or datetime.date from YAML parsing
    template_slide_index: int = 0  # 0-indexed fallback for legacy mode; ignored when master layouts resolve
    theme_color: str = "LIGHT_2"  # MSO_THEME_COLOR value
    layout_map: dict[str, int] | None = None  # Maps layout names to template slide indices


@dataclass
class SlideDeck:
    """Complete slide deck definition."""

    metadata: DeckMetadata
    slides: list[SlideContent] = field(default_factory=list)
    template_path: str | None = None  # Path to template .pptx
