"""Text matching utilities for keyword search.

This module provides backward-compatible functions that delegate to
KeywordMatcher for the actual implementation.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

# Re-export from keyword_matcher for backward compatibility
from .keyword_matcher import (
    normalize_text,
    keyword_match,
    expand_keywords,
    KeywordMatcher,
)
