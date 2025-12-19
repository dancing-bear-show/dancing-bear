from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .io_utils import read_yaml_or_json


def _normalize_keywords(lst: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not lst:
        return out
    if isinstance(lst, list):
        for item in lst:
            if isinstance(item, str):
                out.append({"skill": item, "weight": 1})
            elif isinstance(item, dict):
                skill = item.get("skill") or item.get("name") or item.get("key")
                weight = item.get("weight", 1)
                if skill:
                    out.append({"skill": str(skill), "weight": int(weight)})
    return out


def load_job_config(path: str) -> Dict[str, Any]:
    return read_yaml_or_json(path)


def build_keyword_spec(job_cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
    kws = job_cfg.get("keywords", {}) or {}
    required = _normalize_keywords(kws.get("required"))
    preferred = _normalize_keywords(kws.get("preferred"))
    nice = _normalize_keywords(kws.get("nice_to_have") or kws.get("nice") or [])

    # Category groups
    soft = _normalize_keywords(kws.get("soft_skills"))
    tech = _normalize_keywords(kws.get("tech_skills") or kws.get("technical_skills"))
    tech_ref = _normalize_keywords(
        kws.get("technologies")
        or kws.get("individual_technology_reference")
        or kws.get("individual_technology_references")
    )

    synonyms: Dict[str, List[str]] = {}
    syn = kws.get("synonyms") or {}
    if isinstance(syn, dict):
        for k, v in syn.items():
            if isinstance(v, list):
                synonyms[str(k)] = [str(x) for x in v]
            elif isinstance(v, str):
                synonyms[str(k)] = [v]

    spec: Dict[str, Any] = {
        "required": required,
        "preferred": preferred,
        "nice": nice,
        "categories": {
            "soft_skills": soft,
            "tech_skills": tech,
            "technologies": tech_ref,
        },
    }
    return spec, synonyms
