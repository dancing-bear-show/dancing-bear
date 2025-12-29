from __future__ import annotations

from typing import Any, Dict, List


def _score(v) -> float:
    try:
        return float(v)
    except Exception:
        return 1.0


def _filter_items(items: List[Any], cutoff: float) -> List[Any]:
    out = []
    for it in (items or []):
        if isinstance(it, dict):
            pr = it.get("priority") if it.get("priority") is not None else it.get("usefulness")
            pr = _score(pr) if pr is not None else 1.0
            if pr >= cutoff:
                out.append(it)
        else:
            # strings: keep when cutoff is <= default (1.0)
            if cutoff <= 1.0:
                out.append(it)
    return out


def _filter_skills_groups(groups: List[Any], cutoff: float) -> List[Any]:
    """Filter skills_groups items by priority cutoff."""
    new_groups = []
    for g in groups or []:
        items = g.get("items") if isinstance(g, dict) else None
        if isinstance(items, list):
            fi = _filter_items(items, cutoff)
            if fi:
                new_groups.append({**g, "items": fi})
        else:
            new_groups.append(g)
    return new_groups


def _filter_experience(exp: List[Any], cutoff: float) -> List[Any]:
    """Filter experience roles and bullets by priority cutoff."""
    new_exp = []
    for e in exp or []:
        if not isinstance(e, dict):
            continue
        role_pr = _score(e.get("priority")) if e.get("priority") is not None else 1.0
        if role_pr < cutoff:
            continue
        if isinstance(e.get("bullets"), list):
            e = {**e, "bullets": _filter_items(e["bullets"], cutoff)}
        new_exp.append(e)
    return new_exp


def filter_by_min_priority(data: Dict[str, Any], min_prio: float) -> Dict[str, Any]:
    """Apply priority/usefulness cutoff across known lists in candidate data."""
    d = dict(data)

    if isinstance(d.get("skills_groups"), list):
        d["skills_groups"] = _filter_skills_groups(d["skills_groups"], min_prio)

    for key in ("technologies", "interests", "presentations", "languages", "coursework", "summary", "teaching", "certifications"):
        if isinstance(d.get(key), list):
            d[key] = _filter_items(d[key], min_prio)

    if isinstance(d.get("experience"), list):
        d["experience"] = _filter_experience(d["experience"], min_prio)

    return d

