"""Candidate-to-job alignment using KeywordMatcher.

Matches candidate profile against job requirements and produces alignment reports.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .keyword_matcher import KeywordMatcher


def _find_missing_required(
    keyword_spec: Dict[str, Any],
    matcher: KeywordMatcher,
    matched_set: set,
) -> List[str]:
    """Find required keywords not present in matched_set."""
    missing = []
    for item in keyword_spec.get("required", []):
        kw = item.get("skill") or item.get("name") or ""
        if kw:
            canon = matcher.canonicalize(kw)
            if canon not in matched_set:
                missing.append(canon)
    return missing


def _missing_from_items(
    items: List[Any],
    matcher: KeywordMatcher,
    matched_set: set,
) -> List[str]:
    """Find canonical keywords from items not present in matched_set."""
    missing = []
    for item in items or []:
        kw = ((item.get("skill") or item.get("name") or "") if isinstance(item, dict) else str(item))
        if kw:
            canon = matcher.canonicalize(kw)
            if canon not in matched_set:
                missing.append(canon)
    return missing


def _find_missing_by_category(
    keyword_spec: Dict[str, Any],
    matcher: KeywordMatcher,
    matched_set: set,
) -> Dict[str, List[str]]:
    """Find keywords missing from each category."""
    return {
        cat_name: _missing_from_items(items, matcher, matched_set)
        for cat_name, items in (keyword_spec.get("categories") or {}).items()
    }


def align_candidate_to_job(
    candidate: Dict[str, Any],
    keyword_spec: Dict[str, Any],
    synonyms: Dict[str, List[str]] | None = None,
) -> Dict[str, Any]:
    """Align a candidate profile against a job keyword specification.

    Args:
        candidate: Candidate data with summary, skills, experience.
        keyword_spec: Job spec with required/preferred/nice tiers and categories.
        synonyms: Optional synonym mapping.

    Returns:
        Alignment report with matched_keywords, missing_required,
        missing_by_category, and experience_scores.
    """
    # Build matcher from spec
    matcher = KeywordMatcher()
    matcher.add_synonyms(synonyms or {})
    matcher.add_keywords_from_spec(keyword_spec)

    # Collect matches from candidate
    matches = matcher.collect_matches_from_candidate(candidate)

    # Build matched keywords list with full metadata
    matched_keywords = []
    for kw, result in matches.items():
        matched_keywords.append({
            "skill": result.keyword,
            "count": result.count,
            "weight": result.weight,
            "tier": result.tier,
            "category": result.category,
        })

    # Sort by tier priority, then weight, then count
    tier_order = {"required": 0, "preferred": 1, "nice": 2}
    matched_keywords.sort(
        key=lambda d: (tier_order.get(d["tier"], 3), -d["weight"], -d["count"])
    )

    matched_set = set(matches.keys())
    missing_required = _find_missing_required(keyword_spec, matcher, matched_set)
    missing_by_category = _find_missing_by_category(keyword_spec, matcher, matched_set)
    exp_scores = matcher.score_experience_roles(candidate)

    return {
        "matched_keywords": matched_keywords,
        "missing_required": missing_required,
        "missing_by_category": missing_by_category,
        "experience_scores": exp_scores,
    }


def _bullet_text(b: Any) -> str:
    """Extract text from a bullet (str or dict)."""
    if isinstance(b, dict):
        return str(b.get("text") or b.get("line") or b.get("name") or "")
    return str(b)


def _filter_bullets(
    bullets: List[Any],
    matcher: KeywordMatcher,
    max_bullets: int,
) -> List[str]:
    """Filter bullets to those matching keywords, up to max_bullets."""
    kept = []
    for b in bullets:
        bt = _bullet_text(b)
        if matcher.matches(bt):
            kept.append(bt)
        if len(kept) >= max_bullets:
            break
    if not kept and bullets:
        kept = [_bullet_text(bullets[0])]
    return kept


def _build_tailored_exp_items(
    candidate: Dict[str, Any],
    scores: Dict[int, int],
    matcher: KeywordMatcher,
    min_exp_score: int,
    max_bullets_per_role: int,
) -> List[Tuple[int, Dict[str, Any]]]:
    """Build scored experience items, filtering by score and bullets."""
    items = []
    for i, e in enumerate(candidate.get("experience") or []):
        if scores.get(i, 0) < min_exp_score:
            continue
        kept = _filter_bullets(e.get("bullets") or [], matcher, max_bullets_per_role)
        items.append((i, {**e, "bullets": kept}))
    return items


def build_tailored_candidate(
    candidate: Dict[str, Any],
    alignment: Dict[str, Any],
    limit_skills: int = 20,
    max_bullets_per_role: int = 6,
    min_exp_score: int = 1,
) -> Dict[str, Any]:
    """Build a tailored candidate profile based on alignment results.

    Args:
        candidate: Original candidate data.
        alignment: Alignment report from align_candidate_to_job.
        limit_skills: Maximum skills to include.
        max_bullets_per_role: Maximum bullets per experience role.
        min_exp_score: Minimum score for a role to be included.

    Returns:
        Tailored candidate with filtered skills and experience.
    """
    matched = alignment.get("matched_keywords") or []
    skills = [m["skill"] for m in matched][:limit_skills]
    scores = {i: s for i, s in alignment.get("experience_scores") or []}

    # Build matcher for bullet filtering
    matcher = KeywordMatcher()
    for skill in skills:
        matcher.add_keyword(skill)

    tailored_exp_items = _build_tailored_exp_items(
        candidate, scores, matcher, min_exp_score, max_bullets_per_role
    )
    tailored_exp_items.sort(key=lambda t: scores.get(t[0], 0), reverse=True)
    tailored_exp = [e for _, e in tailored_exp_items]

    return {
        **{k: v for k, v in candidate.items() if k not in {"skills", "experience"}},
        "skills": skills or (candidate.get("skills") or [])[:limit_skills],
        "experience": tailored_exp or (candidate.get("experience") or [])[:3],
    }
