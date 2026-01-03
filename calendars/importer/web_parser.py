"""Website schedule parsers."""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import List, Optional

import requests

from core.constants import DEFAULT_REQUEST_TIMEOUT
from core.text_utils import html_to_text

from .base import ScheduleParser
from .constants import RE_TABLE_CELL, RE_TABLE_ROW
from .model import ScheduleItem
from .text_utils import normalize_day, normalize_days, parse_time_range, extract_time_ranges

# Standard day ordering for table parsing
WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

# Common swim activity names
LEISURE_SWIM = 'Leisure Swim'


@dataclass
class ScheduleItemParams:
    """Parameters for creating a schedule item."""

    subject: str
    byday: List[str]
    start_time: str
    end_time: str
    location: str
    url: str


def _make_schedule_item_from_params(params: ScheduleItemParams) -> ScheduleItem:
    """Create a weekly recurring ScheduleItem from params."""
    return ScheduleItem(
        subject=params.subject,
        recurrence='weekly',
        byday=params.byday,
        start_time=params.start_time,
        end_time=params.end_time,
        range_start=_dt.date.today().isoformat(),
        location=params.location,
        notes=f'Imported from {params.url}',
    )


def _make_schedule_item(
    subject: str,
    byday: List[str],
    start_time: str,
    end_time: str,
    location: str,
    url: str,
) -> ScheduleItem:
    """Create a weekly recurring ScheduleItem (legacy signature)."""
    params = ScheduleItemParams(
        subject=subject,
        byday=byday,
        start_time=start_time,
        end_time=end_time,
        location=location,
        url=url,
    )
    return _make_schedule_item_from_params(params)


def _fetch_html(url: str) -> str:
    """Fetch HTML content from URL."""
    return requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT).text


class WebParser(ScheduleParser):
    """Parser for website-based schedules.

    Supports:
    - Richmond Hill skating schedules
    - Richmond Hill swimming schedules
    - Aurora Aquatics schedules
    """

    def parse(self, url: str) -> List[ScheduleItem]:
        """Parse schedule items from supported website.

        Args:
            url: URL to parse

        Returns:
            List of ScheduleItem objects

        Raises:
            NotImplementedError: If website is not supported
        """
        u = str(url or '')

        # Richmond Hill Skating
        if 'richmondhill.ca' in u and 'Skating.aspx' in u:
            return RichmondHillSkatingParser().parse(u)

        # Richmond Hill Swimming
        if 'richmondhill.ca' in u and 'Swimming.aspx' in u:
            return RichmondHillSwimmingParser().parse(u)

        # Aurora Aquatics
        if 'aurora.ca' in u and 'aquatics-and-swim-programs' in u:
            return AuroraAquaticsParser().parse(u)

        raise NotImplementedError("Website parsing not implemented for this source. Provide CSV/XLSX or known site.")


class RichmondHillSkatingParser(ScheduleParser):
    """Parser for Richmond Hill skating schedules."""

    def parse(self, url: str) -> List[ScheduleItem]:
        """Parse Richmond Hill skating schedule."""
        html = _fetch_html(url)
        try:
            from bs4 import BeautifulSoup  # type: ignore  # noqa: F401
            return self._parse_with_bs4(html, url)
        except ImportError:
            return self._parse_with_regex(html, url)

    def _parse_with_bs4(self, html: str, url: str) -> List[ScheduleItem]:
        """Parse using BeautifulSoup."""
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, 'html.parser')
        out: List[ScheduleItem] = []

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

    def _extract_weekdays_from_cells(self, cells, weekday_set: set) -> List[str]:
        """Extract weekday names from table cells."""
        days: List[str] = []
        for td in cells:
            txt = (td.get_text(strip=True) or '').strip()
            if txt.lower() in weekday_set:
                days.append(txt)
        return days

    def _extract_day_headers(self, table, row, needed: int) -> List[str]:
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

    def _parse_time_cells(self, cells, days: List[str], location: str, url: str) -> List[ScheduleItem]:
        """Parse time cells and create ScheduleItems."""
        items: List[ScheduleItem] = []
        for i, td in enumerate(cells):
            if i >= len(days):
                continue
            txt = (td.get_text(' ', strip=True) or '').strip()
            if not txt or txt == '\xa0':
                continue
            st, en = parse_time_range(txt)
            if st and en:
                items.append(_make_schedule_item(
                    'Public Skating', [normalize_day(days[i])], st, en, location, url,
                ))
        return items

    def _parse_with_regex(self, html: str, url: str) -> List[ScheduleItem]:
        """Parse using regex fallback."""
        items: List[ScheduleItem] = []

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
                    items.append(_make_schedule_item(
                        'Public Skating', [normalize_day(WEEKDAYS[i])], st, en, arena, url,
                    ))
        return items


class RichmondHillSwimmingParser(ScheduleParser):
    """Parser for Richmond Hill swimming schedules."""

    SWIM_LABELS = (LEISURE_SWIM, 'Fun N Fit', f'Fun N Fit & {LEISURE_SWIM}')

    def parse(self, url: str) -> List[ScheduleItem]:
        """Parse Richmond Hill swimming schedule."""
        html = _fetch_html(url)
        items: List[ScheduleItem] = []

        for b in re.split(r'data-name=\"accParent\"', html)[1:]:
            facility = self._extract_facility_name(b)
            items.extend(self._parse_swim_block(b, facility, url))

        return items

    def _extract_facility_name(self, block: str) -> str:
        """Extract facility name from HTML block."""
        m = re.search(r'>\s*([^<]+?)\s*</td>', block)
        return m.group(1).replace('&nbsp;', ' ').strip() if m else 'Pool'

    def _parse_swim_block(self, block: str, facility: str, url: str) -> List[ScheduleItem]:
        """Parse swim schedule from a single facility block."""
        items: List[ScheduleItem] = []

        for label in self.SWIM_LABELS:
            mpos = re.search(rf'<td[^>]*>\s*<strong>\s*{label}\s*</strong>\s*</td>', block, re.I | re.S)
            if not mpos:
                continue

            subject = LEISURE_SWIM if 'Leisure' in label and 'Fun' not in label else 'Fun N Fit'
            cells = re.findall(r'<td[^>]*>(.*?)</td>', block[mpos.end():], re.I | re.S)[:7]

            for i, cell in enumerate(cells):
                st, en = parse_time_range(html_to_text(cell))
                if st and en:
                    items.append(_make_schedule_item(
                        subject, [normalize_day(WEEKDAYS[i])], st, en, facility, url,
                    ))
        return items


class AuroraAquaticsParser(ScheduleParser):
    """Parser for Aurora Aquatics schedules."""

    def parse(self, url: str) -> List[ScheduleItem]:
        """Parse Aurora Aquatics schedule."""
        html = _fetch_html(url)
        items: List[ScheduleItem] = []

        for tbl in re.findall(r'<table[\s\S]*?</table>', html, re.I):
            if not re.search(r'Leisure\s*Swim', tbl, re.I):
                continue

            headers = self._extract_headers(tbl)
            day_idx, leisure_idx = self._find_column_indices(headers)
            if day_idx is None or leisure_idx is None:
                continue

            items.extend(self._parse_table_rows(tbl, day_idx, leisure_idx, url))

        return items

    def _extract_headers(self, table: str) -> List[str]:
        """Extract column headers from table."""
        header = re.search(r'<thead[\s\S]*?<tr[\s\S]*?>([\s\S]*?)</tr>[\s\S]*?</thead>', table, re.I)
        if header:
            return [html_to_text(h) for h in re.findall(RE_TABLE_CELL, header.group(1), re.I)]

        first_row = re.search(RE_TABLE_ROW, table, re.I)
        if first_row:
            return [html_to_text(h) for h in re.findall(RE_TABLE_CELL, first_row.group(1), re.I)]

        return []

    def _find_column_indices(self, headers: List[str]) -> tuple[Optional[int], Optional[int]]:
        """Find indices for Day and Leisure columns."""
        day_idx = leisure_idx = None
        for i, h in enumerate(headers):
            hl = h.lower()
            if day_idx is None and 'day' in hl:
                day_idx = i
            if leisure_idx is None and 'leisure' in hl:
                leisure_idx = i
        return day_idx, leisure_idx

    def _parse_table_rows(self, table: str, day_idx: int, leisure_idx: int, url: str) -> List[ScheduleItem]:
        """Parse table rows and create ScheduleItems."""
        items: List[ScheduleItem] = []
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
                    items.append(_make_schedule_item(LEISURE_SWIM, [code], st, en, 'Aurora Pools', url))

        return items


def parse_website(url: str) -> List[ScheduleItem]:
    """Parse schedule from supported websites (backward compatibility)."""
    return WebParser().parse(url)
