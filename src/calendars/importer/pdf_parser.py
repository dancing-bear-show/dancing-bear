"""PDF schedule parser."""
from __future__ import annotations

import datetime as _dt
import logging
import re
from typing import Any

from core.date_utils import normalize_days
from core.text_utils import extract_time_ranges

from .base import ScheduleParser
from .model import ScheduleItem

logger = logging.getLogger(__name__)


class PDFParser(ScheduleParser):
    """Parser for PDF schedule files.

    Supports Aurora Aquatics drop-in schedules with both pdfplumber (table extraction)
    and pdfminer.six (text extraction) fallback.
    """

    def parse(self, path: str) -> list[ScheduleItem]:
        """Parse schedule items from PDF file.

        Args:
            path: Path to PDF file

        Returns:
            List of ScheduleItem objects

        Raises:
            RuntimeError: If pdfminer.six is not installed or parsing fails
            NotImplementedError: If PDF format is not supported
        """
        try:
            from pdfminer.high_level import extract_text  # type: ignore
        except Exception as e:  # pragma: no cover - optional
            raise RuntimeError("pdfminer.six is required to parse PDFs. Try: python3 -m pip install pdfminer.six") from e

        items: list[ScheduleItem] = []

        # First, attempt table extraction where possible for structured schedules
        items = self._try_pdfplumber(path)
        if items:
            return items

        # Fall back to text extraction
        try:
            text = extract_text(str(path))
        except Exception as e:
            raise RuntimeError(f"Failed to extract text from PDF: {e}")

        # Target known Aurora Aquatics PDF shape (drop-in schedules)
        if "Town of Aurora" in text and ("Swimming Drop-In Schedules" in text or "drop-in Lane and Leisure swims" in text):
            return self._parse_aurora_text(text, path)

        # Fallback
        raise NotImplementedError("Generic PDF parsing not implemented. This parser supports Aurora drop-in schedules.")

    def _find_column_indices(self, header: list[str]) -> tuple[int | None, int | None]:
        """Find day and leisure column indices in table header."""
        day_idx = None
        leisure_idx = None
        for i, h in enumerate(header):
            hl = h.replace('\n', ' ').lower()
            if day_idx is None and 'day' in hl:
                day_idx = i
            if leisure_idx is None and 'leisure' in hl:
                leisure_idx = i
        return day_idx, leisure_idx

    def _parse_table_row(
        self, row: list[Any], day_idx: int, leisure_idx: int, path: str
    ) -> list[ScheduleItem]:
        """Parse a single table row and create schedule items."""
        items: list[ScheduleItem] = []
        if not row or len(row) <= max(day_idx, leisure_idx):
            return items

        day_spec = str(row[day_idx] or '').replace('\n', ' ').strip()
        leisure_cell = str(row[leisure_idx] or '').replace('\n', ' ').strip()
        if not leisure_cell:
            return items

        for code in normalize_days(day_spec):
            for st, en in extract_time_ranges(leisure_cell):
                items.append(ScheduleItem(
                    subject='Leisure Swim',
                    recurrence='weekly',
                    byday=[code],
                    start_time=st,
                    end_time=en,
                    range_start=_dt.date.today().isoformat(),
                    location='Aurora Pools',
                    notes=f'Imported from PDF {path}',
                ))
        return items

    def _extract_from_table(self, tbl: list[list[Any]], path: str) -> list[ScheduleItem]:
        """Extract schedule items from a single table."""
        items: list[ScheduleItem] = []
        if not tbl or not isinstance(tbl, list):
            return items

        header = [str(x or '').strip() for x in (tbl[0] or [])]
        day_idx, leisure_idx = self._find_column_indices(header)

        if day_idx is None or leisure_idx is None:
            return items

        for row in tbl[1:]:
            items.extend(self._parse_table_row(row, day_idx, leisure_idx, path))

        return items

    def _try_pdfplumber(self, path: str) -> list[ScheduleItem]:
        """Attempt to extract schedule using pdfplumber table extraction.

        Returns empty list if pdfplumber is not available or extraction fails.
        """
        try:
            import pdfplumber  # type: ignore
        except Exception:
            return []

        items: list[ScheduleItem] = []
        try:
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables() or []
                    for tbl in tables:
                        items.extend(self._extract_from_table(tbl, path))
        except (OSError, ValueError, KeyError) as e:  # nosec B110 - pdfplumber failures are non-fatal
            logger.warning("PDF table extraction failed (%s), returning partial results", type(e).__name__)

        return items

    def _parse_aurora_block(self, blk: str, path: str) -> list[ScheduleItem]:
        """Parse one Day-header block from Aurora text into schedule items."""
        if not re.search(r'Leisure', blk, re.I):
            return []
        if not re.search(r'\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)', blk, re.I):
            return []
        day_pattern = r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)'
        rows = re.findall(
            rf'({day_pattern}[^\n]*)\n(.*?)(?=\n{day_pattern}|\Z)',
            blk,
            re.I | re.DOTALL
        )
        items: list[ScheduleItem] = []
        for day_spec, rest in rows:
            for st, en in extract_time_ranges(rest):
                for code in normalize_days(day_spec):
                    items.append(ScheduleItem(
                        subject='Leisure Swim',
                        recurrence='weekly',
                        byday=[code],
                        start_time=st,
                        end_time=en,
                        range_start=_dt.date.today().isoformat(),
                        location='Aurora Pools',
                        notes=f'Imported from PDF {path}',
                    ))
        return items

    def _parse_aurora_text(self, text: str, path: str) -> list[ScheduleItem]:
        """Parse Aurora Aquatics schedule from extracted text."""
        t = text.replace("\r", "\n")
        t = re.sub(r"\n{2,}", "\n", t)
        blocks = re.split(r'(?:^|\n)\s*Day\s*\n', t)
        items: list[ScheduleItem] = []
        for blk in blocks[1:]:
            items.extend(self._parse_aurora_block(blk, path))
        return items
