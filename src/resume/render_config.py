"""Configuration dataclasses for resume rendering.

Reduces parameter count by grouping related rendering options.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class BulletConfig:
    """Configuration for bullet rendering."""

    glyph: str = "•"
    list_style: str = "List Bullet"
    plain: bool = True
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
    meta_pt: Optional[float] = None
    color: Optional[str] = None
    italic: bool = False


@dataclass
class RenderContext:
    """Common rendering context shared across functions."""

    sec: Optional[Dict[str, Any]] = None  # Section config
    keywords: Optional[List[str]] = None  # Keywords to highlight/bold


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

    max_roles: Optional[int] = None
    max_bullets_per_role: Optional[int] = None
    min_score: int = 1


@dataclass
class ExperienceRenderConfig:
    """Configuration for rendering experience entries."""

    role_style: str = "Normal"
    bullet_style: str = "List Bullet"
    max_bullets: int = -1  # -1 means no limit
