"""KeywordMatcher: Unified keyword matching and synonym handling.

This module is now a thin shim; implementation lives in:
  - resume.keyword_normalize: KeywordInfo, KeywordMatchResult, SynonymRegistry, normalize_text
  - resume.keyword_match: KeywordMatchEngine, keyword_match
"""
from __future__ import annotations

from resume.keyword_normalize import KeywordInfo, KeywordMatchResult, normalize_text  # noqa: F401
from resume.keyword_match import KeywordMatchEngine, keyword_match  # noqa: F401
from typing import Iterable

# Backwards-compatible alias for code that imports MatchResult from this module
MatchResult = KeywordMatchResult


class KeywordMatcher(KeywordMatchEngine):
    """Unified keyword matching with synonym support and scoring.

    Re-exported for backwards compatibility. All logic lives in
    KeywordMatchEngine (resume.keyword_match) and SynonymRegistry
    (resume.keyword_normalize).
    """


def expand_keywords(
    keywords: Iterable[str],
    synonyms: dict[str, list[str]] | None = None,
) -> list[str]:
    """Expand keywords with synonyms (standalone function)."""
    matcher = KeywordMatcher()
    matcher.add_synonyms(synonyms or {})
    return matcher.expand_all(keywords)
