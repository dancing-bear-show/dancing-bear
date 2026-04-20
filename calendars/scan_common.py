"""Shared helpers for parsing class-like schedule emails (Gmail/Outlook)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from core.date_utils import MONTH_MAP
from core.text_utils import html_to_text  # noqa: F401 - re-exported for calendars.outlook.commands

TIME_PAT1 = r"(?P<h1>\d{1,2})(?::(?P<m1>\d{2}))?\s*(?P<ampm1>am|pm|a\.m\.|p\.m\.)?"
TIME_PAT2 = r"(?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\s*(?P<ampm2>am|pm|a\.m\.|p\.m\.)?"
RANGE_PAT = re.compile(
    rf"\b(?P<day>mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b[^\n\r]*?{TIME_PAT1}\s*(?:-|to|–|—)\s*{TIME_PAT2}",
    re.I,
)

_CLASS_PAT_PARTS = [
    r"swimmer\s?[0-9a-z]+",
    r"swim\s?kids\s?\d+",
    r"preschool\s?[a-f]",
    r"bronze\s?(?:star|medallion|cross)",
    r"private\s*lessons?",
]
CLASS_PAT = re.compile(r"\b(" + "|".join(_CLASS_PAT_PARTS) + r")\b", re.I)
LOC_LABEL_PAT = re.compile(r"^\s*(Location|Venue)\s*:\s*(.+)$", re.I | re.M)

FACILITIES = [
    "Ed Sackfield",
    "Elgin West",
    "Bayview Hill",
    "Richmond Green",
    "Oak Ridges",
]

_DATE_SEP = r"(?:-|to|–|—)"
_DATE_YEAR = r"(?:,\s*(\d{4}))?"
DATE_RANGE_PAT = re.compile(
    rf"(?:from\s+)?([a-z]{{3,9}})\s+(\d{{1,2}}){_DATE_YEAR}\s*{_DATE_SEP}\s*([a-z]{{3,9}})\s+(\d{{1,2}}){_DATE_YEAR}",
    re.I,
)


@dataclass(frozen=True)
class MetaParserConfig:
    """Configuration for metadata parsing from class schedule text."""

    facilities: Sequence[str] = ()
    date_range_pat: re.Pattern[str] = DATE_RANGE_PAT
    class_pat: re.Pattern[str] = CLASS_PAT
    loc_label_pat: re.Pattern[str] = LOC_LABEL_PAT
    default_year: Optional[int] = None

    def __post_init__(self):
        """Set default facilities if not provided."""
        if not self.facilities:
            object.__setattr__(self, "facilities", FACILITIES)


def norm_time(hour: str, minute: Optional[str], ampm: Optional[str]) -> str:
    hh = int(hour)
    mm = int(minute or 0)
    a = (ampm or "").replace(".", "").lower()
    if a in ("pm",) and hh < 12:
        hh += 12
    if a in ("am",) and hh == 12:
        hh = 0
    return f"{hh:02d}:{mm:02d}"


def _infer_location(text: str, cfg: "MetaParserConfig") -> Optional[str]:
    """Extract location from text using label pattern or facility list."""
    loc_match = cfg.loc_label_pat.search(text)
    if loc_match:
        return loc_match.group(2).strip()
    for facility in cfg.facilities:
        if facility.lower() in text.lower():
            return facility
    return None


def _infer_date_range(text: str, cfg: "MetaParserConfig") -> Optional[Dict[str, str]]:
    """Extract date range from text. Returns dict or None."""
    date_match = cfg.date_range_pat.search(text)
    if not date_match:
        return None
    m1, d1, y1, m2, d2, y2 = date_match.groups()
    try:
        cur_year = cfg.default_year or 0
        y1f = int(y1 or y2 or cur_year)
        y2f = int(y2 or y1 or cur_year)
        start_date = f"{y1f:04d}-{MONTH_MAP[m1.lower()]:02d}-{int(d1):02d}"
        end_date = f"{y2f:04d}-{MONTH_MAP[m2.lower()]:02d}-{int(d2):02d}"
        return {"start_date": start_date, "until": end_date}
    except Exception:  # nosec B110 - non-critical metadata extraction
        return None


def infer_meta_from_text(
    text: str,
    config: Optional[MetaParserConfig] = None,
) -> Dict[str, Any]:
    """Extract metadata from class schedule text.

    Args:
        text: Input text to parse
        config: Optional parser configuration (uses defaults if None)

    Returns:
        Dictionary with extracted metadata (location, range, subject)
    """
    cfg = config or MetaParserConfig()
    safe_text = text or ""
    meta: Dict[str, Any] = {}

    loc = _infer_location(safe_text, cfg)
    if loc:
        meta["location"] = loc

    date_range = _infer_date_range(safe_text, cfg)
    if date_range:
        meta["range"] = date_range

    class_match = cfg.class_pat.search(safe_text)
    if class_match:
        meta["subject"] = class_match.group(0).strip().title()

    return meta
