"""KeywordMatcher: Unified keyword matching and synonym handling.

This module is now a thin shim; implementation lives in:
  - resume.keyword_normalize: KeywordInfo, MatchResult, SynonymRegistry, normalize_text
  - resume.keyword_match: KeywordMatchEngine, keyword_match
"""
from __future__ import annotations

from resume.keyword_normalize import KeywordInfo, MatchResult, normalize_text  # noqa: F401
from resume.keyword_match import KeywordMatchEngine, keyword_match  # noqa: F401
from typing import Dict, Iterable, List, Optional


class KeywordMatcher(KeywordMatchEngine):
    """Unified keyword matching with synonym support and scoring.

    Re-exported for backwards compatibility. All logic lives in
    KeywordMatchEngine (resume.keyword_match) and SynonymRegistry
    (resume.keyword_normalize).
    """


def expand_keywords(
    keywords: Iterable[str],
    synonyms: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """Expand keywords with synonyms (standalone function)."""
    matcher = KeywordMatcher()
    matcher.add_synonyms(synonyms or {})
    return matcher.expand_all(keywords)
