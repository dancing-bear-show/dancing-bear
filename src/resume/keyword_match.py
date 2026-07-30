"""Keyword registration, text matching, and scoring utilities.

Provides the matching and scoring logic used by KeywordMatcher:
  - add_keyword / add_keywords / add_keywords_from_spec: registration
  - match_keyword / matches / matches_any / find_matches / find_matching_keywords: matching
  - score / score_texts: scoring
  - collect_matches_from_candidate / score_experience_roles: bulk operations
  - keyword_match: standalone match helper (compat)
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from resume.keyword_normalize import KeywordInfo, MatchResult, SynonymRegistry


def keyword_match(
    text: str,
    keyword: str,
    *,
    normalize: bool = False,
    word_boundary: bool = True,
) -> bool:
    """Check if keyword matches in text (standalone function)."""
    from resume.keyword_matcher import KeywordMatcher
    matcher = KeywordMatcher()
    return matcher.match_keyword(text, keyword, normalize=normalize, word_boundary=word_boundary)


class KeywordMatchEngine(SynonymRegistry):
    """Keyword registration, text matching, and scoring built on SynonymRegistry."""

    def __init__(self) -> None:
        super().__init__()
        self._keywords: Dict[str, KeywordInfo] = {}  # canonical -> info

    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for matching (lowercase, collapse whitespace)."""
        return re.sub(r"\s+", " ", text or "").strip().lower()

    def add_keyword(
        self,
        keyword: str,
        tier: str = "preferred",
        weight: int = 1,
        category: Optional[str] = None,
    ) -> "KeywordMatchEngine":
        """Register a keyword with metadata."""
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
    ) -> "KeywordMatchEngine":
        """Register multiple keywords with the same metadata."""
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
    ) -> "KeywordMatchEngine":
        """Register keywords from a job/keyword spec."""
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
        """Get metadata for a keyword."""
        canon = self.canonicalize(keyword)
        return self._keywords.get(canon)

    def match_keyword(
        self,
        text: str,
        keyword: str,
        *,
        normalize: bool = True,
        word_boundary: bool = True,
    ) -> bool:
        """Check if a single keyword matches in text."""
        if not text or not keyword:
            return False
        t = self.normalize(text) if normalize else text.lower()
        k = self.normalize(keyword) if normalize else keyword.lower()
        if not k:
            return False
        if word_boundary and re.search(rf"\b{re.escape(k)}\b", t):
            return True
        return k in t

    def matches(self, text: str, *, expand_synonyms: bool = True) -> bool:
        """Check if text matches any registered keyword."""
        for canon in self._keywords:
            to_check = self.expand(canon) if expand_synonyms else [canon]
            if any(self.match_keyword(text, kw) for kw in to_check):
                return True
        return False

    def matches_any(
        self, text: str, keywords: Iterable[str], *, expand_synonyms: bool = True
    ) -> bool:
        """Check if text matches any of the given keywords."""
        for kw in keywords or []:
            if not kw:
                continue
            to_check = self.expand(kw) if expand_synonyms else [kw]
            if any(self.match_keyword(text, k) for k in to_check):
                return True
        return False

    def find_matches(self, text: str, *, expand_synonyms: bool = True) -> List[MatchResult]:
        """Find all registered keywords that match in text."""
        results: List[MatchResult] = []
        for canon, info in self._keywords.items():
            to_check = self.expand(canon) if expand_synonyms else [canon]
            if any(self.match_keyword(text, kw) for kw in to_check):
                results.append(MatchResult(
                    keyword=canon, tier=info.tier, weight=info.weight,
                    category=info.category, count=1, contexts=[text],
                ))
        return results

    def find_matching_keywords(
        self, text: str, keywords: Iterable[str], *, expand_synonyms: bool = True
    ) -> List[str]:
        """Find which of the given keywords match in text."""
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

    def score(self, text: str, *, expand_synonyms: bool = True) -> int:
        """Calculate weighted score for text based on keyword matches."""
        total = 0
        for canon, info in self._keywords.items():
            to_check = self.expand(canon) if expand_synonyms else [canon]
            if any(self.match_keyword(text, kw) for kw in to_check):
                total += info.weight
        return total

    def score_texts(self, texts: Iterable[str], *, expand_synonyms: bool = True) -> int:
        """Calculate total score across multiple texts (each keyword counted once)."""
        matched: Set[str] = set()
        for text in texts or []:
            for canon in self._keywords:
                if canon in matched:
                    continue
                to_check = self.expand(canon) if expand_synonyms else [canon]
                if any(self.match_keyword(text, kw) for kw in to_check):
                    matched.add(canon)
        return sum(self._keywords[k].weight for k in matched)

    def _make_match_result(self, canon: str) -> MatchResult:
        info = self._keywords.get(canon, KeywordInfo(keyword=canon))
        return MatchResult(
            keyword=canon, tier=info.tier, weight=info.weight,
            category=info.category, count=0, contexts=[],
        )

    def _record_match(
        self, results: Dict[str, MatchResult], canon: str, context: str, scope: str
    ) -> None:
        if canon not in results:
            results[canon] = self._make_match_result(canon)
        results[canon].count += 1
        results[canon].contexts.append(f"[{scope}] {context[:50]}")

    def _match_text_against_keywords(
        self, results: Dict[str, MatchResult], text: str, scope: str
    ) -> None:
        for canon in self._keywords:
            if any(self.match_keyword(text, kw) for kw in self.expand(canon)):
                self._record_match(results, canon, text, scope)

    def _collect_exp_matches(
        self, results: Dict[str, MatchResult], candidate: Dict[str, Any]
    ) -> None:
        for i, exp in enumerate(candidate.get("experience") or []):
            title_text = f"{exp.get('title', '')} {exp.get('company', '')}".strip()
            if title_text:
                self._match_text_against_keywords(results, title_text, f"exp[{i}].title")
            for bullet in exp.get("bullets") or []:
                self._match_text_against_keywords(results, str(bullet), f"exp[{i}].bullet")

    def collect_matches_from_candidate(self, candidate: Dict[str, Any]) -> Dict[str, MatchResult]:
        """Collect all keyword matches from a candidate profile."""
        results: Dict[str, MatchResult] = {}
        summary = str(candidate.get("summary") or "")
        if summary:
            self._match_text_against_keywords(results, summary, "summary")
        for skill in candidate.get("skills") or []:
            self._match_text_against_keywords(results, str(skill), "skills")
        self._collect_exp_matches(results, candidate)
        return results

    def _score_role(self, exp: Dict[str, Any]) -> int:
        role_score = 0
        title_text = f"{exp.get('title', '')} {exp.get('company', '')}".strip()
        if title_text:
            for canon, info in self._keywords.items():
                if any(self.match_keyword(title_text, kw) for kw in self.expand(canon)):
                    role_score += info.weight
        for bullet in exp.get("bullets") or []:
            text = str(bullet)
            for canon in self._keywords:
                if any(self.match_keyword(text, kw) for kw in self.expand(canon)):
                    role_score += 1
                    break
        return role_score

    def score_experience_roles(self, candidate: Dict[str, Any]) -> List[Tuple[int, int]]:
        """Score each experience role by keyword matches."""
        scores = [
            (i, self._score_role(exp))
            for i, exp in enumerate(candidate.get("experience") or [])
        ]
        scores.sort(key=lambda t: t[1], reverse=True)
        return scores
