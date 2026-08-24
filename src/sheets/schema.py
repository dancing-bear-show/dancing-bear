"""Dataclasses for spreadsheet workbook definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HeaderStyle:
    """Styling configuration for the header row.

    Color fields accept a 6-character hex string with or without a leading
    ``#``. The generator normalises them to 8-character ARGB before passing
    them to openpyxl, so callers can use either form.
    """

    bg_color: str = "#2D3A4F"
    text_color: str = "#FFFFFF"
    bold: bool = True
    font_size: int = 11


@dataclass
class SheetTab:
    """Definition for a single worksheet/tab inside a workbook."""

    name: str
    headers: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    header_style: HeaderStyle | None = None
    alternating_rows: bool = True
    column_widths: list[int] | None = None
    freeze_rows: int = 1
    freeze_cols: int = 0


@dataclass
class SheetMetadata:
    """Metadata written to the workbook document properties."""

    title: str
    author: str | None = None
    date: str | None = None


@dataclass
class SheetWorkbook:
    """Complete workbook definition: metadata plus one or more sheet tabs."""

    metadata: SheetMetadata
    sheets: list[SheetTab] = field(default_factory=list)
