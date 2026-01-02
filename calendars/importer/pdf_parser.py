"""PDF schedule parser."""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, List

from .base import ScheduleParser
from .model import ScheduleItem
from .text_utils import extract_time_ranges, normalize_days


class PDFParser(ScheduleParser):
    """Parser for PDF schedule files.

    Supports Aurora Aquatics drop-in schedules with both pdfplumber (table extraction)
    and pdfminer.six (text extraction) fallback.
    """

    def parse(self, path: str) -> List[ScheduleItem]:
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

        items: List[ScheduleItem] = []

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

    def _find_column_indices(self, header: List[str]) -> tuple[int | None, int | None]:
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
        self, row: List[Any], day_idx: int, leisure_idx: int, path: str
    ) -> List[ScheduleItem]:
        """Parse a single table row and create schedule items."""
        items: List[ScheduleItem] = []
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

    def _extract_from_table(self, tbl: List[List[Any]], path: str) -> List[ScheduleItem]:
        """Extract schedule items from a single table."""
        items: List[ScheduleItem] = []
        if not tbl or not isinstance(tbl, list):
            return items

        header = [str(x or '').strip() for x in (tbl[0] or [])]
        day_idx, leisure_idx = self._find_column_indices(header)

        if day_idx is None or leisure_idx is None:
            return items

        for row in tbl[1:]:
            items.extend(self._parse_table_row(row, day_idx, leisure_idx, path))

        return items

    def _try_pdfplumber(self, path: str) -> List[ScheduleItem]:
        """Attempt to extract schedule using pdfplumber table extraction.

        Returns empty list if pdfplumber is not available or extraction fails.
        """
        try:
            import pdfplumber  # type: ignore
        except Exception:
            return []

        items: List[ScheduleItem] = []
        try:
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables() or []
                    for tbl in tables:
                        items.extend(self._extract_from_table(tbl, path))
        except (OSError, ValueError, KeyError) as e:  # nosec B110 - pdfplumber failures are non-fatal
            # PDF parsing may fail due to corrupt files, missing tables, or format changes
            # Return partial results and let caller fall back to text extraction
            import sys
            print(f"Warning: PDF table extraction failed ({type(e).__name__}), returning partial results", file=sys.stderr)

        return items

    def _parse_aurora_text(self, text: str, path: str) -> List[ScheduleItem]:
        """Parse Aurora Aquatics schedule from extracted text.

        Args:
            text: Extracted text from PDF
            path: Original PDF path for notes

        Returns:
            List of ScheduleItem objects
        """
        items: List[ScheduleItem] = []

        t = text.replace("\r", "\n")
        t = re.sub(r"\n{2,}", "\n", t)

        # Split into rough sections by headers and process rows
        # Match Day header at start of string or after a newline
        blocks = re.split(r'(?:^|\n)\s*Day\s*\n', t)
        for blk in blocks[1:]:
            # Heuristic: check if block contains "Leisure" header and at least one weekday
            if not re.search(r'Leisure', blk, re.I):
                continue
            if not re.search(r'\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)', blk, re.I):
                continue

            # Split into row-ish chunks, starting with a day spec
            # Match: Day name + rest of line, newline, then content until next day or end
            day_pattern = r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)'
            rows = re.findall(
                rf'({day_pattern}[^\n]*)\n(.*?)(?=\n{day_pattern}|\Z)',
                blk,
                re.I | re.DOTALL
            )
            for day_spec, rest in rows:
                # Extract Leisure Swim times from rest
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
