"""Shared text processing utilities for assistant CLIs."""
from __future__ import annotations

import re
from html import unescape

__all__ = [
    "html_to_text",
    "normalize_unicode",
    "to_24h",
    "extract_email_address",
]


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


def to_24h(spec: str) -> str:
    """Convert 12-hour time spec to 24-hour format.

    Examples:
        '9:30am' -> '09:30'
        '1:00pm' -> '13:00'
    """
    s = (spec or "").strip().lower().replace(" ", "")
    m = re.match(r"(\d{1,2}):(\d{2})(am|pm)", s)
    if not m:
        return (spec or "").strip()
    h, mnt, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mnt:02d}"


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
