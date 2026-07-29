"""Keyword synonym management and normalization utilities.

Provides synonym registry and data classes used by KeywordMatcher:
  - KeywordInfo, MatchResult: data containers
  - SynonymRegistry: synonym management helpers
  - normalize_text: standalone text normalization helper (compat)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set


@dataclass
class KeywordInfo:
    """Metadata for a tracked keyword."""
    keyword: str
    tier: str = "preferred"  # required, preferred, nice
    weight: int = 1
    category: Optional[str] = None


@dataclass
class MatchResult:
    """Result of a keyword match."""
    keyword: str
    tier: str
    weight: int
    category: Optional[str]
    count: int = 1
    contexts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill": self.keyword,
            "tier": self.tier,
            "weight": self.weight,
            "category": self.category,
            "count": self.count,
        }


def normalize_text(text: str) -> str:
    """Normalize text for matching (lowercase, collapse whitespace)."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


class SynonymRegistry:
    """Manages synonym mappings: canonical -> [aliases] and alias -> canonical."""

    def __init__(self) -> None:
        self._synonyms: Dict[str, List[str]] = {}  # canonical -> [aliases]
        self._reverse_map: Dict[str, str] = {}  # alias.lower() -> canonical

    def add_synonym(self, canonical: str, alias: str) -> "SynonymRegistry":
        """Add a single synonym mapping."""
        if canonical not in self._synonyms:
            self._synonyms[canonical] = []
        if alias not in self._synonyms[canonical]:
            self._synonyms[canonical].append(alias)
        self._reverse_map[alias.lower()] = canonical
        self._reverse_map[canonical.lower()] = canonical
        return self

    def add_synonyms(self, synonyms: Dict[str, List[str]]) -> "SynonymRegistry":
        """Add multiple synonym mappings."""
        for canonical, aliases in (synonyms or {}).items():
            self._reverse_map[canonical.lower()] = canonical
            if canonical not in self._synonyms:
                self._synonyms[canonical] = []
            for alias in aliases or []:
                if alias and alias not in self._synonyms[canonical]:
                    self._synonyms[canonical].append(alias)
                    self._reverse_map[alias.lower()] = canonical
        return self

    def canonicalize(self, keyword: str) -> str:
        """Get the canonical form of a keyword."""
        return self._reverse_map.get(keyword.lower(), keyword)

    def get_aliases(self, canonical: str) -> List[str]:
        """Get all aliases for a canonical keyword."""
        return list(self._synonyms.get(canonical, []))

    def expand(self, keyword: str) -> List[str]:
        """Expand a keyword to include itself and all aliases."""
        canon = self.canonicalize(keyword)
        return [canon] + self.get_aliases(canon)

    def expand_all(self, keywords: Iterable[str]) -> List[str]:
        """Expand multiple keywords to include all aliases (deduplicated)."""
        seen: Set[str] = set()
        result: List[str] = []
        for kw in keywords or []:
            if not kw:
                continue
            for expanded in self.expand(kw):
                key = expanded.lower()
                if key not in seen:
                    seen.add(key)
                    result.append(expanded)
        return result
