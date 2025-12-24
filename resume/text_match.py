"""Text matching utilities for keyword search.

This module provides backward-compatible functions that delegate to
KeywordMatcher for the actual implementation.
"""
from __future__ import annotations


# Re-export from keyword_matcher for backward compatibility
from .keyword_matcher import (  # noqa: F401
    normalize_text,
    keyword_match,
    expand_keywords,
    KeywordMatcher,
)

__all__ = ["normalize_text", "keyword_match", "expand_keywords", "KeywordMatcher"]
