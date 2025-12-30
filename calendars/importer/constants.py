"""Constants for schedule importer.

Regex patterns and day mappings used across parsers.
"""

# Regex pattern constants for HTML parsing
RE_STRIP_TAGS = r'<[^>]+>'
RE_AMPM = r'(?i)\b(a\.?m\.?|p\.?m\.?)\b'
RE_AM_ONLY = r'(?i)\b(a\.?m\.?)\b'
RE_PM_ONLY = r'(?i)\b(p\.?m\.?)\b'
RE_TIME = r'^(\d{1,2})(?::(\d{2}))?'
RE_TABLE_CELL = r'<t[dh][^>]*>([\s\S]*?)</t[dh]>'
RE_TABLE_ROW = r'<tr[\s\S]*?>([\s\S]*?)</tr>'

# Day name sequence for iteration
DAY_NAMES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
