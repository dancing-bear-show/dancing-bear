"""Keyword synonym management and normalization utilities.

Provides synonym registry and data classes used by KeywordMatcher:
  - KeywordInfo, KeywordMatchResult: data containers
  - SynonymRegistry: synonym management helpers
  - normalize_text: standalone text normalization helper (compat)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class KeywordInfo:
    """Metadata for a tracked keyword."""
    keyword: str
    tier: str = "preferred"  # required, preferred, nice
    weight: int = 1
    category: str | None = None


@dataclass
class KeywordMatchResult:
    """Result of a keyword match."""
    keyword: str
    tier: str
    weight: int
    category: str | None
    count: int = 1
    contexts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
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
        self._synonyms: dict[str, list[str]] = {}  # canonical -> [aliases]
        self._reverse_map: dict[str, str] = {}  # alias.lower() -> canonical

    def add_synonym(self, canonical: str, alias: str) -> "SynonymRegistry":
        """Add a single synonym mapping."""
        if canonical not in self._synonyms:
            self._synonyms[canonical] = []
        if alias not in self._synonyms[canonical]:
            self._synonyms[canonical].append(alias)
        self._reverse_map[alias.lower()] = canonical
        self._reverse_map[canonical.lower()] = canonical
        return self

    def add_synonyms(self, synonyms: dict[str, list[str]]) -> "SynonymRegistry":
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

    def get_aliases(self, canonical: str) -> list[str]:
        """Get all aliases for a canonical keyword."""
        return list(self._synonyms.get(canonical, []))

    def expand(self, keyword: str) -> list[str]:
        """Expand a keyword to include itself and all aliases."""
        canon = self.canonicalize(keyword)
        return [canon] + self.get_aliases(canon)

    def expand_all(self, keywords: Iterable[str]) -> list[str]:
        """Expand multiple keywords to include all aliases (deduplicated)."""
        seen: set[str] = set()
        result: list[str] = []
        for kw in keywords or []:
            if not kw:
                continue
            for expanded in self.expand(kw):
                key = expanded.lower()
                if key not in seen:
                    seen.add(key)
                    result.append(expanded)
        return result


def item_text(item: Any) -> str:
    """Return the prose of a resume list item, whether str or priority dict.

    Real candidate data stores summary bullets, experience bullets, skills, and
    interests as ``{"text": ..., "priority": 0.9}`` so ``--min-priority`` can
    filter them. A bare ``str(item)`` on that shape yields the dict's Python
    repr — braces, quotes, and the priority number included — so any text
    matching done on the result silently operates on punctuation-mangled
    pseudo-prose instead of the bullet.

    Accepts the ``text``/``line``/``name`` key spellings that the DOCX
    renderers and aligner already tolerate, so one helper covers every
    producer of this shape.
    """
    if isinstance(item, dict):
        return str(item.get("text") or item.get("line") or item.get("name") or "")
    return str(item or "")
