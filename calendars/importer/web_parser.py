"""Website schedule parsers."""
from __future__ import annotations

import datetime as _dt
import re
from typing import List

import requests

from core.constants import DEFAULT_REQUEST_TIMEOUT
from core.text_utils import html_to_text

from .base import ScheduleParser
from .constants import RE_TABLE_CELL, RE_TABLE_ROW
from .model import ScheduleItem
from .text_utils import normalize_day, normalize_days, parse_time_range, extract_time_ranges


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
        """Parse Richmond Hill skating schedule.

        Args:
            url: URL to Richmond Hill skating schedule

        Returns:
            List of ScheduleItem objects
        """
        html = requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT).text
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
        today = _dt.date.today().isoformat()

        parents = soup.select('[data-name="accParent"]')
        for p in parents:
            arena = (p.get_text(strip=True) or '').strip()
            sib = p.find_next(attrs={'data-name': 'accChild'})
            if not sib:
                continue
            table = sib.find('table')
            if not table:
                continue

            # Build day headers
            days: List[str] = []
            for td in table.find_all('td'):
                txt = (td.get_text(strip=True) or '').strip()
                if txt.lower() in ('sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'):
                    days.append(txt)

            # Find row with Public Skating
            row = None
            for tr in table.find_all('tr'):
                first = tr.find('td')
                if first and ('public skating' in (first.get_text(strip=True) or '').lower()):
                    row = tr
                    break
            if not row:
                continue

            cells = row.find_all('td')
            if len(cells) < 2:
                continue

            # Infer day headers if needed
            if len(days) < 7:
                header_tr = row.find_previous('tr')
                days = []
                if header_tr:
                    for td in header_tr.find_all('td'):
                        t = (td.get_text(strip=True) or '').strip()
                        if t.lower() in ('sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'):
                            days.append(t)
            if len(days) < len(cells) - 1:
                days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][:len(cells) - 1]

            for i, td in enumerate(cells[1:], start=0):
                day = days[i] if i < len(days) else None
                if not day:
                    continue
                txt = (td.get_text(" ", strip=True) or '').strip()
                if not txt or txt == '\xa0':
                    continue
                st, en = parse_time_range(txt)
                if not st or not en:
                    continue
                out.append(ScheduleItem(
                    subject="Public Skating",
                    recurrence='weekly',
                    byday=[normalize_day(day)],
                    start_time=st,
                    end_time=en,
                    range_start=today,
                    location=arena,
                    notes=f"Imported from {url}",
                ))
        return out

    def _parse_with_regex(self, html: str, url: str) -> List[ScheduleItem]:
        """Parse using regex fallback."""
        items: List[ScheduleItem] = []
        today = _dt.date.today().isoformat()
        day_list = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

        blocks = re.split(r'data-name="accParent"', html)
        for b in blocks[1:]:
            mname = re.search(r'>\s*([^<]+?)\s*</td>', b)
            arena = (mname.group(1).strip() if mname else 'Arena')
            mpos = re.search(r'<td[^>]*>\s*<strong>\s*Public\s*Skating\s*</strong>\s*</td>', b, re.I | re.S)
            if not mpos:
                continue
            tail = b[mpos.end():]
            cells = re.findall(r'<td[^>]*>(.*?)</td>', tail, re.I | re.S)[:7]
            for i, cell in enumerate(cells[:7]):
                cell_text = html_to_text(cell)
                st, en = parse_time_range(cell_text)
                if not st or not en:
                    continue
                items.append(ScheduleItem(
                    subject="Public Skating",
                    recurrence='weekly',
                    byday=[normalize_day(day_list[i])],
                    start_time=st,
                    end_time=en,
                    range_start=today,
                    location=arena,
                    notes=f"Imported from {url}",
                ))
        return items


class RichmondHillSwimmingParser(ScheduleParser):
    """Parser for Richmond Hill swimming schedules."""

    def parse(self, url: str) -> List[ScheduleItem]:
        """Parse Richmond Hill swimming schedule.

        Args:
            url: URL to Richmond Hill swimming schedule

        Returns:
            List of ScheduleItem objects
        """
        html = requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT).text
        items: List[ScheduleItem] = []
        today = _dt.date.today().isoformat()
        day_list = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

        blocks = re.split(r'data-name=\"accParent\"', html)
        for b in blocks[1:]:
            mname = re.search(r'>\s*([^<]+?)\s*</td>', b)
            facility = (re.sub(r'&nbsp;', ' ', mname.group(1)).strip() if mname else 'Pool')
            for label in ('Leisure Swim', 'Fun N Fit', 'Fun N Fit & Leisure Swim'):
                mpos = re.search(rf'<td[^>]*>\s*<strong>\s*{label}\s*</strong>\s*</td>', b, re.I | re.S)
                if not mpos:
                    continue
                tail = b[mpos.end():]
                cells = re.findall(r'<td[^>]*>(.*?)</td>', tail, re.I | re.S)[:7]
                for i, cell in enumerate(cells):
                    cell_text = html_to_text(cell)
                    st, en = parse_time_range(cell_text)
                    if not st or not en:
                        continue
                    subj = 'Leisure Swim' if 'Leisure' in label and 'Fun' not in label else 'Fun N Fit'
                    items.append(ScheduleItem(
                        subject=subj,
                        recurrence='weekly',
                        byday=[normalize_day(day_list[i])],
                        start_time=st,
                        end_time=en,
                        range_start=today,
                        location=facility,
                        notes=f"Imported from {url}",
                    ))
        return items


class AuroraAquaticsParser(ScheduleParser):
    """Parser for Aurora Aquatics schedules."""

    def parse(self, url: str) -> List[ScheduleItem]:
        """Parse Aurora Aquatics schedule.

        Args:
            url: URL to Aurora Aquatics schedule

        Returns:
            List of ScheduleItem objects
        """
        html = requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT).text
        items: List[ScheduleItem] = []
        today = _dt.date.today().isoformat()

        tables = re.findall(r'<table[\s\S]*?</table>', html, re.I)
        for tbl in tables:
            if not re.search(r'Leisure\s*Swim', tbl, re.I):
                continue

            # Extract headers
            header = re.search(r'<thead[\s\S]*?<tr[\s\S]*?>([\s\S]*?)</tr>[\s\S]*?</thead>', tbl, re.I)
            headers = []
            if header:
                headers = [html_to_text(h) for h in re.findall(RE_TABLE_CELL, header.group(1), re.I)]
            if not headers:
                first_row = re.search(RE_TABLE_ROW, tbl, re.I)
                if first_row:
                    headers = [html_to_text(h) for h in re.findall(RE_TABLE_CELL, first_row.group(1), re.I)]

            # Find Day and Leisure column indices
            day_idx = leisure_idx = None
            for i, h in enumerate(headers):
                hl = h.lower()
                if day_idx is None and 'day' in hl:
                    day_idx = i
                if leisure_idx is None and 'leisure' in hl:
                    leisure_idx = i
            if day_idx is None or leisure_idx is None:
                continue

            # Parse body rows
            body = re.search(r'<tbody[\s\S]*?>([\s\S]*?)</tbody>', tbl, re.I)
            rows = re.findall(RE_TABLE_ROW, body.group(1), re.I) if body else re.findall(RE_TABLE_ROW, tbl, re.I)
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
                        items.append(ScheduleItem(
                            subject='Leisure Swim',
                            recurrence='weekly',
                            byday=[code],
                            start_time=st,
                            end_time=en,
                            range_start=today,
                            location='Aurora Pools',
                            notes=f'Imported from {url}',
                        ))
        return items


# Backward compatibility function
def parse_website(url: str) -> List[ScheduleItem]:
    """Parse schedule from supported websites.

    Args:
        url: URL to parse

    Returns:
        List of ScheduleItem objects
    """
    return WebParser().parse(url)
