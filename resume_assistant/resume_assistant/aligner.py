from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _canon_map(synonyms: Dict[str, List[str]]) -> Dict[str, str]:
    m: Dict[str, str] = {}
    for canon, syns in synonyms.items():
        m[canon.lower()] = canon
        for s in syns:
            m[s.lower()] = canon
    return m


def _token_match(text: str, keyword: str) -> bool:
    if not text or not keyword:
        return False
    # simple case-insensitive substring match with word boundaries preference
    t = text.lower()
    k = keyword.lower()
    if re.search(rf"\b{re.escape(k)}\b", t):
        return True
    return k in t


def _collect_candidate_text(candidate: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    items: List[Tuple[str, Dict[str, Any]]] = []
    # Summary and skills
    if candidate.get("summary"):
        items.append((str(candidate["summary"]), {"scope": "summary"}))
    for s in candidate.get("skills") or []:
        items.append((str(s), {"scope": "skills"}))
    # Experience
    for i, e in enumerate(candidate.get("experience") or []):
        title = " ".join([e.get("title") or "", e.get("company") or ""]).strip()
        if title:
            items.append((title, {"scope": "exp_title", "index": i}))
        for b in e.get("bullets") or []:
            items.append((str(b), {"scope": "exp_bullet", "index": i}))
    return items


def align_candidate_to_job(
    candidate: Dict[str, Any],
    keyword_spec: Dict[str, Any],
    synonyms: Dict[str, List[str]] | None = None,
) -> Dict[str, Any]:
    syn_map = _canon_map(synonyms or {})
    def canon(s: str) -> str:
        return syn_map.get(s.lower(), s)

    required = keyword_spec.get("required", [])
    preferred = keyword_spec.get("preferred", [])
    nice = keyword_spec.get("nice", [])
    categories = (keyword_spec.get("categories") or {})
    # Flatten category keywords and preserve category tag
    cat_map: Dict[str, str] = {}
    all_kw = [*required, *preferred, *nice]
    for cat_name, lst in categories.items():
        for item in lst or []:
            tag = dict(item)
            tag["category"] = cat_name
            all_kw.append(tag)
    canon_list = [canon(x["skill"]) for x in all_kw]
    weights = {canon(k["skill"]): int(k.get("weight", 1)) for k in all_kw}
    tiers = {}
    for k in all_kw:
        ck = canon(k["skill"]) 
        if k in required:
            tiers[ck] = "required"
        elif k in preferred:
            tiers[ck] = "preferred"
        elif k in nice:
            tiers[ck] = "nice"
        if k.get("category"):
            cat_map[ck] = k["category"]

    counts: Dict[str, int] = {k: 0 for k in canon_list}
    hits: Dict[str, List[Dict[str, Any]]] = {k: [] for k in canon_list}
    items = _collect_candidate_text(candidate)
    for text, meta in items:
        for kw_raw in canon_list:
            # test kw and its synonyms
            alts = [kw_raw] + [s for s, c in syn_map.items() if c == kw_raw]
            if any(_token_match(text, alt) for alt in alts):
                counts[kw_raw] += 1
                hits[kw_raw].append({"text": text, **meta})

    matched = [k for k, c in counts.items() if c > 0]
    missing_required = [canon(k["skill"]) for k in required if counts.get(canon(k["skill"])) == 0]
    # missing by category
    missing_by_category: Dict[str, List[str]] = {}
    for cat_name, lst in categories.items():
        miss = []
        for item in lst or []:
            ck = canon(item.get("skill", ""))
            if ck and counts.get(ck, 0) == 0:
                miss.append(ck)
        missing_by_category[cat_name] = miss

    # experience scores
    exp_scores: List[Tuple[int, int]] = []  # (index, score)
    exp_len = len(candidate.get("experience") or [])
    for i in range(exp_len):
        score = 0
        # title/company
        for kw in matched:
            for h in hits[kw]:
                if h.get("scope") == "exp_title" and h.get("index") == i:
                    score += weights.get(kw, 1)
        # bullets
        for kw in matched:
            for h in hits[kw]:
                if h.get("scope") == "exp_bullet" and h.get("index") == i:
                    score += 1
        exp_scores.append((i, score))

    exp_scores.sort(key=lambda t: t[1], reverse=True)
    matched_keywords = [
        {
            "skill": k,
            "count": counts[k],
            "weight": weights.get(k, 1),
            "tier": tiers.get(k, "preferred"),
            "category": cat_map.get(k),
        }
        for k in matched
    ]
    matched_keywords.sort(key=lambda d: (d["tier"] == "required", d["weight"], d["count"]), reverse=True)

    return {
        "matched_keywords": matched_keywords,
        "missing_required": missing_required,
        "missing_by_category": missing_by_category,
        "experience_scores": exp_scores,
    }


def build_tailored_candidate(
    candidate: Dict[str, Any],
    alignment: Dict[str, Any],
    limit_skills: int = 20,
    max_bullets_per_role: int = 6,
    min_exp_score: int = 1,
) -> Dict[str, Any]:
    matched = alignment.get("matched_keywords") or []
    # sort already handled; pick top skills
    skills = [m["skill"] for m in matched][:limit_skills]
    scores = {i: s for i, s in alignment.get("experience_scores") or []}

    tailored_exp_items: List[Tuple[int, Dict[str, Any]]] = []
    for i, e in enumerate(candidate.get("experience") or []):
        sc = scores.get(i, 0)
        if sc < min_exp_score:
            continue
        # filter bullets to those that include matched keywords
        kept: List[str] = []
        for b in e.get("bullets") or []:
            if isinstance(b, dict):
                bt = str(b.get("text") or b.get("line") or b.get("name") or "")
            else:
                bt = str(b)
            if any(re.search(rf"\b{re.escape(k)}\b", bt, re.I) or (k.lower() in bt.lower()) for k in skills):
                kept.append(bt)
            if len(kept) >= max_bullets_per_role:
                break
        tailored_exp_items.append((i, {**e, "bullets": kept or (e.get("bullets") or [])[:1]}))

    # keep order by score descending
    tailored_exp_items.sort(key=lambda t: scores.get(t[0], 0), reverse=True)
    tailored_exp = [e for _, e in tailored_exp_items]

    out = {
        **{k: v for k, v in candidate.items() if k not in {"skills", "experience"}},
        "skills": skills or (candidate.get("skills") or [])[:limit_skills],
        "experience": tailored_exp or (candidate.get("experience") or [])[:3],
    }
    return out
