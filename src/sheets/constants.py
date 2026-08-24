"""Constants for spreadsheet generation.

Centralises all magic strings, numeric values, and configuration defaults
used in the sheets module. All values are plain Python scalars, so this
module stays importable without openpyxl installed.
"""

from __future__ import annotations

# =============================================================================
# Default Colors (6-character RGB hex, no leading #)
# =============================================================================

# Header row background — dark blue-gray
DEFAULT_HEADER_BG_COLOR = "2D3A4F"
DEFAULT_HEADER_TEXT_COLOR = "FFFFFF"

# Alternating row (zebra) fill colors
ALTERNATING_ROW_COLOR_1 = "F5F5F5"  # Light gray for even rows
ALTERNATING_ROW_COLOR_2 = "FFFFFF"  # White for odd rows

# Thin cell border color
DEFAULT_BORDER_COLOR = "CCCCCC"


# =============================================================================
# Font Configuration
# =============================================================================

DEFAULT_FONT_NAME = "Calibri"
DEFAULT_FONT_SIZE = 11
DEFAULT_HEADER_FONT_SIZE = 11
DEFAULT_HEADER_BOLD = True


# =============================================================================
# Column and Row Dimensions (characters / points)
# =============================================================================

DEFAULT_COLUMN_WIDTH = 12  # characters
MIN_COLUMN_WIDTH = 8       # auto-fit lower bound
MAX_COLUMN_WIDTH = 50      # auto-fit upper bound

DEFAULT_ROW_HEIGHT = 15    # points


# =============================================================================
# Freeze Panes
# =============================================================================

DEFAULT_FREEZE_ROWS = 1   # Freeze the header row by default
DEFAULT_FREEZE_COLS = 0   # No column freeze by default


# =============================================================================
# YAML Field Names
# =============================================================================

YAML_TITLE = "title"
YAML_AUTHOR = "author"
YAML_DATE = "date"
YAML_SHEETS = "sheets"
YAML_SHEET_NAME = "name"
YAML_HEADERS = "headers"
YAML_ROWS = "rows"
YAML_HEADER_STYLE = "header_style"
YAML_BG_COLOR = "bg_color"
YAML_TEXT_COLOR = "text_color"
YAML_BOLD = "bold"
YAML_FONT_SIZE = "font_size"
YAML_ALTERNATING_ROWS = "alternating_rows"
YAML_COLUMN_WIDTHS = "column_widths"
YAML_FREEZE_ROWS = "freeze_rows"
YAML_FREEZE_COLS = "freeze_cols"


# =============================================================================
# Default Values
# =============================================================================

DEFAULT_WORKBOOK_TITLE = "Untitled"
DEFAULT_SHEET_NAME = "Sheet1"
DEFAULT_ALTERNATING_ROWS = True
