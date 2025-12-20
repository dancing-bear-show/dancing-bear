from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .text_match import expand_keywords, keyword_match


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
    """
    kws: List[str] = expand_keywords(matched_keywords or [], synonyms=synonyms)

    experiences = list(data.get("experience") or [])
    if not experiences or not kws:
        return dict(data)

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for idx, e in enumerate(experiences):
        score = 0
        title_company = " ".join([e.get("title") or "", e.get("company") or ""]).strip()
        for kw in kws:
            if keyword_match(title_company, kw):
                score += 1
        bullets = e.get("bullets") or []
        keep_bullets: List[str] = []
        for b in bullets:
            if any(keyword_match(str(b), kw) for kw in kws):
                keep_bullets.append(str(b))
        # Fallback keep first bullet if none matched
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
