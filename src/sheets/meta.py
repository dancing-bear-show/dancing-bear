"""App metadata for the sheets CLI."""

from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="sheets",
    purpose="Generate styled .xlsx spreadsheets from YAML workbook definitions",
    display_name="Sheets",
    example_cmd="./bin/sheets generate workbook.yaml -o output.xlsx",
)
