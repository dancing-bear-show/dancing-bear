"""Experience filtering by keyword matching.

Uses KeywordMatcher for consistent matching behavior across the codebase.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .keyword_matcher import KeywordMatcher
from .render_config import ExperienceFilterConfig


def _score_experience(e: Dict[str, Any], matcher: KeywordMatcher, expanded: List[str]) -> Tuple[int, Dict[str, Any]]:
    """Score a single experience entry against expanded keywords."""
    score = 0
    title_company = f"{e.get('title', '')} {e.get('company', '')}".strip()
    for kw in expanded:
        if matcher.match_keyword(title_company, kw):
            score += 1
    bullets = e.get("bullets") or []
    keep_bullets = [str(b) for b in bullets if matcher.matches_any(str(b), expanded, expand_synonyms=False)]
    if not keep_bullets and bullets:
        keep_bullets = [str(bullets[0])]
    return score + len(keep_bullets), {**e, "bullets": keep_bullets}


def _score_experiences(
    experiences: List[Dict[str, Any]],
    matcher: KeywordMatcher,
    expanded: List[str],
) -> List[Tuple[int, Dict[str, Any]]]:
    """Score all experience entries against expanded keywords."""
    return [_score_experience(e, matcher, expanded) for e in experiences]


def _trim_roles(
    filtered: List[Tuple[int, Dict[str, Any]]],
    max_roles: Optional[int],
    max_bullets_per_role: Optional[int],
) -> List[Dict[str, Any]]:
    """Apply max_roles and max_bullets_per_role limits."""
    out_roles: List[Dict[str, Any]] = []
    for _, e in filtered[: (max_roles or len(filtered))]:
        if max_bullets_per_role is not None and e.get("bullets"):
            e = {**e, "bullets": e["bullets"][:max_bullets_per_role]}
        out_roles.append(e)
    return out_roles


def filter_experience_by_keywords(
    data: Dict[str, Any],
    matched_keywords: Iterable[str],
    synonyms: Optional[Dict[str, List[str]]] = None,
    filter_cfg: Optional[ExperienceFilterConfig] = None,
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
        filter_cfg: Filtering limits (max_roles, max_bullets_per_role, min_score).

    Returns:
        Filtered data with scored and trimmed experience.
    """
    cfg = filter_cfg or ExperienceFilterConfig()

    # Build matcher with expanded keywords
    matcher = KeywordMatcher()
    matcher.add_synonyms(synonyms or {})
    keywords = list(matched_keywords or [])
    expanded = matcher.expand_all(keywords)

    experiences = list(data.get("experience") or [])
    if not experiences or not expanded:
        return dict(data)

    scored = _score_experiences(experiences, matcher, expanded)
    filtered = sorted(
        [(s, e) for s, e in scored if s >= cfg.min_score],
        key=lambda t: t[0],
        reverse=True,
    )
    out_roles = _trim_roles(filtered, cfg.max_roles, cfg.max_bullets_per_role)

    out = dict(data)
    out["experience"] = out_roles
    return out
