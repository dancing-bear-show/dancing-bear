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


def _extract_tier_keywords(spec: Dict[str, Any]) -> List[str]:
    """Extract keywords from tier lists (required, preferred, nice)."""
    out: List[str] = []
    for tier in ("required", "preferred", "nice"):
        for item in spec.get(tier, []) or []:
            if (name := _extract_item_name(item)):
                out.append(name)
    return out


def _extract_category_keywords(spec: Dict[str, Any]) -> List[str]:
    """Extract keywords from categories section."""
    out: List[str] = []
    cats = spec.get("categories") or {}
    if isinstance(cats, dict):
        for _, lst in cats.items():
            for item in lst or []:
                if (name := _extract_item_name(item)):
                    out.append(name)
    return out


def _flatten_keywords(spec: Dict[str, Any]) -> List[str]:
    """Extract all keywords from a keyword spec."""
    out: List[str] = []
    out.extend(_extract_tier_keywords(spec))
    out.extend(_extract_category_keywords(spec))
    return out


def _extract_item_text(item: Any) -> str:
    """Extract text from a skill item for matching."""
    if isinstance(item, dict):
        name = item.get("name") or item.get("title") or item.get("label") or ""
        desc = item.get("desc") or item.get("description") or ""
        return f"{name} {desc}".strip()
    return str(item)


def _filter_group_items(
    items: List[Any],
    matcher: KeywordMatcher,
    expanded_keywords: List[str]
) -> List[Any]:
    """Filter items in a skill group based on keyword matches."""
    keep_items = []
    for it in items:
        text = _extract_item_text(it)
        if matcher.matches_any(text, expanded_keywords, expand_synonyms=False):
            keep_items.append(it)
    return keep_items


def _filter_skills_groups(
    groups: List[Dict[str, Any]],
    matcher: KeywordMatcher,
    expanded_keywords: List[str]
) -> List[Dict[str, Any]]:
    """Filter skills groups, keeping only groups with matching items."""
    new_groups = []
    for g in groups:
        title = g.get("title")
        items = g.get("items") or []
        keep_items = _filter_group_items(items, matcher, expanded_keywords)
        if keep_items:
            new_groups.append({"title": title, "items": keep_items})
    return new_groups


def _filter_flat_skills(
    skills: List[Any],
    matcher: KeywordMatcher,
    expanded_keywords: List[str]
) -> List[str]:
    """Filter flat skills list based on keyword matches."""
    skills_str = [str(s) for s in skills]
    return [
        s for s in skills_str
        if matcher.matches_any(s, expanded_keywords, expand_synonyms=False)
    ]


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
        out["skills_groups"] = _filter_skills_groups(groups, matcher, expanded)
    else:
        skills = data.get("skills") or []
        out["skills"] = _filter_flat_skills(skills, matcher, expanded)

    return out
