"""Configuration dataclasses for resume rendering.

Reduces parameter count by grouping related rendering options.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BulletConfig:
    """Configuration for bullet rendering.

    ``list_style``/``plain`` are gone: they selected between a Word
    ``List Bullet`` paragraph and a literal-glyph paragraph, and the standard
    layout now has exactly one bullet mechanism. See
    ``BulletRenderer.new_bullet_paragraph``.
    """

    glyph: str = "•"
    sep: str = ": "  # Separator for named bullets


@dataclass
class HeaderLineConfig:
    """Configuration for header line rendering."""

    title_text: str = ""
    company_text: str = ""
    loc_text: str = ""
    span_text: str = ""
    style: str = "Normal"


@dataclass
class MetaRunConfig:
    """Configuration for metadata run rendering (location, duration)."""

    brackets: bool = True
    open_br: str = "["
    close_br: str = "]"
    meta_pt: float | None = None
    color: str | None = None
    italic: bool = False


@dataclass(frozen=True)
class CenteredHeaderLineStyle:
    """Style options for a centered, shaded header line."""

    size_pt: float
    color: str
    bold: bool
    after_pt: float
    bg_rgb: tuple | None = None


@dataclass
class RenderContext:
    """Common rendering context shared across functions."""

    sec: dict[str, Any] | None = None  # Section config
    keywords: list[str] | None = None  # Keywords to highlight/bold


@dataclass
class IndentedRunStyle:
    """Style options for indented paragraph runs."""

    italic: bool = False
    size_offset: int = 0
    color: str = "#666666"
    after_pt: int = 0


@dataclass
class ExperienceFilterConfig:
    """Configuration for experience filtering."""

    max_roles: int | None = None
    max_bullets_per_role: int | None = None
    min_score: int = 1


@dataclass
class ExperienceRenderConfig:
    """Configuration for rendering experience entries.

    ``bullet_style`` is gone for the same reason it is no longer read from
    section config: experience bullets use the one shared bullet mechanism.
    """

    role_style: str = "Normal"
    max_bullets: int = -1  # -1 means no limit
