"""Dataclasses for slide deck definitions."""

from __future__ import annotations

from dataclasses import dataclass, field

from slides.constants import DEFAULT_TEMPLATE_SLIDE_INDEX, DEFAULT_THEME_COLOR


@dataclass
class BulletItem:
    """A single bullet point with optional indentation and highlights."""

    text: str
    level: int = 0  # 0 = top level, 1 = sub-bullet, 2 = sub-sub-bullet
    highlight: list[str] = field(default_factory=list)  # Text segments to highlight
    bold: bool = False
    url: str | None = None  # Clickable hyperlink target


@dataclass(frozen=True)
class ResolvedBullet:
    """A bullet normalized to its render-time fields.

    Both BulletItem and a plain string collapse to this, so renderers do not
    need to re-check the input type at each use site.
    """

    text: str
    level: int = 0
    highlight: list[str] = field(default_factory=list)
    bold: bool = False
    url: str | None = None

    @classmethod
    def from_item(cls, item: "str | BulletItem") -> "ResolvedBullet":
        """Normalize a BulletItem or plain string into a ResolvedBullet."""
        if isinstance(item, BulletItem):
            return cls(
                text=item.text,
                level=item.level,
                highlight=item.highlight,
                bold=item.bold,
                url=item.url,
            )
        return cls(text=str(item))


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


@dataclass(frozen=True)
class DeckOptions:
    """Common deck-metadata options shared by the CSV, Markdown, and Outline parsers.

    Bundles the five metadata fields that every parser accepts so callers can
    construct one object and pass it to whichever loader they use, reducing
    per-function parameter counts.
    """

    # None means "unset" so each parser can apply its own fallback: the CSV
    # loader substitutes DEFAULT_TITLE, while the markdown/outline loaders fall
    # back to the first slide's title. A concrete default here would erase that
    # distinction.
    #
    # The loaders differ on what an explicitly EMPTY title means, and that
    # predates this dataclass:
    #   - CSV took `title: str = DEFAULT_TITLE`, so "" was a real title and
    #     reached the deck unchanged. It still does (`is None`).
    #   - markdown/outline took `title: str | None = None` and have always
    #     used a truthiness check, so "" falls back to the first slide title.
    # Both behaviours are preserved deliberately; changing either would alter
    # rendered output for callers who pass "". Read the loader before assuming
    # `is None` semantics.
    title: str | None = None
    author: str | None = None
    template_path: str | None = None
    template_slide_index: int = DEFAULT_TEMPLATE_SLIDE_INDEX
    theme_color: str = DEFAULT_THEME_COLOR
