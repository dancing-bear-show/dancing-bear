"""Candidate-to-job alignment using KeywordMatcher.

Matches candidate profile against job requirements and produces alignment reports.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .keyword_matcher import KeywordMatcher


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

    # Find missing required keywords
    required = keyword_spec.get("required", [])
    matched_set = set(matches.keys())
    missing_required = []
    for item in required:
        kw = item.get("skill") or item.get("name") or ""
        if kw:
            canon = matcher.canonicalize(kw)
            if canon not in matched_set:
                missing_required.append(canon)

    # Find missing by category
    categories = keyword_spec.get("categories") or {}
    missing_by_category: Dict[str, List[str]] = {}
    for cat_name, items in categories.items():
        missing = []
        for item in items or []:
            kw = item.get("skill") or item.get("name") or "" if isinstance(item, dict) else str(item)
            if kw:
                canon = matcher.canonicalize(kw)
                if canon not in matched_set:
                    missing.append(canon)
        missing_by_category[cat_name] = missing

    # Score experience roles
    exp_scores = matcher.score_experience_roles(candidate)

    return {
        "matched_keywords": matched_keywords,
        "missing_required": missing_required,
        "missing_by_category": missing_by_category,
        "experience_scores": exp_scores,
    }


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

    tailored_exp_items: List[Tuple[int, Dict[str, Any]]] = []
    for i, e in enumerate(candidate.get("experience") or []):
        sc = scores.get(i, 0)
        if sc < min_exp_score:
            continue

        # Filter bullets to those matching keywords
        kept: List[str] = []
        for b in e.get("bullets") or []:
            if isinstance(b, dict):
                bt = str(b.get("text") or b.get("line") or b.get("name") or "")
            else:
                bt = str(b)
            if matcher.matches(bt):
                kept.append(bt)
            if len(kept) >= max_bullets_per_role:
                break

        # Fallback to first bullet if none matched
        if not kept and e.get("bullets"):
            kept = [str(e["bullets"][0])]

        tailored_exp_items.append((i, {**e, "bullets": kept}))

    # Sort by score descending
    tailored_exp_items.sort(key=lambda t: scores.get(t[0], 0), reverse=True)
    tailored_exp = [e for _, e in tailored_exp_items]

    return {
        **{k: v for k, v in candidate.items() if k not in {"skills", "experience"}},
        "skills": skills or (candidate.get("skills") or [])[:limit_skills],
        "experience": tailored_exp or (candidate.get("experience") or [])[:3],
    }
