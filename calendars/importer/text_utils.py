"""Text and time parsing utilities for schedule import."""
from __future__ import annotations

import re
from typing import List, Optional

from core.text_utils import normalize_unicode

from .constants import (
    DAY_NAMES,
    RE_AM_ONLY,
    RE_AMPM,
    RE_PM_ONLY,
    RE_STRIP_TAGS,
)
from ..constants import DAY_MAP


def strip_html_tags(s: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    return re.sub(RE_STRIP_TAGS, '', s).replace('\xa0', ' ').replace('&nbsp;', ' ').strip()


def normalize_day(day_name: str) -> str:
    """Convert day name to two-letter code (e.g., 'Monday' -> 'MO')."""
    return DAY_MAP.get(day_name.lower().strip(), '')


def normalize_days(spec: str) -> List[str]:
    """Parse day specification to list of two-letter codes.

    Handles ranges like 'Mon to Fri' and lists like 'Mon & Wed'.
    Also handles full day names like 'Monday', 'Saturday'.
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


def to_24h(time_str: str, am_pm: Optional[str] = None) -> Optional[str]:
    """Convert time string to 24-hour format (e.g., '1:45 p.m.' -> '13:45').

    If am_pm is None and not detectable, uses heuristic: hour >= 7 assumes PM.
    """
    t = (time_str or '').strip().lower().replace(' ', '')

    # Try to extract am/pm from the string itself
    detected_ampm = am_pm
    if detected_ampm is None:
        if re.search(r'p\.?m\.?', t):
            detected_ampm = 'pm'
        elif re.search(r'a\.?m\.?', t):
            detected_ampm = 'am'

    # Remove am/pm markers
    t_clean = re.sub(r'[ap]\.?m\.?', '', t).strip(' .')

    m = re.match(r'^(\d{1,2})(?::(\d{2}))?$', t_clean)
    if not m:
        return None

    hh = int(m.group(1))
    mm = int(m.group(2) or 0)

    # Apply am/pm conversion
    suf = detected_ampm
    if suf is None:
        # Heuristic: if hour >= 7 and <= 11, assume PM for evening schedules
        suf = 'pm' if 7 <= hh <= 11 else 'am'

    if suf.startswith('p') and hh < 12:
        hh += 12
    if suf.startswith('a') and hh == 12:
        hh = 0

    return f"{hh:02d}:{mm:02d}"


def parse_time_range(s: str) -> tuple[Optional[str], Optional[str]]:
    """Parse time range string to (start_24h, end_24h) tuple.

    Examples: '1:45 - 3:15 p.m.', '11:15 a.m. - 12:15 p.m.', '7 - 8:30 p.m.'
    """
    s = (s or '').strip()
    if not s or s == '\xa0':
        return None, None

    # Normalize unicode and separators
    s = normalize_unicode(s).replace(' to ', '-')

    # Detect am/pm for each side
    has_am = re.search(RE_AM_ONLY, s) is not None
    has_pm = re.search(RE_PM_ONLY, s) is not None

    # Strip am/pm text for splitting
    s_clean = re.sub(RE_AMPM, '', s)
    parts = [t.strip(' .') for t in s_clean.split('-') if t.strip()]
    if len(parts) != 2:
        return None, None

    # Determine am/pm for left and right sides
    if has_am and has_pm:
        left_suf, right_suf = 'am', 'pm'
    elif has_am:
        left_suf = right_suf = 'am'
    elif has_pm:
        left_suf = right_suf = 'pm'
    else:
        left_suf = right_suf = None

    start = to_24h(parts[0], left_suf)
    end = to_24h(parts[1], right_suf)
    return start, end


def extract_time_ranges(text: str) -> List[tuple[str, str]]:
    """Extract all time ranges from text.

    Finds patterns like '10:00 a.m. - 12:00 p.m.' or '9:00pm - 10:30pm'.
    Returns list of (start_24h, end_24h) tuples.
    """
    text = (text or '').replace('*', ' ').replace('\n', ' ')
    results: List[tuple[str, str]] = []

    # Match time range patterns with am/pm
    pattern = r'(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))\s*(?:-|to)\s*(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))'
    for m in re.finditer(pattern, text, re.I):
        start = to_24h(m.group(1))
        end = to_24h(m.group(2))
        if start and end:
            results.append((start, end))

    return results
