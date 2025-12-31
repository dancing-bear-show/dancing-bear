"""Workbook context and helpers for Excel Graph API operations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from mail.outlook_api import OutlookClient


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
