"""Schedule Importer scaffolding.

Parses schedules from simple tabular sources (CSV/XLSX) and produces
recurring/one-off event specs suitable for Outlook calendar creation.

Heavy parsers (PDF/HTML) are optional and lazily imported.

This module provides an object-oriented parser architecture with backward
compatibility for the original functional API.
"""
from __future__ import annotations

import os
from typing import List, Optional

# Public API - Data Model
from .model import ScheduleItem

# Public API - Text Utilities
from .text_utils import (
    extract_time_ranges,
    normalize_day,
    normalize_days,
    parse_time_range,
    strip_html_tags,
    to_24h,
)

# Public API - Constants (for tests)
from .constants import (
    DAY_NAMES,
    RE_AMPM,
    RE_AM_ONLY,
    RE_PM_ONLY,
    RE_STRIP_TAGS,
    RE_TABLE_CELL,
    RE_TABLE_ROW,
    RE_TIME,
)

# Public API - Base Parser
from .base import ScheduleParser

# Public API - Format Parsers
from .csv_parser import CSVParser, parse_csv
from .xlsx_parser import XLSXParser, parse_xlsx
from .pdf_parser import PDFParser, parse_pdf
from .web_parser import (
    WebParser,
    RichmondHillSkatingParser,
    RichmondHillSwimmingParser,
    AuroraAquaticsParser,
    parse_website,
)

# Private helpers (exposed for backward compatibility with tests)
_get_field = ScheduleParser._get_field
_row_to_schedule_item = ScheduleParser._row_to_schedule_item


def load_schedule(source: str, kind: Optional[str] = None) -> List[ScheduleItem]:
    """Load schedule items from a source path/URL.

    Args:
        source: Path to file or URL to parse
        kind: Type of source - one of: csv, xlsx, pdf, website, auto
              If 'auto' or None, determines type from file extension

    Returns:
        List of ScheduleItem objects

    Raises:
        ValueError: If kind is unknown
        NotImplementedError: If source format is not supported
    """
    ext = (os.path.splitext(source)[1] or '').lower()
    k = (kind or '').strip().lower()

    if k in ('', 'auto'):
        if ext == '.csv':
            return CSVParser().parse(source)
        if ext in ('.xlsx', '.xlsm'):
            return XLSXParser().parse(source)
        if ext == '.pdf':
            return PDFParser().parse(source)
        # Default to csv
        return CSVParser().parse(source)

    if k == 'csv':
        return CSVParser().parse(source)
    if k == 'xlsx':
        return XLSXParser().parse(source)
    if k == 'pdf':
        return PDFParser().parse(source)
    if k in ('website', 'html', 'url'):
        return WebParser().parse(source)

    raise ValueError(f"Unknown schedule kind: {kind}")


__all__ = [
    # Data Model
    'ScheduleItem',
    # Text Utilities
    'extract_time_ranges',
    'normalize_day',
    'normalize_days',
    'parse_time_range',
    'strip_html_tags',
    'to_24h',
    # Constants
    'DAY_NAMES',
    'RE_AMPM',
    'RE_AM_ONLY',
    'RE_PM_ONLY',
    'RE_STRIP_TAGS',
    'RE_TABLE_CELL',
    'RE_TABLE_ROW',
    'RE_TIME',
    # Parsers (OO)
    'ScheduleParser',
    'CSVParser',
    'XLSXParser',
    'PDFParser',
    'WebParser',
    'RichmondHillSkatingParser',
    'RichmondHillSwimmingParser',
    'AuroraAquaticsParser',
    # Functions (backward compatibility)
    'parse_csv',
    'parse_xlsx',
    'parse_pdf',
    'parse_website',
    'load_schedule',
    # Private (for tests)
    '_get_field',
    '_row_to_schedule_item',
]
