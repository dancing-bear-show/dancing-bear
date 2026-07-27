"""Workbook context and helpers for Excel Graph API operations."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Dict, List

from core.http import HttpClient
from mail.outlook_api import OutlookClient


def col_letter(idx: int) -> str:
    """Convert 1-based column index to Excel column letters (e.g. 1->'A', 27->'AA')."""
    s = ""
    n = idx
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def read_csv_rows(path: str) -> List[List[str]]:
    """Read a CSV file and return rows as lists of strings."""
    rows: List[List[str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            rows.append(list(row))
    return rows


def pad_rows(values: List[List[str]], cols: int) -> List[List[str]]:
    """Pad ragged rows to a rectangular shape for the Graph API."""
    return [r + [""] * (cols - len(r)) if len(r) < cols else r for r in values]


def write_range_to_sheet(wb: "WorkbookContext", sheet: str, values: List[List[str]]) -> None:
    """Write values to a worksheet with table styling, autofit, and frozen header.

    Clears A1:Z100000, writes the range, applies TableStyleMedium2, autofits
    columns, and freezes the first row.  Table creation and formatting are
    best-effort (errors silently ignored).
    """
    import json as _json
    from core.constants import DEFAULT_REQUEST_TIMEOUT

    _client = HttpClient("", default_headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT)
    sheet_url = wb.sheet_url(sheet)
    try:
        _client.post(
            f"{sheet_url}/range(address='A1:Z100000')/clear",
            data=_json.dumps({"applyTo": "contents"}),
        )
    except Exception:  # nosec B110 - clear is best-effort
        pass
    if not values:
        return

    rows = len(values)
    cols = max((len(r) for r in values), default=0)
    if cols <= 0:
        return
    padded = pad_rows(values, cols)
    end_col = col_letter(cols)
    addr = f"A1:{end_col}{rows}"

    try:
        _client.patch(
            f"{sheet_url}/range(address='{addr}')",
            data=_json.dumps({"values": padded}),
        )
    except Exception as e:
        raise RuntimeError(f"Failed writing sheet {sheet}: {e}") from e

    # Add table (best-effort): POST to workbook-level tables/add with sheet-qualified
    # address (e.g. "Sheet1!A1:D5") as required by the Graph API /workbook/tables/add endpoint.
    try:
        tadd = _client.post(
            f"{wb.base_url}/tables/add",
            data=_json.dumps({"address": f"'{sheet.replace(chr(39), chr(39)*2)}'!{addr}", "hasHeaders": True}),
        )
        if tid := (tadd.json() or {}).get("id"):
            _client.patch(
                f"{wb.base_url}/tables/{tid}",
                data=_json.dumps({"style": "TableStyleMedium2"}),
            )
    except Exception:
        pass  # nosec B110 - table styling is optional

    # Autofit columns and freeze header row
    try:
        _client.post(
            f"{sheet_url}/range(address='A:{end_col}')/format/autofitColumns",
        )
        _client.post(
            f"{sheet_url}/freezePanes/freeze",
            data=_json.dumps({"top": 1, "left": 0}),
        )
    except Exception:  # nosec B110 - formatting is best-effort
        pass


@dataclass
class WorkbookContext:
    """Context for Excel workbook operations via Graph API.

    Bundles the client and workbook identifiers to reduce parameter passing.
    """

    client: OutlookClient
    drive_id: str
    item_id: str

    @property
    def base_url(self) -> str:
        """Return base URL for workbook Graph API operations."""
        return f"{self.client.GRAPH}/drives/{self.drive_id}/items/{self.item_id}/workbook"

    def headers(self) -> Dict[str, str]:
        """Return auth headers for API calls."""
        return self.client._headers()

    def sheet_url(self, sheet: str) -> str:
        """Return URL for a specific worksheet."""
        safe = sheet.replace("'", "''")
        return f"{self.base_url}/worksheets('{safe}')"

    def chart_url(self, sheet: str, chart_id: str) -> str:
        """Return URL for a specific chart."""
        return f"{self.sheet_url(sheet)}/charts('{chart_id}')"


@dataclass
class ChartPlacement:
    """Chart position and size parameters."""

    left: int = 400
    top: int = 10
    width: int = 600
    height: int = 360


@dataclass
class SheetContext:
    """Context for operations on a specific worksheet."""

    wb: WorkbookContext
    sheet: str

    @property
    def url(self) -> str:
        """Return URL for this worksheet."""
        return self.wb.sheet_url(self.sheet)

    def chart_url(self, chart_id: str) -> str:
        """Return URL for a chart in this sheet."""
        return self.wb.chart_url(self.sheet, chart_id)
