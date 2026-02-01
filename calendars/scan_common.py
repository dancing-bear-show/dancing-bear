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

# Simplified class patterns - split into smaller alternatives
_SWIMMER_PAT = r"swimmer\s?[\da-z]+"
_SWIM_KIDS_PAT = r"swim\s?kids\s?\d+"
_PRESCHOOL_PAT = r"preschool\s?[a-f]"
_BRONZE_PAT = r"bronze\s?(?:star|medallion|cross)"
_PRIVATE_PAT = r"private\s*lessons?"
CLASS_PAT = re.compile(
    rf"\b({_SWIMMER_PAT}|{_SWIM_KIDS_PAT}|{_PRESCHOOL_PAT}|{_BRONZE_PAT}|{_PRIVATE_PAT})\b",
    re.I,
)
LOC_LABEL_PAT = re.compile(r"^\s*(Location|Venue)\s*:\s*(.+)$", re.I | re.M)

FACILITIES = [
    "Ed Sackfield",
    "Elgin West",
    "Bayview Hill",
    "Richmond Green",
    "Oak Ridges",
]

# Simplified date range pattern - split components to reduce complexity
_MONTH_PAT = r"\w{3,9}"
_DAY_PAT = r"\d{1,2}"
_YEAR_PAT = r"(?:,\s*(\d{4}))?"
_SEP_PAT = r"[-–—to]+"
DATE_RANGE_PAT = re.compile(
    rf"(?:from\s+)?({_MONTH_PAT})\s+({_DAY_PAT}){_YEAR_PAT}\s*{_SEP_PAT}\s*({_MONTH_PAT})\s+({_DAY_PAT}){_YEAR_PAT}",
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


def _extract_location(text: str, cfg: MetaParserConfig) -> Optional[str]:
    """Extract location from text."""
    loc_match = cfg.loc_label_pat.search(text or "")
    if loc_match:
        return loc_match.group(2).strip()
    for facility in cfg.facilities:
        if facility.lower() in (text or "").lower():
            return facility
    return None


def _extract_date_range(text: str, cfg: MetaParserConfig) -> Optional[Dict[str, str]]:
    """Extract date range from text."""
    date_match = cfg.date_range_pat.search(text or "")
    if not date_match:
        return None
    try:
        m1, d1, y1, m2, d2, y2 = date_match.groups()
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
    meta: Dict[str, Any] = {}

    location = _extract_location(text, cfg)
    if location:
        meta["location"] = location

    date_range = _extract_date_range(text, cfg)
    if date_range:
        meta["range"] = date_range

    class_match = cfg.class_pat.search(text or "")
    if class_match:
        meta["subject"] = class_match.group(0).strip().title()

    return meta
