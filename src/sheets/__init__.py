"""Styled spreadsheet generation from YAML workbook definitions."""

from sheets.constants import (
    DEFAULT_HEADER_BG_COLOR,
    DEFAULT_WORKBOOK_TITLE,
    MIN_COLUMN_WIDTH,
    MAX_COLUMN_WIDTH,
)
from sheets.generator import (
    SheetGenerator,
    generate_from_yaml,
    generate_xlsx,
    load_workbook_from_yaml,
)
from sheets.schema import (
    HeaderStyle,
    SheetMetadata,
    SheetTab,
    SheetWorkbook,
)

__all__ = [
    # Constants
    "DEFAULT_HEADER_BG_COLOR",
    "DEFAULT_WORKBOOK_TITLE",
    "MAX_COLUMN_WIDTH",
    "MIN_COLUMN_WIDTH",
    # Schema dataclasses
    "HeaderStyle",
    "SheetMetadata",
    "SheetTab",
    "SheetWorkbook",
    # Generator class and functions
    "SheetGenerator",
    "generate_from_yaml",
    "generate_xlsx",
    "load_workbook_from_yaml",
]
