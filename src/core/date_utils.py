"""Shared date and time utilities.

Provides day-of-week parsing, month parsing, and ISO date conversions
used across multiple modules.
"""

from __future__ import annotations

import datetime as _dt
import functools
import re
from datetime import datetime, timedelta
from typing import Any

from .constants import FMT_DATETIME_SEC, FMT_DAY_END, FMT_DAY_START

__all__ = [
    "DAY_MAP",
    "DAY_NAMES",
    "MONTH_MAP",
    "RRULE_CODE_TO_DAY_NAME",
    "day_range_to_iso",
    "iso_now",
    "normalize_day",
    "normalize_days",
    "now_utc",
    "parse_duration_seconds",
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
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# RRULE code -> Python weekday index, matching datetime.date.weekday()
# (Monday = 0). Derived from DAY_NAMES so the ordering has one source.
RRULE_CODE_TO_WEEKDAY: dict[str, int] = {
    DAY_MAP[_day]: _index for _index, _day in enumerate(DAY_NAMES)
}

# Month name to number mapping (1-12)
MONTH_MAP = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}
MONTH_MAP.update({k[:3]: v for k, v in list(MONTH_MAP.items())})


def normalize_day(day_name: str) -> str:
    """Convert day name to two-letter RRULE code (e.g., 'Monday' -> 'MO')."""
    return DAY_MAP.get(day_name.lower().strip(), "")


def normalize_days(spec: str | None) -> list[str]:
    """Parse day specification to list of two-letter RRULE codes.

    Handles ranges like 'Mon to Fri' and lists like 'Mon & Wed'.
    Also handles full day names like 'Monday', 'Saturday'.

    Examples:
        'Monday' -> ['MO']
        'Mon to Fri' -> ['MO', 'TU', 'WE', 'TH', 'FR']
        'Mon & Wed' -> ['MO', 'WE']
        'Sat-Sun' -> ['SA', 'SU']
    """
    s = (spec or "").lower().replace("&", " & ").replace("to", " to ").replace("&amp;", "&")
    out: list[str] = []

    # Check for ranges like "Mon to Fri" or "Mon-Fri"
    m = re.search(
        r"\b(mon|tue|wed|thu|fri|sat|sun)\w*\b\s*(?:-|to)\s*\b(mon|tue|wed|thu|fri|sat|sun)\w*\b", s
    )
    if m:
        a, b = m.group(1), m.group(2)
        i1, i2 = DAY_NAMES.index(a), DAY_NAMES.index(b)
        rng = DAY_NAMES[i1 : i2 + 1] if i1 <= i2 else (DAY_NAMES[i1:] + DAY_NAMES[: i2 + 1])
        return [DAY_MAP[d] for d in rng]

    # Check for individual days (supports both abbreviated and full names)
    for d in DAY_NAMES:
        if re.search(rf"\b{d}\w*\b", s):
            c = DAY_MAP[d]
            if c not in out:
                out.append(c)
    return out


def parse_month(month_str: str | None) -> int | None:
    """Parse month name (full or abbreviated) to number (1-12).

    Examples:
        'January' -> 1
        'jan' -> 1
        'Dec' -> 12
    """
    cleaned = (month_str or "").strip().lower()
    return MONTH_MAP.get(cleaned) or MONTH_MAP.get(cleaned[:3])


def to_iso_str(v: Any) -> str | None:
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


def day_range_to_iso(from_date: str, to_date: str) -> tuple[str, str]:
    """Widen two ``YYYY-MM-DD`` dates into an inclusive ISO datetime range.

    Returns ``(start_iso, end_iso)`` spanning midnight on ``from_date`` through
    23:59:59 on ``to_date`` -- the window shape the Outlook list-events calls
    expect.

    Raises ``ValueError`` on either date being unparseable or not a string.
    Callers that need a different error type should catch it and re-raise;
    the three schedule call sites deliberately differ (two raise ``CLIError``
    with ``ExitCode.USAGE``, one raises ``ValueError``), so this helper raises
    the primitive and leaves that translation to them.
    """
    try:
        start_iso = _dt.datetime.fromisoformat(from_date).strftime(FMT_DAY_START)
        end_iso = _dt.datetime.fromisoformat(to_date).strftime(FMT_DAY_END)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid --from/--to date format; expected YYYY-MM-DD") from exc
    return start_iso, end_iso


def now_utc() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(tz=_dt.UTC)


def iso_now() -> str:
    """Return the current UTC time as an ISO 8601 string (e.g. '2024-01-15T10:30:00Z')."""
    return datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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


DURATION_UNIT_SECONDS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


@functools.lru_cache(maxsize=32)
def _duration_patterns(units: str, compound: bool) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """Return (whole-string, single-part) patterns for the given unit letters."""
    part = rf"\d+[{re.escape(units)}]"
    whole = rf"(?:{part})+" if compound else part
    return re.compile(whole), re.compile(rf"(\d+)([{re.escape(units)}])")


def parse_duration_seconds(
    s: str | None,
    *,
    units: str = "smhdw",
    compound: bool = True,
    bare_unit: str | None = None,
) -> int | None:
    """Parse a relative duration like '90m', '2h' or '1h30m' into seconds.

    Strict: the whole string (after strip + lowercase) must be well-formed, so
    embedded junk ('abc2hxyz'), signs ('-5h') and inner whitespace return None
    rather than salvaging a digit-unit pair. Zero ('0s') is valid and returns 0.

    units: allowed unit letters, a subset of 'smhdw'.
    compound: accept several <digits><unit> parts ('1h30m') rather than one.
    bare_unit: unit applied to a bare integer ('30'); None rejects bare digits.
    Returns None for empty/None input and any malformed value.
    """
    if not s:
        return None
    s = s.strip().lower()
    if bare_unit is not None and s.isascii() and s.isdigit():
        mult = DURATION_UNIT_SECONDS.get(bare_unit.lower())
        return int(s) * mult if mult and bare_unit.lower() in units else None
    whole, part = _duration_patterns(units, compound)
    if not whole.fullmatch(s):
        return None
    return sum(int(n) * DURATION_UNIT_SECONDS[u] for n, u in part.findall(s))


def parse_window(win: str, default_unit: str = "hours") -> timedelta:
    """Parse a time window string like '7d', '24h', '30m' into a timedelta.

    Supported units: s (seconds), m (minutes), h (hours), d (days), w (weeks).
    A bare integer uses the first letter of default_unit.
    """
    win = win.strip().lower()
    secs = parse_duration_seconds(win, compound=False, bare_unit=default_unit[:1])
    if secs is None:
        raise ValueError(f"Cannot parse time window: {win!r}")
    return timedelta(seconds=secs)


def parse_iso_utc(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to a UTC-aware datetime, or None on failure."""
    if not value:
        return None
    try:
        # Strip before parsing: worker's --not-before takes user-supplied
        # timestamps and queue_ops treats a parse failure as "run now", so a
        # stray space would silently drop the scheduling guarantee.
        s = value.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.UTC)
        else:
            dt = dt.astimezone(_dt.UTC)
        return dt
    except (ValueError, AttributeError):
        return None
