"""Document metadata and styling shared by the slides and sheets generators.

Pure Python with no third-party imports, so either generator can use it
without pulling in the other's backend (python-pptx or openpyxl).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["HEADER_BG_HEX", "DocMetadata", "parse_doc_metadata"]

# Table header row background, dark blue-gray: 6-char RGB hex, no leading "#".
HEADER_BG_HEX = "2D3A4F"

_KEY_TITLE = "title"
_KEY_AUTHOR = "author"
_KEY_DATE = "date"


@dataclass(frozen=True)
class DocMetadata:
    """The title/author/date triple every generated document carries."""

    title: str
    author: str | None
    date: str | None


def parse_doc_metadata(data: Mapping[str, Any], default_title: str) -> DocMetadata:
    """Read title, author and date from a top-level YAML mapping.

    A missing title falls back to *default_title*. A missing or null date is
    ``None``; any other date (YAML may parse it as ``datetime.date``) is
    stringified. Title and author pass through as given.
    """
    raw_date = data.get(_KEY_DATE)
    return DocMetadata(
        title=data.get(_KEY_TITLE, default_title),
        author=data.get(_KEY_AUTHOR),
        date=None if raw_date is None else str(raw_date),
    )
