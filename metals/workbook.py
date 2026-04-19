"""Workbook context and helpers for Excel Graph API operations."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Dict, List

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
    import requests  # type: ignore
    from core.constants import DEFAULT_REQUEST_TIMEOUT

    sheet_url = wb.sheet_url(sheet)
    requests.post(
        f"{sheet_url}/range(address='A1:Z100000')/clear",
        headers=wb.headers(),
        data=_json.dumps({"applyTo": "contents"}),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )
    if not values:
        return

    rows, cols = len(values), max(len(r) for r in values)
    padded = pad_rows(values, cols)
    end_col = col_letter(cols)
    addr = f"A1:{end_col}{rows}"

    r = requests.patch(
        f"{sheet_url}/range(address='{addr}')",
        headers=wb.headers(),
        data=_json.dumps({"values": padded}),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Failed writing sheet {sheet}: {r.status_code} {r.text}")

    # Add table (best-effort)
    tadd = requests.post(
        f"{wb.base_url}/tables/add",
        headers=wb.headers(),
        data=_json.dumps({"address": f"{sheet}!{addr}", "hasHeaders": True}),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )
    try:
        if tid := (tadd.json() or {}).get("id"):
            requests.patch(
                f"{wb.base_url}/tables/{tid}",
                headers=wb.headers(),
                data=_json.dumps({"style": "TableStyleMedium2"}),
                timeout=DEFAULT_REQUEST_TIMEOUT,
            )
    except Exception:
        pass  # nosec B110 - table styling is optional

    # Autofit columns and freeze header row
    requests.post(
        f"{sheet_url}/range(address='{sheet}!A:{end_col}')/format/autofitColumns",
        headers=wb.headers(),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )
    requests.post(
        f"{sheet_url}/freezePanes/freeze",
        headers=wb.headers(),
        data=_json.dumps({"top": 1, "left": 0}),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )


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
        return f"{self.base_url}/worksheets('{sheet}')"

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
