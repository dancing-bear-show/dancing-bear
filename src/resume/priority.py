from __future__ import annotations

from typing import Any


def _score(v: Any) -> float:
    try:
        return float(v)
    except Exception:  # nosec B110 - non-numeric priority falls back to default
        return 1.0


def _item_priority(it: Any) -> float:
    """Return priority score for a dict item (falls back to 1.0)."""
    pr = it.get("priority") if it.get("priority") is not None else it.get("usefulness")
    return _score(pr) if pr is not None else 1.0


def _filter_items(items: list[Any] | None, cutoff: float) -> list[Any]:
    out = []
    for it in (items or []):
        if isinstance(it, dict):
            if _item_priority(it) >= cutoff:
                out.append(it)
        elif cutoff <= 1.0:
            # strings: keep when cutoff is <= default (1.0)
            out.append(it)
    return out


def _filter_skills_groups(groups: list[Any] | None, cutoff: float) -> list[Any]:
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


def _filter_experience(exp: list[Any] | None, cutoff: float) -> list[Any]:
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


def _filter_projects(projects: list[Any] | None, cutoff: float) -> list[Any]:
    """Filter project entries and their bullets by priority cutoff.

    Mirrors :func:`_filter_experience`: project-level ``priority`` gates the
    whole entry, and each bullet's ``priority`` gates that bullet independently.
    """
    new_projects = []
    for p in projects or []:
        if not isinstance(p, dict):
            continue
        proj_pr = _score(p.get("priority")) if p.get("priority") is not None else 1.0
        if proj_pr < cutoff:
            continue
        if isinstance(p.get("bullets"), list):
            p = {**p, "bullets": _filter_items(p["bullets"], cutoff)}
        new_projects.append(p)
    return new_projects


def filter_by_min_priority(data: dict[str, Any], min_prio: float) -> dict[str, Any]:
    """Apply priority/usefulness cutoff across known lists in candidate data."""
    d = dict(data)

    if isinstance(d.get("skills_groups"), list):
        d["skills_groups"] = _filter_skills_groups(d["skills_groups"], min_prio)

    for key in ("technologies", "interests", "presentations", "languages", "coursework", "summary", "teaching", "certifications"):
        if isinstance(d.get(key), list):
            d[key] = _filter_items(d[key], min_prio)

    if isinstance(d.get("experience"), list):
        d["experience"] = _filter_experience(d["experience"], min_prio)

    if isinstance(d.get("projects"), list):
        d["projects"] = _filter_projects(d["projects"], min_prio)

    return d

