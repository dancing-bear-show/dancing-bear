"""Skills filtering by keyword matching.

Uses KeywordMatcher for consistent matching behavior across the codebase.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .keyword_matcher import KeywordMatcher


def _extract_item_name(item: Any) -> Optional[str]:
    """Extract keyword name from an item (dict or str)."""
    if isinstance(item, dict):
        name = item.get("skill") or item.get("name")
        return str(name) if name else None
    if isinstance(item, str):
        return item
    return None


def _flatten_tier_keywords(spec: Dict[str, Any]) -> List[str]:
    """Extract keywords from required/preferred/nice tiers."""
    out: List[str] = []
    for tier in ("required", "preferred", "nice"):
        for item in spec.get(tier, []) or []:
            if (name := _extract_item_name(item)):
                out.append(name)
    return out


def _flatten_category_keywords(spec: Dict[str, Any]) -> List[str]:
    """Extract keywords from category sections."""
    out: List[str] = []
    cats = spec.get("categories") or {}
    for _, lst in (cats.items() if isinstance(cats, dict) else []):
        for item in lst or []:
            if (name := _extract_item_name(item)):
                out.append(name)
    return out


def _flatten_keywords(spec: Dict[str, Any]) -> List[str]:
    """Extract all keywords from a keyword spec."""
    return _flatten_tier_keywords(spec) + _flatten_category_keywords(spec)


def filter_skills_by_keywords(
    data: Dict[str, Any],
    matched_keywords: Iterable[str],
    synonyms: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Return a shallow-copied data with skills filtered by matched keywords.

    - Filters skills_groups items whose name/desc contains any keyword or synonym.
    - Filters flat skills list similarly if groups are absent.
    - Drops empty groups.

    Args:
        data: Candidate data dict.
        matched_keywords: Keywords to match against.
        synonyms: Optional synonym mapping.

    Returns:
        Filtered data with only matching skills.
    """
    # Build matcher with expanded keywords
    matcher = KeywordMatcher()
    matcher.add_synonyms(synonyms or {})
    keywords = list(matched_keywords or [])
    expanded = matcher.expand_all(keywords)

    out = dict(data)
    groups = data.get("skills_groups") or []

    if groups:
        out["skills_groups"] = _filter_skill_groups(groups, matcher, expanded)
    else:
        skills = [str(s) for s in (data.get("skills") or [])]
        out["skills"] = [
            s for s in skills
            if matcher.matches_any(s, expanded, expand_synonyms=False)
        ]

    return out


def _item_text(it: Any) -> str:
    """Extract searchable text from a skill item."""
    if isinstance(it, dict):
        name = it.get("name") or it.get("title") or it.get("label") or ""
        desc = it.get("desc") or it.get("description") or ""
        return f"{name} {desc}".strip()
    return str(it)


def _filter_skill_groups(groups: List[Any], matcher: "KeywordMatcher", expanded: List[str]) -> List[Dict[str, Any]]:
    """Filter skill groups to only items matching expanded keywords."""
    new_groups = []
    for g in groups:
        title = g.get("title")
        items = g.get("items") or []
        keep_items = [
            it for it in items
            if matcher.matches_any(_item_text(it), expanded, expand_synonyms=False)
        ]
        if keep_items:
            new_groups.append({"title": title, "items": keep_items})
    return new_groups
