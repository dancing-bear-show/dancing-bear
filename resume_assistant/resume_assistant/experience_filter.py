"""Experience filtering by keyword matching.

Uses KeywordMatcher for consistent matching behavior across the codebase.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .keyword_matcher import KeywordMatcher


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

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for e in experiences:
        score = 0

        # Score title + company
        title_company = f"{e.get('title', '')} {e.get('company', '')}".strip()
        for kw in expanded:
            if matcher.match_keyword(title_company, kw):
                score += 1

        # Filter and score bullets
        bullets = e.get("bullets") or []
        keep_bullets: List[str] = []
        for b in bullets:
            text = str(b)
            if matcher.matches_any(text, expanded, expand_synonyms=False):
                keep_bullets.append(text)

        # Fallback: keep first bullet if none matched
        if not keep_bullets and bullets:
            keep_bullets = [str(bullets[0])]

        scored.append((score + len(keep_bullets), {**e, "bullets": keep_bullets}))

    # Filter by min_score
    filtered = [(s, e) for s, e in scored if s >= min_score]

    # Sort by score desc
    filtered.sort(key=lambda t: t[0], reverse=True)

    # Apply max_roles and max bullets per role
    out_roles: List[Dict[str, Any]] = []
    for _, e in filtered[: (max_roles or len(filtered))]:
        if max_bullets_per_role is not None and e.get("bullets"):
            e = {**e, "bullets": e["bullets"][:max_bullets_per_role]}
        out_roles.append(e)

    out = dict(data)
    out["experience"] = out_roles
    return out
