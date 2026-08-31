"""Richmond Hill venue-specific website schedule parsers."""
from __future__ import annotations

import re

from core.date_utils import normalize_day
from core.text_utils import html_to_text, parse_time_range

from .base import ScheduleParser
from .model import ScheduleItem
from .web_parser_base import (
    WEEKDAYS,
    LEISURE_SWIM,
    ScheduleItemParams,
    _make_schedule_item_from_params,
    _fetch_html,
)


class RichmondHillSkatingParser(ScheduleParser):
    """Parser for Richmond Hill skating schedules."""

    def parse(self, url: str) -> list[ScheduleItem]:
        """Parse Richmond Hill skating schedule."""
        html = _fetch_html(url)
        try:
            from bs4 import BeautifulSoup  # noqa: F401
            return self._parse_with_bs4(html, url)
        except ImportError:
            return self._parse_with_regex(html, url)

    def _parse_with_bs4(self, html: str, url: str) -> list[ScheduleItem]:
        """Parse using BeautifulSoup."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        out: list[ScheduleItem] = []

        for p in soup.select('[data-name="accParent"]'):
            arena = (p.get_text(strip=True) or '').strip()
            sib = p.find_next(attrs={'data-name': 'accChild'})
            if not sib:
                continue
            table = sib.find('table')
            if not table:
                continue

            row = self._find_public_skating_row(table)
            if not row:
                continue

            cells = row.find_all('td')
            if len(cells) < 2:
                continue

            days = self._extract_day_headers(table, row, len(cells) - 1)
            out.extend(self._parse_time_cells(cells[1:], days, arena, url))

        return out

    def _find_public_skating_row(self, table):
        """Find the table row containing 'Public Skating'."""
        for tr in table.find_all('tr'):
            first = tr.find('td')
            if first and 'public skating' in (first.get_text(strip=True) or '').lower():
                return tr
        return None

    def _extract_weekdays_from_cells(self, cells, weekday_set: set) -> list[str]:
        """Extract weekday names from table cells."""
        days: list[str] = []
        for td in cells:
            txt = (td.get_text(strip=True) or '').strip()
            if txt.lower() in weekday_set:
                days.append(txt)
        return days

    def _extract_day_headers(self, table, row, needed: int) -> list[str]:
        """Extract day headers from table, inferring if needed."""
        weekday_set = {d.lower() for d in WEEKDAYS}

        # Try to extract from all table cells
        days = self._extract_weekdays_from_cells(table.find_all('td'), weekday_set)

        # Fall back to previous row if insufficient
        if len(days) < 7:
            header_tr = row.find_previous('tr')
            if header_tr:
                days = self._extract_weekdays_from_cells(header_tr.find_all('td'), weekday_set)

        # Default to standard weekdays if still insufficient
        return days if len(days) >= needed else WEEKDAYS[:needed]

    def _parse_time_cells(self, cells, days: list[str], location: str, url: str) -> list[ScheduleItem]:
        """Parse time cells and create ScheduleItems."""
        items: list[ScheduleItem] = []
        for i, td in enumerate(cells):
            if i >= len(days):
                continue
            txt = (td.get_text(' ', strip=True) or '').strip()
            if not txt or txt == '\xa0':
                continue
            st, en = parse_time_range(txt)
            if st and en:
                items.append(_make_schedule_item_from_params(ScheduleItemParams(
                    'Public Skating', [normalize_day(days[i])], st, en, location, url,
                )))
        return items

    def _parse_with_regex(self, html: str, url: str) -> list[ScheduleItem]:
        """Parse using regex fallback."""
        items: list[ScheduleItem] = []

        for b in re.split(r'data-name="accParent"', html)[1:]:
            mname = re.search(r'>\s*([^<]+?)\s*</td>', b)
            arena = mname.group(1).strip() if mname else 'Arena'

            mpos = re.search(r'<td[^>]*>\s*<strong>\s*Public\s*Skating\s*</strong>\s*</td>', b, re.I | re.S)
            if not mpos:
                continue

            cells = re.findall(r'<td[^>]*>(.*?)</td>', b[mpos.end():], re.I | re.S)[:7]
            for i, cell in enumerate(cells):
                st, en = parse_time_range(html_to_text(cell))
                if st and en:
                    items.append(_make_schedule_item_from_params(ScheduleItemParams(
                        'Public Skating', [normalize_day(WEEKDAYS[i])], st, en, arena, url,
                    )))
        return items


class RichmondHillSwimmingParser(ScheduleParser):
    """Parser for Richmond Hill swimming schedules."""

    SWIM_LABELS = (LEISURE_SWIM, 'Fun N Fit', f'Fun N Fit & {LEISURE_SWIM}')

    def parse(self, url: str) -> list[ScheduleItem]:
        """Parse Richmond Hill swimming schedule."""
        html = _fetch_html(url)
        items: list[ScheduleItem] = []

        for b in re.split(r'data-name=\"accParent\"', html)[1:]:
            facility = self._extract_facility_name(b)
            items.extend(self._parse_swim_block(b, facility, url))

        return items

    def _extract_facility_name(self, block: str) -> str:
        """Extract facility name from HTML block."""
        m = re.search(r'>\s*([^<]+?)\s*</td>', block)
        return m.group(1).replace('&nbsp;', ' ').strip() if m else 'Pool'

    def _parse_swim_block(self, block: str, facility: str, url: str) -> list[ScheduleItem]:
        """Parse swim schedule from a single facility block."""
        items: list[ScheduleItem] = []

        for label in self.SWIM_LABELS:
            mpos = re.search(rf'<td[^>]*>\s*<strong>\s*{label}\s*</strong>\s*</td>', block, re.I | re.S)
            if not mpos:
                continue

            subject = LEISURE_SWIM if 'Leisure' in label and 'Fun' not in label else 'Fun N Fit'
            cells = re.findall(r'<td[^>]*>(.*?)</td>', block[mpos.end():], re.I | re.S)[:7]

            for i, cell in enumerate(cells):
                st, en = parse_time_range(html_to_text(cell))
                if st and en:
                    items.append(_make_schedule_item_from_params(ScheduleItemParams(
                        subject, [normalize_day(WEEKDAYS[i])], st, en, facility, url,
                    )))
        return items
