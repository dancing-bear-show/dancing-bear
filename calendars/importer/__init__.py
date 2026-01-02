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
from .csv_parser import CSVParser
from .xlsx_parser import XLSXParser
from .pdf_parser import PDFParser
from .web_parser import (
    WebParser,
    RichmondHillSkatingParser,
    RichmondHillSwimmingParser,
    AuroraAquaticsParser,
    parse_website,
)


# Parser registry: maps kind/extension to parser class
_KIND_PARSERS = {
    'csv': CSVParser,
    'xlsx': XLSXParser,
    'pdf': PDFParser,
    'website': WebParser,
    'html': WebParser,
    'url': WebParser,
}

_EXT_PARSERS = {
    '.csv': CSVParser,
    '.xlsx': XLSXParser,
    '.xlsm': XLSXParser,
    '.pdf': PDFParser,
}


def _get_parser_for_source(source: str, kind: Optional[str]) -> ScheduleParser:
    """Get appropriate parser for source based on kind or extension."""
    k = (kind or '').strip().lower()

    # Explicit kind takes precedence
    if k and k != 'auto':
        parser_cls = _KIND_PARSERS.get(k)
        if parser_cls is None:
            raise ValueError(f"Unknown schedule kind: {kind}")
        return parser_cls()

    # Auto-detect from extension
    ext = (os.path.splitext(source)[1] or '').lower()
    parser_cls = _EXT_PARSERS.get(ext, CSVParser)  # Default to CSV
    return parser_cls()


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
    return _get_parser_for_source(source, kind).parse(source)


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
    # Functions
    'parse_website',
    'load_schedule',
]
