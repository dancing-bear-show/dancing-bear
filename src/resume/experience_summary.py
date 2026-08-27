from __future__ import annotations

from typing import Any

from .keyword_normalize import item_text


def build_experience_summary(data: dict[str, Any], max_bullets: int | None = None) -> dict[str, Any]:
    roles_out: list[dict[str, Any]] = []
    for e in data.get("experience") or []:
        # item_text, not str(): a bullet is a dict ({"text": ..., "priority": ...})
        # as often as a bare string, and str() on the dict emits its Python repr
        # -- braces, quotes and the priority number -- into the exported summary.
        bullets = [t for b in (e.get("bullets") or []) if (t := item_text(b))]
        if max_bullets is not None:
            bullets = bullets[: max_bullets]
        roles_out.append(
            {
                "title": e.get("title", ""),
                "company": e.get("company", ""),
                "start": e.get("start", ""),
                "end": e.get("end", ""),
                "location": e.get("location", ""),
                "bullets": bullets,
            }
        )
    summary = {
        "name": data.get("name", ""),
        "headline": data.get("headline", ""),
        "experience": roles_out,
    }
    return summary

