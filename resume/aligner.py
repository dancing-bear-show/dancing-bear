"""Candidate-to-job alignment using KeywordMatcher.

Matches candidate profile against job requirements and produces alignment reports.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .keyword_matcher import KeywordMatcher


def _build_matched_keywords(matches: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build sorted list of matched keywords with metadata."""
    matched_keywords = []
    for kw, result in matches.items():
        matched_keywords.append({
            "skill": result.keyword,
            "count": result.count,
            "weight": result.weight,
            "tier": result.tier,
            "category": result.category,
        })

    tier_order = {"required": 0, "preferred": 1, "nice": 2}
    matched_keywords.sort(
        key=lambda d: (tier_order.get(d["tier"], 3), -d["weight"], -d["count"])
    )
    return matched_keywords


def _find_missing_required(
    keyword_spec: Dict[str, Any],
    matched_set: set,
    matcher: KeywordMatcher,
) -> List[str]:
    """Find required keywords that are missing from matches."""
    required = keyword_spec.get("required", [])
    missing_required = []
    for item in required:
        kw = item.get("skill") or item.get("name") or ""
        if kw:
            canon = matcher.canonicalize(kw)
            if canon not in matched_set:
                missing_required.append(canon)
    return missing_required


def _extract_keyword_from_item(item: Any) -> str:
    """Extract keyword string from an item (dict or string)."""
    if isinstance(item, dict):
        return item.get("skill") or item.get("name") or ""
    return str(item)


def _find_missing_in_category(
    items: List[Any],
    matched_set: set,
    matcher: KeywordMatcher,
) -> List[str]:
    """Find missing keywords in a single category."""
    missing = []
    for item in items or []:
        kw = _extract_keyword_from_item(item)
        if kw:
            canon = matcher.canonicalize(kw)
            if canon not in matched_set:
                missing.append(canon)
    return missing


def _find_missing_by_category(
    keyword_spec: Dict[str, Any],
    matched_set: set,
    matcher: KeywordMatcher,
) -> Dict[str, List[str]]:
    """Find missing keywords grouped by category."""
    categories = keyword_spec.get("categories") or {}
    missing_by_category: Dict[str, List[str]] = {}
    for cat_name, items in categories.items():
        missing_by_category[cat_name] = _find_missing_in_category(items, matched_set, matcher)
    return missing_by_category


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
    matched_set = set(matches.keys())

    # Build matched keywords list with full metadata
    matched_keywords = _build_matched_keywords(matches)

    # Find missing required keywords
    missing_required = _find_missing_required(keyword_spec, matched_set, matcher)

    # Find missing by category
    missing_by_category = _find_missing_by_category(keyword_spec, matched_set, matcher)

    # Score experience roles
    exp_scores = matcher.score_experience_roles(candidate)

    return {
        "matched_keywords": matched_keywords,
        "missing_required": missing_required,
        "missing_by_category": missing_by_category,
        "experience_scores": exp_scores,
    }


def _extract_bullet_text(bullet: Any) -> str:
    """Extract text from a bullet item (dict or string)."""
    if isinstance(bullet, dict):
        return str(bullet.get("text") or bullet.get("line") or bullet.get("name") or "")
    return str(bullet)


def _filter_bullets(
    bullets: List[Any],
    matcher: KeywordMatcher,
    max_bullets: int,
) -> List[str]:
    """Filter bullets to those matching keywords, up to max_bullets."""
    kept: List[str] = []
    for b in bullets or []:
        bt = _extract_bullet_text(b)
        if matcher.matches(bt):
            kept.append(bt)
        if len(kept) >= max_bullets:
            break

    # Fallback to first bullet if none matched
    if not kept and bullets:
        kept = [_extract_bullet_text(bullets[0])]

    return kept


def _tailor_experience_items(
    candidate: Dict[str, Any],
    scores: Dict[int, int],
    matcher: KeywordMatcher,
    max_bullets_per_role: int,
    min_exp_score: int,
) -> List[Tuple[int, Dict[str, Any]]]:
    """Filter and tailor experience items based on scores and keyword matches."""
    tailored_exp_items: List[Tuple[int, Dict[str, Any]]] = []
    for i, e in enumerate(candidate.get("experience") or []):
        sc = scores.get(i, 0)
        if sc < min_exp_score:
            continue

        kept = _filter_bullets(e.get("bullets"), matcher, max_bullets_per_role)
        tailored_exp_items.append((i, {**e, "bullets": kept}))

    return tailored_exp_items


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

    # Filter and tailor experience items
    tailored_exp_items = _tailor_experience_items(
        candidate, scores, matcher, max_bullets_per_role, min_exp_score
    )

    # Sort by score descending
    tailored_exp_items.sort(key=lambda t: scores.get(t[0], 0), reverse=True)
    tailored_exp = [e for _, e in tailored_exp_items]

    return {
        **{k: v for k, v in candidate.items() if k not in {"skills", "experience"}},
        "skills": skills or (candidate.get("skills") or [])[:limit_skills],
        "experience": tailored_exp or (candidate.get("experience") or [])[:3],
    }
