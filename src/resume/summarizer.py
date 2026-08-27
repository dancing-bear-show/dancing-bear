from __future__ import annotations

from typing import Any

from .keyword_normalize import item_match_text, item_text


def _keyword_hits(text: str, keywords: list[str]) -> int:
    text_l = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_l)


def _extract_keywords(seed: dict[str, Any]) -> list[str]:
    """Extract the keyword list from a seed dict (list or comma-separated string)."""
    raw = seed.get("keywords")
    if isinstance(raw, list):
        return [str(k) for k in raw]
    if isinstance(raw, str):
        return [k.strip() for k in raw.split(",") if k.strip()]
    return []


def _score_experiences(experiences: list[dict[str, Any]], keywords: list[str]) -> list[dict[str, Any]]:
    """Rank experiences by keyword-match count, most relevant first."""
    def _score(e: dict[str, Any]) -> int:
        # Bullets are dicts ({"text": ..., "priority": ...}) or bare strings
        # depending on the producer, so they are joined through item_match_text
        # rather than directly: " ".join() over dicts raises TypeError, and
        # str(dict) would match against the Python repr's braces and quotes.
        # item_match_text also folds in `desc`, so a keyword appearing only in a
        # bullet's detail still scores.
        bullets = " ".join(item_match_text(b) for b in (e.get("bullets") or []))
        blob = " ".join([e.get("title", ""), e.get("company", ""), bullets])
        return _keyword_hits(blob, keywords)

    return sorted(experiences, key=_score, reverse=True)


def _experience_highlight_lines(e: dict[str, Any]) -> list[str]:
    """Build the highlight lines (title/company + top bullets) for one experience entry."""
    lines: list[str] = []
    title = e.get("title", "")
    company = e.get("company", "")
    if title or company:
        lines.append(f"{title} at {company}".strip())
    # Display text, so item_text (not item_match_text): a highlight line shows
    # the bullet's prose, without the `desc` detail that matching folds in.
    # Emitting the raw item would put a dict's repr into the rendered summary.
    lines.extend(t for b in (e.get("bullets") or [])[:2] if (t := item_text(b)))
    return lines


def _build_highlights(scored_experiences: list[dict[str, Any]], limit: int = 8, top_n: int = 5) -> list[str]:
    """Assemble top experience highlights up to limit, from the top_n ranked experiences."""
    highlights: list[str] = []
    for e in scored_experiences[:top_n]:
        highlights.extend(_experience_highlight_lines(e))
        if len(highlights) >= limit:
            break
    return highlights


def _prioritize_skills(skills: list[str], keywords: list[str], limit: int = 10) -> list[str]:
    """Order skills with keyword matches first, then truncate to limit."""
    keyset = {k.lower() for k in keywords}
    prioritized = [s for s in skills if s.lower() in keyset] + [s for s in skills if s.lower() not in keyset]
    return prioritized[:limit]


def build_summary(data: dict[str, Any], seed: dict[str, Any] | None = None) -> dict[str, Any]:
    seed = seed or {}
    keywords = _extract_keywords(seed)

    scored = _score_experiences(data.get("experience", []) or [], keywords)
    highlights = _build_highlights(scored)

    skills = [str(s) for s in (data.get("skills") or [])]
    top_skills = _prioritize_skills(skills, keywords)

    return {
        "name": data.get("name", ""),
        "headline": data.get("headline", ""),
        "top_skills": top_skills,
        "experience_highlights": highlights,
    }
