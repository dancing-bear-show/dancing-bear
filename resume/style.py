from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .io_utils import read_text_any


DEFAULT_STOPWORDS = {
    "the","a","an","and","or","but","if","then","else","for","to","of","in","on","at","by","with",
    "as","is","are","was","were","be","been","being","it","this","that","these","those","from","into",
    "i","we","you","they","he","she","them","him","her","our","your","their","my","mine","ours","yours",
    "not","no","yes","do","does","did","done","can","could","should","would","may","might","will","shall",
}


def _iter_texts(corpus_dir: str | os.PathLike[str]) -> Iterable[str]:
    p = Path(corpus_dir)
    if not p.exists():
        return []
    for ext in ("*.txt", "*.md", "*.docx"):
        for f in p.rglob(ext):
            try:
                yield read_text_any(f)
            except Exception:  # nosec B112 - skip on error
                continue


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9+_.-]{1,}", text)


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def build_style_profile(corpus_dir: str, top_n: int = 50) -> Dict[str, Any]:
    texts = list(_iter_texts(corpus_dir))
    if not texts:
        return {"files": 0, "tokens": [], "bigrams": [], "avg_sentence_length": 0.0}
    all_text = "\n".join(texts)
    toks = [t for t in _tokenize(all_text)]
    words = [t.lower() for t in toks if t.lower() not in DEFAULT_STOPWORDS and len(t) > 2]
    unigram_counts = Counter(words)
    # bigrams
    bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
    bigram_counts = Counter(bigrams)
    # avg sentence length
    sents = _sentences(all_text)
    avg_len = 0.0
    if sents:
        avg_len = sum(len(_tokenize(s)) for s in sents) / max(1, len(sents))
    profile = {
        "files": len(texts),
        "top_unigrams": [w for w, _ in unigram_counts.most_common(top_n)],
        "top_bigrams": [w for w, _ in bigram_counts.most_common(min(top_n, 30))],
        "avg_sentence_length": round(avg_len, 2),
    }
    return profile


def extract_style_keywords(style_profile: Dict[str, Any], limit: int = 20) -> List[str]:
    kws = []
    kws.extend(style_profile.get("top_unigrams", [])[:limit])
    # include bigrams as tokens (optional)
    for bg in style_profile.get("top_bigrams", [])[:10]:
        if bg not in kws:
            kws.append(bg)
    return kws[:limit]

