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


def filter_by_min_priority(data: Dict[str, Any], min_prio: float) -> Dict[str, Any]:
    """Apply priority/usefulness cutoff across known lists in candidate data.

    Applies to: skills_groups.items, technologies, interests, presentations,
    languages, coursework, summary (list), and experience roles+bullets.
    """
    d = dict(data)
    # Skills groups
    if isinstance(d.get("skills_groups"), list):
        new_groups = []
        for g in d.get("skills_groups") or []:
            items = g.get("items") if isinstance(g, dict) else None
            if isinstance(items, list):
                fi = _filter_items(items, min_prio)
                if fi:
                    g2 = dict(g)
                    g2["items"] = fi
                    new_groups.append(g2)
            else:
                new_groups.append(g)
        d["skills_groups"] = new_groups

    # Flat lists
    for key in ("technologies", "interests", "presentations", "languages", "coursework", "summary"):
        if isinstance(d.get(key), list):
            d[key] = _filter_items(d.get(key) or [], min_prio)

    # Experience roles and bullets
    if isinstance(d.get("experience"), list):
        new_exp = []
        for e in d.get("experience") or []:
            if not isinstance(e, dict):
                continue
            role_pr = _score(e.get("priority")) if e.get("priority") is not None else 1.0
            if role_pr < min_prio:
                continue
            bl = e.get("bullets")
            if isinstance(bl, list):
                e = dict(e)
                e["bullets"] = _filter_items(bl, min_prio)
            new_exp.append(e)
        d["experience"] = new_exp
    return d

