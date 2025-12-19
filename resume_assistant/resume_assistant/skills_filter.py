from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _item_matches(item_text: str, keywords: Set[str]) -> bool:
    it = _normalize_text(item_text)
    for kw in keywords:
        if not kw:
            continue
        k = kw.lower()
        # match whole or substring to be forgiving
        if k in it:
            return True
    return False


def _flatten_keywords(spec: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for tier in ("required", "preferred", "nice"):
        for item in spec.get(tier, []) or []:
            if isinstance(item, dict):
                name = item.get("skill") or item.get("name")
                if name:
                    out.append(str(name))
            elif isinstance(item, str):
                out.append(item)
    cats = spec.get("categories") or {}
    for _, lst in (cats.items() if isinstance(cats, dict) else []):
        for item in lst or []:
            if isinstance(item, dict):
                name = item.get("skill") or item.get("name")
                if name:
                    out.append(str(name))
            elif isinstance(item, str):
                out.append(item)
    return out


def filter_skills_by_keywords(
    data: Dict[str, Any],
    matched_keywords: Iterable[str],
    synonyms: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Return a shallow-copied data with skills filtered by matched keywords.

    - Filters skills_groups items whose name/desc contains any keyword or synonym.
    - Filters flat skills list similarly if groups are absent.
    - Drops empty groups.
    """
    syn = synonyms or {}
    kw: Set[str] = set()
    for k in matched_keywords:
        kw.add(str(k))
        for s in syn.get(k, []) or []:
            kw.add(str(s))

    out = dict(data)
    groups = (data.get("skills_groups") or [])
    if groups:
        new_groups = []
        for g in groups:
            title = g.get("title")
            items = g.get("items") or []
            keep_items = []
            for it in items:
                if isinstance(it, dict):
                    name = it.get("name") or it.get("title") or it.get("label") or ""
                    desc = it.get("desc") or it.get("description") or ""
                    text = f"{name} {desc}".strip()
                    if _item_matches(text, kw):
                        keep_items.append(it)
                else:
                    if _item_matches(str(it), kw):
                        keep_items.append(it)
            if keep_items:
                new_groups.append({"title": title, "items": keep_items})
        out["skills_groups"] = new_groups
    else:
        skills = [str(s) for s in (data.get("skills") or [])]
        out["skills"] = [s for s in skills if _item_matches(s, kw)]
    return out

