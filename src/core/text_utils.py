"""Shared text processing utilities for assistant CLIs."""
from __future__ import annotations

import re
from html import unescape
from typing import List, Optional

from .patterns import RE_AM_ONLY, RE_AMPM, RE_PM_ONLY, RE_STRIP_TAGS

__all__ = [
    "html_to_text",
    "normalize_unicode",
    "strip_html_tags",
    "strip_css_boilerplate",
    "to_24h",
    "parse_time_range",
    "extract_time_ranges",
    "extract_email_address",
    "truncate_text",
]

# CSS comment blocks: /* ... */ (non-greedy, spans newlines)
_RE_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)

# Leftover <style>...</style> tags that survive HTML-to-text flattening.
_RE_STYLE_TAG = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.I | re.S)

# Common HTML tag names used as bare CSS selectors in email boilerplate.
# Deliberately a fixed allowlist (not "any word") so ordinary prose words
# immediately followed by "{...}" are never mistaken for a selector.
_CSS_BARE_TAGS = (
    "html|body|head|div|span|table|thead|tbody|tfoot|tr|td|th|p|a|img|ul|ol|li"
    "|h[1-6]|strong|em|b|i|u|br|hr|form|input|button|label|small|font"
)
# One CSS selector token: #id, .class, an allowlisted bare tag, *, or an
# at-rule name like @media.
_CSS_SELECTOR_TOKEN = rf"(?:[#.][\w-]+|(?:{_CSS_BARE_TAGS})\b|\*|@[A-Za-z-]+[^{{,]*)"
# A selector list is one or more tokens optionally combined with combinators
# (space, >, +, ~, :pseudo-class) and comma-separated, e.g.
# "#id .class, a:hover td.foo".
_CSS_SELECTOR = (
    rf"{_CSS_SELECTOR_TOKEN}(?:[:\w.#-]*(?:[ \t]*[>+~][ \t]*|[ \t]+)?{_CSS_SELECTOR_TOKEN})*"
)
# Rule body: declarations, allowing one level of nesting for @media blocks
# that wrap inner rule sets, e.g. "@media ... { .foo { color: red; } }".
_CSS_RULE_BODY = r"[^{}]*(?:\{[^{}]*\}[^{}]*)*"
# A CSS rule block: "<selector list> { declarations }".
_RE_CSS_RULE = re.compile(
    rf"(?:(?<=^)|(?<=[\s;}}]))"
    rf"{_CSS_SELECTOR}(?:,\s*{_CSS_SELECTOR})*"
    rf"[ \t]*\{{{_CSS_RULE_BODY}\}}",
)

# Three-or-more blank lines left behind after removing CSS blocks.
_RE_EXCESS_BLANK_LINES = re.compile(r"\n[ \t]*\n[ \t]*(?:\n[ \t]*)+")


def strip_css_boilerplate(s: str) -> str:
    """Strip CSS comment blocks, ``<style>`` tags, and CSS rule blocks from text.

    Transactional email senders (booking/receipt systems) frequently emit a
    ``text/plain`` MIME part that is really an HTML email flattened to text,
    leaving raw CSS at the top. This targets that shape without touching
    legitimate prose: rule blocks are only removed when the selector looks
    like real CSS (``#id``, ``.class``, an allowlisted HTML tag name, or an
    ``@media``-style at-rule), so text like ``Balance Due { $0.00 }`` is left
    untouched.

    Args:
        s: Text possibly containing CSS boilerplate.

    Returns:
        Text with CSS blocks removed. If no CSS is found, returns the input
        unchanged (byte-identical).
    """
    if not s:
        return s
    cleaned = _RE_STYLE_TAG.sub(" ", s)
    cleaned = _RE_CSS_COMMENT.sub(" ", cleaned)
    cleaned = _RE_CSS_RULE.sub(" ", cleaned)
    if cleaned == s:
        return s
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = _RE_EXCESS_BLANK_LINES.sub("\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip()


def html_to_text(s: str) -> str:
    """Convert HTML to plain text.

    - Converts <br> and <p> tags to newlines
    - Removes all other HTML tags
    - Unescapes HTML entities
    - Normalizes whitespace
    """
    if not s:
        return ""
    s = re.sub(r"<\s*br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<\s*p\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_unicode(text: str) -> str:
    """Normalize unicode characters for consistent text processing.

    - Converts non-breaking hyphen, en-dash, em-dash to regular hyphen
    - Converts non-breaking space to regular space
    """
    if not text:
        return ""
    t = text.replace('\u2011', '-')  # non-breaking hyphen
    t = t.replace('\u2013', '-')     # en dash
    t = t.replace('\u2014', '-')     # em dash
    t = t.replace('\u00A0', ' ')     # non-breaking space
    return t


def strip_html_tags(s: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    return re.sub(RE_STRIP_TAGS, '', s).replace('\xa0', ' ').replace('&nbsp;', ' ').strip()


def to_24h(time_str: str, am_pm: Optional[str] = None) -> Optional[str]:
    """Convert time string to 24-hour format.

    Args:
        time_str: Time string like '1:45 p.m.', '9:30am', '7'
        am_pm: Optional explicit am/pm suffix. If None, detects from string
               or uses heuristic (hour 7-11 assumes PM for evening schedules).

    Returns:
        24-hour formatted time string (e.g., '13:45', '09:30'), or None if unparseable.

    Examples:
        '9:30am' -> '09:30'
        '1:00pm' -> '13:00'
        '1:45 p.m.' -> '13:45'
        to_24h('7', 'pm') -> '19:00'
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

    Handles various formats with am/pm detection and boundary inference.

    Args:
        s: Time range string like '1:45 - 3:15 p.m.' or '11:15 a.m. - 12:15 p.m.'

    Returns:
        Tuple of (start_24h, end_24h), or (None, None) if unparseable.

    Examples:
        '1:45 - 3:15 p.m.' -> ('13:45', '15:15')
        '11:15 a.m. - 12:15 p.m.' -> ('11:15', '12:15')
        '7 - 8:30 p.m.' -> ('19:00', '20:30')
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

    Args:
        text: Text containing time range patterns.

    Returns:
        List of (start_24h, end_24h) tuples.
    """
    text = (text or '').replace('*', ' ').replace('\n', ' ')
    results: List[tuple[str, str]] = []

    # Match time range patterns with am/pm using simplified pattern
    time_pat = r'(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)'
    sep_pat = r'\s*(?:[-–—]|to)\s*'
    for m in re.finditer(time_pat + sep_pat + time_pat, text, re.I):
        start = to_24h(m.group(1))
        end = to_24h(m.group(2))
        if start and end:
            results.append((start, end))

    return results


def extract_email_address(s: str) -> str:
    """Extract bare email address from a From-like string.

    Examples:
        'Name <user@example.com>' -> 'user@example.com'
        'user@example.com' -> 'user@example.com'
    """
    if not s:
        return s
    m = re.search(r"<([^>]+@[^>]+)>", s)
    if m:
        return m.group(1).strip().lower()
    m2 = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", s)
    return (m2.group(0).strip().lower() if m2 else s.strip().lower())


def truncate_text(s: str, max_len: int, suffix: str = "…", **_kwargs: object) -> str:
    """Truncate s to max_len chars, appending suffix if truncated."""
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    cut = max_len - len(suffix)
    if cut <= 0:
        return s[:max_len]
    return s[:cut] + suffix
