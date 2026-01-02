"""Shared regex patterns for text parsing.

These patterns are used across multiple modules for parsing
time expressions, HTML content, and other common text formats.
"""
from __future__ import annotations

# HTML parsing
RE_STRIP_TAGS = r'<[^>]+>'
RE_TABLE_CELL = r'<t[dh][^>]*>([\s\S]*?)</t[dh]>'
RE_TABLE_ROW = r'<tr[\s\S]*?>([\s\S]*?)</tr>'

# Time parsing
RE_AMPM = r'(?i)\b(a\.?m\.?|p\.?m\.?)\b'
RE_AM_ONLY = r'(?i)\b(a\.?m\.?)\b'
RE_PM_ONLY = r'(?i)\b(p\.?m\.?)\b'
RE_TIME = r'^(\d{1,2})(?::(\d{2}))?'
