"""Constants for slide deck generation.

Centralizes all magic strings, numeric values, and configuration defaults
used in the slides module. pptx-derived values (RGBColor, MSO_THEME_COLOR,
MSO_ANCHOR) are built lazily via accessor functions so this module — and
everything that imports only its plain constants — stays importable without
python-pptx installed.
"""

from __future__ import annotations

from typing import Any

# =============================================================================
# Bullet Characters
# =============================================================================

BULLET_LEVEL_0 = "•"  # Top-level bullet
BULLET_LEVEL_1 = "◦"  # Sub-bullet
BULLET_LEVEL_2 = "▪"  # Sub-sub-bullet

BULLET_CHARS = [BULLET_LEVEL_0, BULLET_LEVEL_1, BULLET_LEVEL_2]

# Characters that indicate text already has a bullet
EXISTING_BULLET_CHARS = ("•", "◦", "▪", "‣", "-", "*")


# =============================================================================
# Font Sizes (in points)
# =============================================================================

FONT_SIZE_HEADER = 22
FONT_SIZE_BULLET_LEVEL_0 = 20
FONT_SIZE_BULLET_LEVEL_1 = 18
FONT_SIZE_BULLET_LEVEL_2 = 16

FONT_SIZES_BY_LEVEL = [
    FONT_SIZE_BULLET_LEVEL_0,
    FONT_SIZE_BULLET_LEVEL_1,
    FONT_SIZE_BULLET_LEVEL_2,
]

# Table font sizes
FONT_SIZE_TABLE_HEADER = 11
FONT_SIZE_TABLE_CELL = 10


# =============================================================================
# Paragraph Spacing (in points)
# =============================================================================

SPACING_BEFORE_HEADER = 14
SPACING_AFTER_HEADER = 6
SPACING_BEFORE_BULLET = 4
SPACING_AFTER_BULLET = 14


# =============================================================================
# Content Positioning (in inches)
# =============================================================================

SLIDE_WIDTH = 13.33  # Standard widescreen slide width in inches
SLIDE_HEIGHT = 7.5  # Standard widescreen slide height in inches
CONTENT_WIDTH = 10.5  # Text box width
CONTENT_LEFT = (SLIDE_WIDTH - CONTENT_WIDTH) / 2  # Centered horizontally
CONTENT_TOP = 2.7  # Inches from top (below title, below branding graphic)
CONTENT_BOTTOM_MARGIN = 0.4  # Inches from slide bottom
IMAGE_CONTENT_TOP = 1.3  # Top of content area for image/mermaid slides (below title in layout_map mode)

# Table positioning
TABLE_WIDTH = 8.5
TABLE_LEFT = 0.75  # Left-aligned with margin
TABLE_TOP = 3.2  # Below title (title ends ~3.08")
TABLE_ROW_HEIGHT = 0.28  # Inches per row


# =============================================================================
# Table Colors (RGB) — built lazily, pptx.dml.color.RGBColor requires pptx
# =============================================================================


def table_header_bg() -> Any:
    """Dark blue-gray RGBColor for the table header row."""
    from pptx.dml.color import RGBColor

    return RGBColor(0x2D, 0x3A, 0x4F)


def table_row_even_bg() -> Any:
    """Lighter RGBColor for even data rows."""
    from pptx.dml.color import RGBColor

    return RGBColor(0x1E, 0x28, 0x3C)


def table_row_odd_bg() -> Any:
    """Darker RGBColor for odd data rows."""
    from pptx.dml.color import RGBColor

    return RGBColor(0x16, 0x1E, 0x2E)


def severity_colors() -> dict[str, Any]:
    """Map severity badge text to its RGBColor (text color for severity cells)."""
    from pptx.dml.color import RGBColor

    return {
        "P0": RGBColor(0xFF, 0x4D, 0x4D),  # Red
        "P1": RGBColor(0xFF, 0xA5, 0x00),  # Orange
        "P2": RGBColor(0xFF, 0xD7, 0x00),  # Yellow
        "P3": RGBColor(0x90, 0xEE, 0x90),  # Light green
    }


# =============================================================================
# Theme Color Mapping — built lazily, pptx.enum.dml.MSO_THEME_COLOR requires pptx
# =============================================================================


def theme_color_map() -> dict[str, Any]:
    """Map theme color name strings to MSO_THEME_COLOR enum members."""
    from pptx.enum.dml import MSO_THEME_COLOR

    return {
        "LIGHT_1": MSO_THEME_COLOR.LIGHT_1,
        "LIGHT_2": MSO_THEME_COLOR.LIGHT_2,
        "DARK_1": MSO_THEME_COLOR.DARK_1,
        "DARK_2": MSO_THEME_COLOR.DARK_2,
        "ACCENT_1": MSO_THEME_COLOR.ACCENT_1,
        "ACCENT_2": MSO_THEME_COLOR.ACCENT_2,
        "ACCENT_3": MSO_THEME_COLOR.ACCENT_3,
        "ACCENT_4": MSO_THEME_COLOR.ACCENT_4,
        "ACCENT_5": MSO_THEME_COLOR.ACCENT_5,
        "ACCENT_6": MSO_THEME_COLOR.ACCENT_6,
    }


# Default theme color for text
DEFAULT_THEME_COLOR = "LIGHT_2"


def highlight_theme_color() -> Any:
    """Highlight color for emphasized text (ACCENT_4 = bright cyan, readable on dark bg)."""
    from pptx.enum.dml import MSO_THEME_COLOR

    return MSO_THEME_COLOR.ACCENT_4


# =============================================================================
# Layout Types
# =============================================================================

LAYOUT_BULLET = "bullet"
LAYOUT_TABLE = "table"
LAYOUT_TITLE_ONLY = "title_only"
LAYOUT_SECTION = "section"
LAYOUT_BREAKER = "breaker"

VALID_LAYOUTS = [LAYOUT_BULLET, LAYOUT_TABLE, LAYOUT_TITLE_ONLY, LAYOUT_SECTION, LAYOUT_BREAKER]


# =============================================================================
# YAML Field Names
# =============================================================================

YAML_TITLE = "title"
YAML_AUTHOR = "author"
YAML_DATE = "date"
YAML_TEMPLATE_SLIDE_INDEX = "template_slide_index"
YAML_THEME_COLOR = "theme_color"
YAML_SLIDES = "slides"
YAML_TEMPLATE_PATH = "template_path"
YAML_BULLETS = "bullets"
YAML_LAYOUT = "layout"
YAML_NOTES = "notes"
YAML_HEADERS = "headers"
YAML_ROWS = "rows"
YAML_FIRST_COL_WIDTH = "first_col_width"
YAML_SUBTITLE = "subtitle"
YAML_TEXT = "text"
YAML_LEVEL = "level"
YAML_HIGHLIGHT = "highlight"
YAML_BOLD = "bold"
YAML_URL = "url"
YAML_BODY = "body"
YAML_LAYOUT_MAP = "layout_map"
YAML_IMAGE = "image"
YAML_MERMAID = "mermaid"


# =============================================================================
# Default Values
# =============================================================================

DEFAULT_TITLE = "Untitled"
DEFAULT_TEMPLATE_SLIDE_INDEX = 0  # 0-indexed fallback; master layouts are preferred at generate time
DEFAULT_BULLET_LEVEL = 0
DEFAULT_SECTION_HEADER_MAX_LENGTH = 40
DEFAULT_LAYOUT_KEY = LAYOUT_BULLET
RESERVED_LAYOUT_KEY = "__fallback__"

# Common layout_map indices for branded templates
DEFAULT_SECTION_LAYOUT = 0  # Section/breaker slide (typically first layout)
DEFAULT_CONTENT_LAYOUT = 1  # Content/bullet slide (typically second layout)


def link_blue() -> Any:
    """Google-style link blue RGBColor for hyperlinks."""
    from pptx.dml.color import RGBColor

    return RGBColor(0x1A, 0x73, 0xE8)


# =============================================================================
# Vertical Anchor
# =============================================================================


def vertical_anchor_middle() -> Any:
    """MSO_ANCHOR.MIDDLE for vertically centering table cell text."""
    from pptx.enum.text import MSO_ANCHOR

    return MSO_ANCHOR.MIDDLE


# =============================================================================
# Error Messages
# =============================================================================

ERR_NO_TEMPLATE_PATH = "No template path provided"


# =============================================================================
# Lazy constant access (PEP 562)
# =============================================================================

# The pptx-derived values above are exposed as functions so that importing this
# module never imports pptx. Callers that want the historical constant spelling
# (TABLE_HEADER_BG, THEME_COLOR_MAP, ...) get it through this hook, which
# resolves the name to its accessor and calls it on first attribute access.
# Keeping both spellings matters: the constant names are the module's public
# API, and dropping them would silently break every importer.
_LAZY_CONSTANTS = {
    "TABLE_HEADER_BG": table_header_bg,
    "TABLE_ROW_EVEN_BG": table_row_even_bg,
    "TABLE_ROW_ODD_BG": table_row_odd_bg,
    "SEVERITY_COLORS": severity_colors,
    "THEME_COLOR_MAP": theme_color_map,
    "HIGHLIGHT_THEME_COLOR": highlight_theme_color,
    "LINK_BLUE": link_blue,
    "VERTICAL_ANCHOR_MIDDLE": vertical_anchor_middle,
}


def __getattr__(name: str) -> Any:
    """Resolve pptx-derived constants lazily on first access (PEP 562)."""
    accessor = _LAZY_CONSTANTS.get(name)
    if accessor is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return accessor()


def __dir__() -> list[str]:
    """Include lazily-resolved constant names in dir() and tab completion."""
    return sorted([*globals(), *_LAZY_CONSTANTS])
