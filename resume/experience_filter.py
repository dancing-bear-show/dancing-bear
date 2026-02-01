"""Experience filtering by keyword matching.

Uses KeywordMatcher for consistent matching behavior across the codebase.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .keyword_matcher import KeywordMatcher


def _score_role_header(role: Dict[str, Any], matcher: KeywordMatcher, keywords: List[str]) -> int:
    """Score role by keyword matches in title and company."""
    title_company = f"{role.get('title', '')} {role.get('company', '')}".strip()
    score = 0
    for kw in keywords:
        if matcher.match_keyword(title_company, kw):
            score += 1
    return score


def _filter_bullets(bullets: List[Any], matcher: KeywordMatcher, keywords: List[str]) -> List[str]:
    """Filter bullets by keyword matches, with fallback to first bullet."""
    keep_bullets: List[str] = []
    for b in bullets:
        text = str(b)
        if matcher.matches_any(text, keywords, expand_synonyms=False):
            keep_bullets.append(text)

    # Fallback: keep first bullet if none matched
    if not keep_bullets and bullets:
        keep_bullets = [str(bullets[0])]

    return keep_bullets


def _score_and_filter_role(
    role: Dict[str, Any], matcher: KeywordMatcher, keywords: List[str]
) -> Tuple[int, Dict[str, Any]]:
    """Score a role and filter its bullets by keywords."""
    header_score = _score_role_header(role, matcher, keywords)
    bullets = role.get("bullets") or []
    keep_bullets = _filter_bullets(bullets, matcher, keywords)
    total_score = header_score + len(keep_bullets)
    return (total_score, {**role, "bullets": keep_bullets})


def _apply_limits(
    scored_roles: List[Tuple[int, Dict[str, Any]]],
    max_roles: Optional[int],
    max_bullets_per_role: Optional[int],
) -> List[Dict[str, Any]]:
    """Apply role and bullet limits to scored roles."""
    out_roles: List[Dict[str, Any]] = []
    limit = max_roles if max_roles is not None else len(scored_roles)
    for _, role in scored_roles[:limit]:
        if max_bullets_per_role is not None and role.get("bullets"):
            role = {**role, "bullets": role["bullets"][:max_bullets_per_role]}
        out_roles.append(role)
    return out_roles


def filter_experience_by_keywords(
    data: Dict[str, Any],
    matched_keywords: Iterable[str],
    synonyms: Optional[Dict[str, List[str]]] = None,
    max_roles: Optional[int] = None,
    max_bullets_per_role: Optional[int] = None,
    min_score: int = 1,
) -> Dict[str, Any]:
    """Filter and compress experience entries based on matched keywords.

    - Keeps roles scored by occurrences of keywords in title/company/bullets.
    - Keeps only bullets that contain matched keywords (fallback to first bullet if none).
    - Respects max_roles and max_bullets_per_role if provided.
    - Drops roles with score < min_score.

    Args:
        data: Candidate data dict.
        matched_keywords: Keywords to match against.
        synonyms: Optional synonym mapping.
        max_roles: Maximum roles to keep.
        max_bullets_per_role: Maximum bullets per role.
        min_score: Minimum score to keep a role.

    Returns:
        Filtered data with scored and trimmed experience.
    """
    # Build matcher with expanded keywords
    matcher = KeywordMatcher()
    matcher.add_synonyms(synonyms or {})
    keywords = list(matched_keywords or [])
    expanded = matcher.expand_all(keywords)

    experiences = list(data.get("experience") or [])
    if not experiences or not expanded:
        return dict(data)

    # Score and filter each role
    scored = [_score_and_filter_role(e, matcher, expanded) for e in experiences]

    # Filter by min_score and sort by score descending
    filtered = [(s, e) for s, e in scored if s >= min_score]
    filtered.sort(key=lambda t: t[0], reverse=True)

    # Apply limits
    out_roles = _apply_limits(filtered, max_roles, max_bullets_per_role)

    out = dict(data)
    out["experience"] = out_roles
    return out
