from __future__ import annotations

"""Text parsing helpers for email/HTML schedule extraction."""

import re
from html import unescape
import re as _re


def html_to_text(s: str) -> str:
    if not s:
        return ""
    # Replace breaks and paragraphs with newlines, strip tags, unescape entities
    s = re.sub(r"<\s*br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<\s*p\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    # Normalize whitespace
    return re.sub(r"\s+", " ", s).strip()


def to_24h(spec: str) -> str:
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
      - 'Name <user@example.com>' -> 'user@example.com'
      - 'user@example.com' -> 'user@example.com'
    """
    if not s:
        return s
    m = _re.search(r"<([^>]+@[^>]+)>", s)
    if m:
        return m.group(1).strip().lower()
    m2 = _re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", s)
    return (m2.group(0).strip().lower() if m2 else s.strip().lower())
