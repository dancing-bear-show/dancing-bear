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
from typing import Any, Iterable

from resume.keyword_normalize import (
    KeywordInfo,
    KeywordMatchResult,
    SynonymRegistry,
    item_text,
)


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


def _summary_text(summary: Any) -> str:
    """Flatten a summary into matchable prose.

    Real data stores the summary as a list of ``{text, priority}`` items, so a
    bare ``str()`` produced the list's repr and matched keywords against that
    instead of the prose.
    """
    if isinstance(summary, list):
        return " ".join(t for t in (item_text(x) for x in summary) if t)
    return item_text(summary)


class KeywordMatchEngine(SynonymRegistry):
    """Keyword registration, text matching, and scoring built on SynonymRegistry."""

    def __init__(self) -> None:
        super().__init__()
        self._keywords: dict[str, KeywordInfo] = {}  # canonical -> info

    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for matching (lowercase, collapse whitespace)."""
        return re.sub(r"\s+", " ", text or "").strip().lower()

    def add_keyword(
        self,
        keyword: str,
        tier: str = "preferred",
        weight: int = 1,
        category: str | None = None,
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
        category: str | None = None,
    ) -> "KeywordMatchEngine":
        """Register multiple keywords with the same metadata."""
        for kw in keywords or []:
            if kw:
                self.add_keyword(kw, tier=tier, weight=weight, category=category)
        return self

    def _add_keyword_item(
        self, item: Any, tier: str, category: str | None = None
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
        spec: dict[str, Any],
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
    def keywords(self) -> list[str]:
        """Get all registered keywords (canonical forms)."""
        return list(self._keywords.keys())

    def get_keyword_info(self, keyword: str) -> KeywordInfo | None:
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

    def _keyword_hits(self, text: str, keyword: str, *, expand_synonyms: bool) -> bool:
        """Check if a keyword (or any of its synonym expansions) matches text."""
        to_check = self.expand(keyword) if expand_synonyms else [keyword]
        return any(self.match_keyword(text, kw) for kw in to_check)

    def matches(self, text: str, *, expand_synonyms: bool = True) -> bool:
        """Check if text matches any registered keyword."""
        return any(
            self._keyword_hits(text, canon, expand_synonyms=expand_synonyms)
            for canon in self._keywords
        )

    def matches_any(
        self, text: str, keywords: Iterable[str], *, expand_synonyms: bool = True
    ) -> bool:
        """Check if text matches any of the given keywords."""
        return any(
            self._keyword_hits(text, kw, expand_synonyms=expand_synonyms)
            for kw in keywords or []
            if kw
        )

    def find_matches(self, text: str, *, expand_synonyms: bool = True) -> list[KeywordMatchResult]:
        """Find all registered keywords that match in text."""
        results: list[KeywordMatchResult] = []
        for canon, info in self._keywords.items():
            if self._keyword_hits(text, canon, expand_synonyms=expand_synonyms):
                results.append(KeywordMatchResult(
                    keyword=canon, tier=info.tier, weight=info.weight,
                    category=info.category, count=1, contexts=[text],
                ))
        return results

    def find_matching_keywords(
        self, text: str, keywords: Iterable[str], *, expand_synonyms: bool = True
    ) -> list[str]:
        """Find which of the given keywords match in text."""
        matched: list[str] = []
        for kw in keywords or []:
            if not kw:
                continue
            canon = self.canonicalize(kw)
            if self._keyword_hits(text, kw, expand_synonyms=expand_synonyms) and canon not in matched:
                matched.append(canon)
        return matched

    def score(self, text: str, *, expand_synonyms: bool = True) -> int:
        """Calculate weighted score for text based on keyword matches."""
        return sum(
            info.weight
            for canon, info in self._keywords.items()
            if self._keyword_hits(text, canon, expand_synonyms=expand_synonyms)
        )

    def score_texts(self, texts: Iterable[str], *, expand_synonyms: bool = True) -> int:
        """Calculate total score across multiple texts (each keyword counted once)."""
        matched: set[str] = set()
        for text in texts or []:
            for canon in self._keywords:
                if canon in matched:
                    continue
                if self._keyword_hits(text, canon, expand_synonyms=expand_synonyms):
                    matched.add(canon)
        return sum(self._keywords[k].weight for k in matched)

    def _make_match_result(self, canon: str) -> KeywordMatchResult:
        info = self._keywords.get(canon, KeywordInfo(keyword=canon))
        return KeywordMatchResult(
            keyword=canon, tier=info.tier, weight=info.weight,
            category=info.category, count=0, contexts=[],
        )

    def _record_match(
        self, results: dict[str, KeywordMatchResult], canon: str, context: str, scope: str
    ) -> None:
        if canon not in results:
            results[canon] = self._make_match_result(canon)
        results[canon].count += 1
        results[canon].contexts.append(f"[{scope}] {context[:50]}")

    def _match_text_against_keywords(
        self, results: dict[str, KeywordMatchResult], text: str, scope: str
    ) -> None:
        for canon in self._keywords:
            if self._keyword_hits(text, canon, expand_synonyms=True):
                self._record_match(results, canon, text, scope)

    def _collect_exp_matches(
        self, results: dict[str, KeywordMatchResult], candidate: dict[str, Any]
    ) -> None:
        for i, exp in enumerate(candidate.get("experience") or []):
            title_text = f"{exp.get('title', '')} {exp.get('company', '')}".strip()
            if title_text:
                self._match_text_against_keywords(results, title_text, f"exp[{i}].title")
            for bullet in exp.get("bullets") or []:
                self._match_text_against_keywords(
                    results, item_text(bullet), f"exp[{i}].bullet"
                )

    def collect_matches_from_candidate(self, candidate: dict[str, Any]) -> dict[str, KeywordMatchResult]:
        """Collect all keyword matches from a candidate profile."""
        results: dict[str, KeywordMatchResult] = {}
        summary = _summary_text(candidate.get("summary"))
        if summary:
            self._match_text_against_keywords(results, summary, "summary")
        for skill in candidate.get("skills") or []:
            self._match_text_against_keywords(results, str(skill), "skills")
        self._collect_exp_matches(results, candidate)
        return results

    def _score_title(self, title_text: str) -> int:
        """Sum weights of every keyword matching the title/company text."""
        if not title_text:
            return 0
        return sum(
            info.weight
            for canon, info in self._keywords.items()
            if self._keyword_hits(title_text, canon, expand_synonyms=True)
        )

    def _score_role(self, exp: dict[str, Any]) -> int:
        title_text = f"{exp.get('title', '')} {exp.get('company', '')}".strip()
        role_score = self._score_title(title_text)
        for bullet in exp.get("bullets") or []:
            text = item_text(bullet)
            if any(self._keyword_hits(text, canon, expand_synonyms=True) for canon in self._keywords):
                role_score += 1
        return role_score

    def score_experience_roles(self, candidate: dict[str, Any]) -> list[tuple[int, int]]:
        """Score each experience role by keyword matches."""
        scores = [
            (i, self._score_role(exp))
            for i, exp in enumerate(candidate.get("experience") or [])
        ]
        scores.sort(key=lambda t: t[1], reverse=True)
        return scores
