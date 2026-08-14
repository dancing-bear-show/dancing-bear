"""Aurora Aquatics venue-specific website schedule parser."""
from __future__ import annotations

import re

from core.date_utils import normalize_days
from core.patterns import RE_TABLE_CELL, RE_TABLE_ROW
from core.text_utils import extract_time_ranges, html_to_text

from .base import ScheduleParser
from .model import ScheduleItem
from .web_parser_base import (
    LEISURE_SWIM,
    ScheduleItemParams,
    _make_schedule_item_from_params,
    _fetch_html,
)


class AuroraAquaticsParser(ScheduleParser):
    """Parser for Aurora Aquatics schedules."""

    def parse(self, url: str) -> list[ScheduleItem]:
        """Parse Aurora Aquatics schedule."""
        html = _fetch_html(url)
        items: list[ScheduleItem] = []

        for tbl in re.findall(r'<table[\s\S]*?</table>', html, re.I):
            if not re.search(r'Leisure\s*Swim', tbl, re.I):
                continue

            headers = self._extract_headers(tbl)
            day_idx, leisure_idx = self._find_column_indices(headers)
            if day_idx is None or leisure_idx is None:
                continue

            items.extend(self._parse_table_rows(tbl, day_idx, leisure_idx, url))

        return items

    def _extract_headers(self, table: str) -> list[str]:
        """Extract column headers from table."""
        header = re.search(r'<thead[\s\S]*?<tr[\s\S]*?>([\s\S]*?)</tr>[\s\S]*?</thead>', table, re.I)
        if header:
            return [html_to_text(h) for h in re.findall(RE_TABLE_CELL, header.group(1), re.I)]

        first_row = re.search(RE_TABLE_ROW, table, re.I)
        if first_row:
            return [html_to_text(h) for h in re.findall(RE_TABLE_CELL, first_row.group(1), re.I)]

        return []

    def _find_column_indices(self, headers: list[str]) -> tuple[int | None, int | None]:
        """Find indices for Day and Leisure columns."""
        day_idx = leisure_idx = None
        for i, h in enumerate(headers):
            hl = h.lower()
            if day_idx is None and 'day' in hl:
                day_idx = i
            if leisure_idx is None and 'leisure' in hl:
                leisure_idx = i
        return day_idx, leisure_idx

    def _parse_table_rows(self, table: str, day_idx: int, leisure_idx: int, url: str) -> list[ScheduleItem]:
        """Parse table rows and create ScheduleItems."""
        items: list[ScheduleItem] = []
        body = re.search(r'<tbody[\s\S]*?>([\s\S]*?)</tbody>', table, re.I)
        rows = re.findall(RE_TABLE_ROW, body.group(1), re.I) if body else re.findall(RE_TABLE_ROW, table, re.I)

        for row in rows:
            cols = re.findall(RE_TABLE_CELL, row, re.I)
            if len(cols) <= max(day_idx, leisure_idx):
                continue

            day_spec = html_to_text(cols[day_idx])
            leisure_cell = cols[leisure_idx]
            if not html_to_text(leisure_cell):
                continue

            for code in normalize_days(day_spec):
                for st, en in extract_time_ranges(leisure_cell):
                    items.append(_make_schedule_item_from_params(ScheduleItemParams(LEISURE_SWIM, [code], st, en, 'Aurora Pools', url)))

        return items
