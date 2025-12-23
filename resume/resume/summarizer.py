from __future__ import annotations

from typing import Any, Dict, List


def _keyword_hits(text: str, keywords: List[str]) -> int:
    text_l = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_l)


def build_summary(data: Dict[str, Any], seed: Dict[str, Any] | None = None) -> Dict[str, Any]:
    seed = seed or {}
    keywords: List[str] = []
    if isinstance(seed.get("keywords"), list):
        keywords = [str(k) for k in seed.get("keywords", [])]
    elif isinstance(seed.get("keywords"), str):
        keywords = [k.strip() for k in seed["keywords"].split(",") if k.strip()]

    experiences = data.get("experience", []) or []
    # score experiences by keyword matches
    scored = []
    for e in experiences:
        blob = " ".join([e.get("title", ""), e.get("company", ""), " ".join(e.get("bullets", []))])
        scored.append((e, _keyword_hits(blob, keywords)))
    # top highlights = top bullets or titles
    scored.sort(key=lambda t: t[1], reverse=True)
    highlights: List[str] = []
    for e, _score in scored[:5]:
        title = e.get("title", "")
        company = e.get("company", "")
        if title or company:
            highlights.append(f"{title} at {company}".strip())
        for b in (e.get("bullets") or [])[:2]:
            highlights.append(b)
        if len(highlights) >= 8:
            break

    # top skills: keep order but prefer those in keywords
    skills = [str(s) for s in (data.get("skills") or [])]
    keyset = {k.lower() for k in keywords}
    prioritized = [s for s in skills if s.lower() in keyset] + [s for s in skills if s.lower() not in keyset]
    top_skills = prioritized[:10]

    return {
        "name": data.get("name", ""),
        "headline": data.get("headline", ""),
        "top_skills": top_skills,
        "experience_highlights": highlights,
    }

