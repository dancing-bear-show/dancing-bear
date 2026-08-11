"""Shared date and time utilities.

Provides day-of-week parsing, month parsing, and ISO date conversions
used across multiple modules.
"""
from __future__ import annotations

import datetime as _dt
import re
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from .constants import FMT_DATETIME_SEC, FMT_DAY_START

__all__ = [
    "DAY_MAP",
    "DAY_NAMES",
    "MONTH_MAP",
    "RRULE_CODE_TO_DAY_NAME",
    "iso_now",
    "normalize_day",
    "normalize_days",
    "now_utc",
    "parse_iso_utc",
    "parse_iso_utc_strict",
    "parse_month",
    "parse_window",
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

# Inverse of DAY_MAP (RRULE code -> full day name). DAY_MAP has multiple
# spellings per code (e.g. "tue"/"tues"/"tuesday"); keep the longest, which
# is always the full name.
RRULE_CODE_TO_DAY_NAME: dict[str, str] = {}
for _name, _code in DAY_MAP.items():
    if len(_name) > len(RRULE_CODE_TO_DAY_NAME.get(_code, "")):
        RRULE_CODE_TO_DAY_NAME[_code] = _name
del _name, _code

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


def now_utc() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    """Return the current UTC time as an ISO 8601 string (e.g. '2024-01-15T10:30:00Z')."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc_strict(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, raising ValueError on failure.

    "Strict" refers to the error behaviour, not the accepted syntax: unlike
    parse_iso_utc (which returns None), this raises. Any form fromisoformat
    understands is accepted, including 'Z', '+00:00' offsets and fractional
    seconds -- worker's --not-before takes user-supplied timestamps, so
    narrowing this to the 'Z'-only form iso_now() emits would reject valid
    input and, because callers treat a parse failure as "run now", silently
    drop the scheduling guarantee.
    """
    dt = parse_iso_utc(ts)
    if dt is None:
        raise ValueError(f"invalid ISO timestamp: {ts}")
    return dt


def parse_window(win: str, default_unit: str = "hours") -> timedelta:
    """Parse a time window string like '7d', '24h', '30m' into a timedelta.

    Supported units: s (seconds), m (minutes), h (hours), d (days), w (weeks).
    """
    import re as _re
    win = win.strip().lower()
    m = _re.fullmatch(r"(\d+)([smhdw]?)", win)
    if not m:
        raise ValueError(f"Cannot parse time window: {win!r}")
    value = int(m.group(1))
    unit = m.group(2) or default_unit[0]
    if unit == "s":
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    if unit == "w":
        return timedelta(weeks=value)
    raise ValueError(f"Unknown time unit in window: {win!r}")


def parse_iso_utc(value: str | None) -> "datetime | None":
    """Parse an ISO 8601 string to a UTC-aware datetime, or None on failure."""
    if not value:
        return None
    try:
        s = value
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None
