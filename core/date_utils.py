"""Shared date and time utilities.

Provides day-of-week parsing, month parsing, and ISO date conversions
used across multiple modules.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, List, Optional

from .constants import FMT_DATETIME_SEC, FMT_DAY_START

__all__ = [
    "DAY_MAP",
    "DAY_NAMES",
    "MONTH_MAP",
    "normalize_day",
    "normalize_days",
    "parse_month",
    "to_iso_str",
]

# Day-of-week name/abbreviation to RRULE code mapping
DAY_MAP = {
    "monday": "MO",
    "mon": "MO",
    "tuesday": "TU",
    "tue": "TU",
    "tues": "TU",
    "wednesday": "WE",
    "wed": "WE",
    "thursday": "TH",
    "thu": "TH",
    "thur": "TH",
    "thurs": "TH",
    "friday": "FR",
    "fri": "FR",
    "saturday": "SA",
    "sat": "SA",
    "sunday": "SU",
    "sun": "SU",
}

# Day name sequence for iteration (abbreviated, lowercase)
DAY_NAMES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

# Month name to number mapping (1-12)
MONTH_MAP = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"],
    start=1,
)}
MONTH_MAP.update({k[:3]: v for k, v in list(MONTH_MAP.items())})


def normalize_day(day_name: str) -> str:
    """Convert day name to two-letter RRULE code (e.g., 'Monday' -> 'MO')."""
    return DAY_MAP.get(day_name.lower().strip(), '')


def normalize_days(spec: str) -> List[str]:
    """Parse day specification to list of two-letter RRULE codes.

    Handles ranges like 'Mon to Fri' and lists like 'Mon & Wed'.
    Also handles full day names like 'Monday', 'Saturday'.

    Examples:
        'Monday' -> ['MO']
        'Mon to Fri' -> ['MO', 'TU', 'WE', 'TH', 'FR']
        'Mon & Wed' -> ['MO', 'WE']
        'Sat-Sun' -> ['SA', 'SU']
    """
    s = (spec or '').lower().replace('&', ' & ').replace('to', ' to ').replace('&amp;', '&')
    out: List[str] = []

    # Check for ranges like "Mon to Fri" or "Mon-Fri"
    m = re.search(r'\b(mon|tue|wed|thu|fri|sat|sun)\w*\b\s*(?:-|to)\s*\b(mon|tue|wed|thu|fri|sat|sun)\w*\b', s)
    if m:
        a, b = m.group(1), m.group(2)
        i1, i2 = DAY_NAMES.index(a), DAY_NAMES.index(b)
        rng = DAY_NAMES[i1:i2+1] if i1 <= i2 else (DAY_NAMES[i1:] + DAY_NAMES[:i2+1])
        return [DAY_MAP[d] for d in rng]

    # Check for individual days (supports both abbreviated and full names)
    for d in DAY_NAMES:
        if re.search(rf'\b{d}\w*\b', s):
            c = DAY_MAP[d]
            if c not in out:
                out.append(c)
    return out


def parse_month(month_str: str) -> Optional[int]:
    """Parse month name (full or abbreviated) to number (1-12).

    Examples:
        'January' -> 1
        'jan' -> 1
        'Dec' -> 12
    """
    cleaned = (month_str or "").strip().lower()
    return MONTH_MAP.get(cleaned) or MONTH_MAP.get(cleaned[:3])


def to_iso_str(v: Any) -> Optional[str]:
    """Convert a value to ISO datetime string.

    Args:
        v: A datetime, date, string, or other value.

    Returns:
        ISO-formatted string, or None if input is None.
    """
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        if isinstance(v, _dt.datetime):
            return v.strftime(FMT_DATETIME_SEC)
        if isinstance(v, _dt.date):
            return v.strftime(FMT_DAY_START)
    except Exception:  # nosec B110 - fallback to str(v)
        pass
    return str(v)
