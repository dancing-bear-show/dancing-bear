"""Lightweight summarization adapter.

Defaults to a heuristic (extractive) summary to avoid optional deps.
If an external LLM is configured via environment variables, this module can
be extended to call out to that provider. Keep imports lazy.
"""
from __future__ import annotations



def _take_sentences_within_budget(parts: list[str], max_words: int) -> list[str]:
    """Accumulate sentence parts until the word budget is spent, trimming the last part to fit."""
    out: list[str] = []
    words = 0
    for p in parts:
        w = len(p.split())
        if w == 0:
            continue
        remaining_budget = max_words - words
        if w > remaining_budget:
            if remaining_budget > 0:
                out.append(" ".join(p.split()[:remaining_budget]))
            break
        out.append(p)
        words += w
        if words >= max_words:
            break
    return out


def summarize_text(
    text: str | None,
    *,
    instructions: str | None = None,
    max_words: int = 120,
) -> str:
    """Return a concise summary of the given text.

    Heuristic behavior:
    - Take the first few sentences/lines until ~max_words.
    - Normalize whitespace.
    """
    # Basic normalization
    s = (text or "").strip()
    if not s:
        return "(no content)"
    # Prefer splitting on sentence boundaries, fallback to lines/words
    import re

    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)

    # Try to cut by sentence ends
    parts = re.split(r"(?<=[\.\?\!])\s+", s)
    out = _take_sentences_within_budget(parts, max_words)

    summary = " ".join(out).strip()
    if not summary:
        # Fallback on words only
        summary = " ".join(s.split()[:max_words])

    if instructions:
        # Prepend brief instruction context to guide interpretation when used
        return f"Summary: {summary}"
    return summary

