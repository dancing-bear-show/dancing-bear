from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def keyword_match(
    text: str,
    keyword: str,
    *,
    normalize: bool = False,
    word_boundary: bool = True,
) -> bool:
    if not text or not keyword:
        return False
    if normalize:
        t = normalize_text(text)
        k = normalize_text(keyword)
    else:
        t = text.lower()
        k = keyword.lower()
    if not k:
        return False
    if word_boundary and re.search(rf"\b{re.escape(k)}\b", t):
        return True
    return k in t


def expand_keywords(
    keywords: Iterable[str],
    synonyms: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    syn = synonyms or {}
    out: List[str] = []
    for kw in keywords or []:
        if not kw:
            continue
        skw = str(kw)
        out.append(skw)
        for s in syn.get(skw, []) or []:
            if s:
                out.append(str(s))
    return out
