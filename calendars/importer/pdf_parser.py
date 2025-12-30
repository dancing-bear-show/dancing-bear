"""PDF schedule parser."""
from __future__ import annotations

import datetime as _dt
import re
from typing import List

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
                        if not tbl or not isinstance(tbl, list):
                            continue
                        header = [str(x or '').strip() for x in (tbl[0] or [])]

                        # Identify Day and Leisure Swim columns
                        day_idx = None
                        leisure_idx = None
                        for i, h in enumerate(header):
                            hl = h.replace('\n', ' ').lower()
                            if day_idx is None and 'day' in hl:
                                day_idx = i
                            if leisure_idx is None and 'leisure' in hl:
                                leisure_idx = i

                        if day_idx is None or leisure_idx is None:
                            continue

                        # Parse rows
                        for row in tbl[1:]:
                            if not row or len(row) <= max(day_idx, leisure_idx):
                                continue
                            day_spec = str(row[day_idx] or '').replace('\n', ' ').strip()
                            leisure_cell = str(row[leisure_idx] or '').replace('\n', ' ').strip()
                            if not leisure_cell:
                                continue
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
        except Exception:  # noqa: S110 - pdfplumber failure falls through to text extraction
            pass

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

        t = re.sub(r"\r", "\n", text)
        t = re.sub(r"\n{2,}", "\n", t)

        # Split into rough sections by headers and process rows
        blocks = re.split(r'\n\s*Day\s*\n', t)
        for blk in blocks[1:]:
            # Heuristic: check if block contains "Leisure" header and at least one weekday
            if not re.search(r'Leisure', blk, re.I):
                continue
            if not re.search(r'\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)', blk, re.I):
                continue

            # Split into row-ish chunks, starting with a day spec
            rows = re.findall(
                r'((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[^\n]*?(?:\bto\b[^\n]*)?)\n([\s\S]*?)(?=\n(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)|\Z)',
                blk,
                re.I
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


# Backward compatibility function
def parse_pdf(path: str) -> List[ScheduleItem]:
    """Parse schedule items from PDF file.

    Args:
        path: Path to PDF file

    Returns:
        List of ScheduleItem objects
    """
    return PDFParser().parse(path)
