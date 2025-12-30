"""KeywordMatcher: Unified keyword matching and synonym handling.

Consolidates keyword matching logic from:
- text_match.py (normalize, match, expand)
- aligner.py (canonical mapping, scoring)
- skills_filter.py (item matching)
- experience_filter.py (role scoring)

Usage:
    from resume.keyword_matcher import KeywordMatcher

    matcher = KeywordMatcher()
    matcher.add_synonyms({"Python": ["python3", "py"], "JavaScript": ["JS", "ES6"]})
    matcher.add_keywords(["Python", "JavaScript", "Go"], tier="required", weight=2)
    matcher.add_keywords(["Docker", "K8s"], tier="preferred")

    # Check if text matches any keyword
    if matcher.matches("Experience with Python and Docker"):
        print("Match found!")

    # Get all matching keywords with scores
    matches = matcher.find_matches("Built APIs with Python, deployed on K8s")
    # [{"keyword": "Python", "tier": "required", "weight": 2}, ...]

    # Score a text
    score = matcher.score("Python developer with Docker experience")
    # Returns weighted score
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


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


class KeywordMatcher:
    """Unified keyword matching with synonym support and scoring."""

    def __init__(self):
        self._synonyms: Dict[str, List[str]] = {}  # canonical -> [aliases]
        self._reverse_map: Dict[str, str] = {}  # alias.lower() -> canonical
        self._keywords: Dict[str, KeywordInfo] = {}  # canonical -> info

    # -------------------------------------------------------------------------
    # Synonym management
    # -------------------------------------------------------------------------

    def add_synonym(self, canonical: str, alias: str) -> "KeywordMatcher":
        """Add a single synonym mapping.

        Args:
            canonical: The canonical form of the keyword.
            alias: An alternative form that maps to the canonical.

        Returns:
            Self for chaining.
        """
        if canonical not in self._synonyms:
            self._synonyms[canonical] = []
        if alias not in self._synonyms[canonical]:
            self._synonyms[canonical].append(alias)
        self._reverse_map[alias.lower()] = canonical
        self._reverse_map[canonical.lower()] = canonical
        return self

    def add_synonyms(
        self,
        synonyms: Dict[str, List[str]],
    ) -> "KeywordMatcher":
        """Add multiple synonym mappings.

        Args:
            synonyms: Dict mapping canonical forms to lists of aliases.

        Returns:
            Self for chaining.
        """
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
        """Get the canonical form of a keyword.

        Args:
            keyword: A keyword or alias.

        Returns:
            The canonical form, or the original if not found.
        """
        return self._reverse_map.get(keyword.lower(), keyword)

    def get_aliases(self, canonical: str) -> List[str]:
        """Get all aliases for a canonical keyword.

        Args:
            canonical: The canonical keyword.

        Returns:
            List of aliases (not including the canonical itself).
        """
        return list(self._synonyms.get(canonical, []))

    def expand(self, keyword: str) -> List[str]:
        """Expand a keyword to include itself and all aliases.

        Args:
            keyword: A keyword (canonical or alias).

        Returns:
            List containing the canonical form and all aliases.
        """
        canon = self.canonicalize(keyword)
        return [canon] + self.get_aliases(canon)

    def expand_all(self, keywords: Iterable[str]) -> List[str]:
        """Expand multiple keywords to include all aliases.

        Args:
            keywords: Iterable of keywords.

        Returns:
            Deduplicated list of all keywords and their aliases.
        """
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

    # -------------------------------------------------------------------------
    # Keyword registration
    # -------------------------------------------------------------------------

    def add_keyword(
        self,
        keyword: str,
        tier: str = "preferred",
        weight: int = 1,
        category: Optional[str] = None,
    ) -> "KeywordMatcher":
        """Register a keyword with metadata.

        Args:
            keyword: The keyword to track.
            tier: Priority tier (required, preferred, nice).
            weight: Scoring weight.
            category: Optional category name.

        Returns:
            Self for chaining.
        """
        canon = self.canonicalize(keyword)
        self._keywords[canon] = KeywordInfo(
            keyword=canon,
            tier=tier,
            weight=weight,
            category=category,
        )
        return self

    def add_keywords(
        self,
        keywords: Iterable[str],
        tier: str = "preferred",
        weight: int = 1,
        category: Optional[str] = None,
    ) -> "KeywordMatcher":
        """Register multiple keywords with the same metadata.

        Args:
            keywords: Keywords to track.
            tier: Priority tier for all.
            weight: Scoring weight for all.
            category: Optional category for all.

        Returns:
            Self for chaining.
        """
        for kw in keywords or []:
            if kw:
                self.add_keyword(kw, tier=tier, weight=weight, category=category)
        return self

    def _add_keyword_item(
        self, item: Any, tier: str, category: Optional[str] = None
    ) -> None:
        """Add a single keyword item from a spec."""
        if isinstance(item, dict):
            kw = item.get("skill") or item.get("name") or ""
            if kw:
                self.add_keyword(kw, tier=tier, weight=int(item.get("weight", 1)), category=category)
        elif isinstance(item, str) and item:
            self.add_keyword(item, tier=tier, category=category)

    def add_keywords_from_spec(
        self,
        spec: Dict[str, Any],
    ) -> "KeywordMatcher":
        """Register keywords from a job/keyword spec.

        Handles spec format with required/preferred/nice tiers and categories.
        """
        for tier in ("required", "preferred", "nice"):
            for item in spec.get(tier, []) or []:
                self._add_keyword_item(item, tier)

        for cat_name, items in (spec.get("categories") or {}).items():
            for item in items or []:
                self._add_keyword_item(item, "preferred", category=cat_name)

        return self

    @property
    def keywords(self) -> List[str]:
        """Get all registered keywords (canonical forms)."""
        return list(self._keywords.keys())

    def get_keyword_info(self, keyword: str) -> Optional[KeywordInfo]:
        """Get metadata for a keyword.

        Args:
            keyword: A keyword (canonical or alias).

        Returns:
            KeywordInfo or None if not registered.
        """
        canon = self.canonicalize(keyword)
        return self._keywords.get(canon)

    # -------------------------------------------------------------------------
    # Text matching
    # -------------------------------------------------------------------------

    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for matching (lowercase, collapse whitespace)."""
        return re.sub(r"\s+", " ", text or "").strip().lower()

    def match_keyword(
        self,
        text: str,
        keyword: str,
        *,
        normalize: bool = True,
        word_boundary: bool = True,
    ) -> bool:
        """Check if a single keyword matches in text.

        Args:
            text: Text to search in.
            keyword: Keyword to find.
            normalize: Whether to normalize both text and keyword.
            word_boundary: Whether to require word boundaries.

        Returns:
            True if keyword found in text.
        """
        if not text or not keyword:
            return False

        t = self.normalize(text) if normalize else text.lower()
        k = self.normalize(keyword) if normalize else keyword.lower()

        if not k:
            return False

        if word_boundary and re.search(rf"\b{re.escape(k)}\b", t):
            return True
        return k in t

    def matches(
        self,
        text: str,
        *,
        expand_synonyms: bool = True,
    ) -> bool:
        """Check if text matches any registered keyword.

        Args:
            text: Text to search in.
            expand_synonyms: Whether to check aliases too.

        Returns:
            True if any keyword matches.
        """
        for canon in self._keywords:
            to_check = self.expand(canon) if expand_synonyms else [canon]
            if any(self.match_keyword(text, kw) for kw in to_check):
                return True
        return False

    def matches_any(
        self,
        text: str,
        keywords: Iterable[str],
        *,
        expand_synonyms: bool = True,
    ) -> bool:
        """Check if text matches any of the given keywords.

        Args:
            text: Text to search in.
            keywords: Keywords to check (don't need to be registered).
            expand_synonyms: Whether to expand each keyword with synonyms.

        Returns:
            True if any keyword matches.
        """
        for kw in keywords or []:
            if not kw:
                continue
            to_check = self.expand(kw) if expand_synonyms else [kw]
            if any(self.match_keyword(text, k) for k in to_check):
                return True
        return False

    def find_matches(
        self,
        text: str,
        *,
        expand_synonyms: bool = True,
    ) -> List[MatchResult]:
        """Find all registered keywords that match in text.

        Args:
            text: Text to search in.
            expand_synonyms: Whether to check aliases too.

        Returns:
            List of MatchResult for each matching keyword.
        """
        results: List[MatchResult] = []
        for canon, info in self._keywords.items():
            to_check = self.expand(canon) if expand_synonyms else [canon]
            if any(self.match_keyword(text, kw) for kw in to_check):
                results.append(MatchResult(
                    keyword=canon,
                    tier=info.tier,
                    weight=info.weight,
                    category=info.category,
                    count=1,
                    contexts=[text],
                ))
        return results

    def find_matching_keywords(
        self,
        text: str,
        keywords: Iterable[str],
        *,
        expand_synonyms: bool = True,
    ) -> List[str]:
        """Find which of the given keywords match in text.

        Args:
            text: Text to search in.
            keywords: Keywords to check.
            expand_synonyms: Whether to expand each keyword.

        Returns:
            List of matching keywords (canonical forms).
        """
        matched: List[str] = []
        for kw in keywords or []:
            if not kw:
                continue
            canon = self.canonicalize(kw)
            to_check = self.expand(kw) if expand_synonyms else [kw]
            if any(self.match_keyword(text, k) for k in to_check):
                if canon not in matched:
                    matched.append(canon)
        return matched

    # -------------------------------------------------------------------------
    # Scoring
    # -------------------------------------------------------------------------

    def score(
        self,
        text: str,
        *,
        expand_synonyms: bool = True,
    ) -> int:
        """Calculate weighted score for text based on keyword matches.

        Args:
            text: Text to score.
            expand_synonyms: Whether to check aliases.

        Returns:
            Sum of weights for all matching keywords.
        """
        total = 0
        for canon, info in self._keywords.items():
            to_check = self.expand(canon) if expand_synonyms else [canon]
            if any(self.match_keyword(text, kw) for kw in to_check):
                total += info.weight
        return total

    def score_texts(
        self,
        texts: Iterable[str],
        *,
        expand_synonyms: bool = True,
    ) -> int:
        """Calculate total score across multiple texts.

        Counts each keyword only once across all texts.

        Args:
            texts: Texts to score.
            expand_synonyms: Whether to check aliases.

        Returns:
            Sum of weights for all matching keywords.
        """
        matched: Set[str] = set()
        for text in texts or []:
            for canon in self._keywords:
                if canon in matched:
                    continue
                to_check = self.expand(canon) if expand_synonyms else [canon]
                if any(self.match_keyword(text, kw) for kw in to_check):
                    matched.add(canon)

        return sum(self._keywords[k].weight for k in matched)

    # -------------------------------------------------------------------------
    # Bulk operations
    # -------------------------------------------------------------------------

    def collect_matches_from_candidate(
        self,
        candidate: Dict[str, Any],
    ) -> Dict[str, MatchResult]:
        """Collect all keyword matches from a candidate profile.

        Searches: summary, skills, experience (title, company, bullets).

        Args:
            candidate: Candidate data dict.

        Returns:
            Dict mapping canonical keyword to MatchResult with counts.
        """
        results: Dict[str, MatchResult] = {}

        def record_match(canon: str, context: str, scope: str):
            if canon not in results:
                info = self._keywords.get(canon, KeywordInfo(keyword=canon))
                results[canon] = MatchResult(
                    keyword=canon,
                    tier=info.tier,
                    weight=info.weight,
                    category=info.category,
                    count=0,
                    contexts=[],
                )
            results[canon].count += 1
            results[canon].contexts.append(f"[{scope}] {context[:50]}")

        # Summary
        summary = str(candidate.get("summary") or "")
        if summary:
            for canon in self._keywords:
                if any(self.match_keyword(summary, kw) for kw in self.expand(canon)):
                    record_match(canon, summary, "summary")

        # Skills
        for skill in candidate.get("skills") or []:
            text = str(skill)
            for canon in self._keywords:
                if any(self.match_keyword(text, kw) for kw in self.expand(canon)):
                    record_match(canon, text, "skills")

        # Experience
        for i, exp in enumerate(candidate.get("experience") or []):
            # Title + company
            title_text = f"{exp.get('title', '')} {exp.get('company', '')}".strip()
            if title_text:
                for canon in self._keywords:
                    if any(self.match_keyword(title_text, kw) for kw in self.expand(canon)):
                        record_match(canon, title_text, f"exp[{i}].title")

            # Bullets
            for bullet in exp.get("bullets") or []:
                text = str(bullet)
                for canon in self._keywords:
                    if any(self.match_keyword(text, kw) for kw in self.expand(canon)):
                        record_match(canon, text, f"exp[{i}].bullet")

        return results

    def score_experience_roles(
        self,
        candidate: Dict[str, Any],
    ) -> List[Tuple[int, int]]:
        """Score each experience role by keyword matches.

        Args:
            candidate: Candidate data dict.

        Returns:
            List of (role_index, score) tuples, sorted by score descending.
        """
        scores: List[Tuple[int, int]] = []

        for i, exp in enumerate(candidate.get("experience") or []):
            role_score = 0

            # Title + company
            title_text = f"{exp.get('title', '')} {exp.get('company', '')}".strip()
            if title_text:
                for canon, info in self._keywords.items():
                    if any(self.match_keyword(title_text, kw) for kw in self.expand(canon)):
                        role_score += info.weight

            # Bullets (count as 1 each regardless of weight)
            for bullet in exp.get("bullets") or []:
                text = str(bullet)
                for canon in self._keywords:
                    if any(self.match_keyword(text, kw) for kw in self.expand(canon)):
                        role_score += 1
                        break  # Only count once per bullet

            scores.append((i, role_score))

        scores.sort(key=lambda t: t[1], reverse=True)
        return scores


# -----------------------------------------------------------------------------
# Convenience functions (backward compatible with text_match.py)
# -----------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """Normalize text for matching."""
    return KeywordMatcher.normalize(text)


def keyword_match(
    text: str,
    keyword: str,
    *,
    normalize: bool = False,
    word_boundary: bool = True,
) -> bool:
    """Check if keyword matches in text (standalone function)."""
    matcher = KeywordMatcher()
    return matcher.match_keyword(text, keyword, normalize=normalize, word_boundary=word_boundary)


def expand_keywords(
    keywords: Iterable[str],
    synonyms: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """Expand keywords with synonyms (standalone function)."""
    matcher = KeywordMatcher()
    matcher.add_synonyms(synonyms or {})
    return matcher.expand_all(keywords)
