"""Lightweight summarization adapter.

Defaults to a heuristic (extractive) summary to avoid optional deps.
If an external LLM is configured via environment variables, this module can
be extended to call out to that provider. Keep imports lazy.
"""
from __future__ import annotations

from typing import Optional


def summarize_text(
    text: str,
    *,
    instructions: Optional[str] = None,
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
    out: list[str] = []
    words = 0
    for p in parts:
        w = len(p.split())
        if w == 0:
            continue
        if words + w > max_words:
            # Trim last sentence to fit word budget
            remaining = max_words - words
            if remaining > 0:
                p = " ".join(p.split()[:remaining])
                out.append(p)
            break
        out.append(p)
        words += w
        if words >= max_words:
            break

    summary = " ".join(out).strip()
    if not summary:
        # Fallback on words only
        summary = " ".join(s.split()[:max_words])

    if instructions:
        # Prepend brief instruction context to guide interpretation when used
        return f"Summary: {summary}"
    return summary

