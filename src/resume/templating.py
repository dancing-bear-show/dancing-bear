from __future__ import annotations

import json
from typing import Any, Dict

from .io_utils import read_yaml_or_json


DEFAULT_TEMPLATE: Dict[str, Any] = {
    "sections": [
        {"key": "summary", "title": "Summary"},
        {"key": "skills", "title": "Skills"},
        {"key": "experience", "title": "Experience", "max_items": 10},
        {"key": "education", "title": "Education"},
    ]
}


def load_template(path: str | None) -> Dict[str, Any]:
    if not path:
        return DEFAULT_TEMPLATE
    return read_yaml_or_json(path)


def parse_seed_criteria(seed: str | None) -> Dict[str, Any]:
    if not seed:
        return {}
    seed = seed.strip()
    if seed.startswith("{"):
        try:
            return json.loads(seed)
        except Exception:
            return {}
    out: Dict[str, Any] = {}
    # KEY=VALUE pairs comma separated
    for part in seed.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k == "keywords":
            out[k] = [s.strip() for s in v.split(";") if s.strip()] if ";" in v else [s.strip() for s in v.split(" ") if s.strip()]
        else:
            out[k] = v
    return out

