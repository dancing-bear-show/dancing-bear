from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .io_utils import read_yaml_or_json


def apply_profile_overlays(data: Dict[str, Any], profile: str | None) -> Dict[str, Any]:
    """Overlay profile-specific config files under config/ onto data.

    Supports the following optional files when present (YAML/JSON):
    - profile.<profile>.yaml: top-level contact/title fields and optional lists
    - skills_groups.<profile>.yaml: grouped skills (key: groups)
    - experience.<profile>.yaml: canonical job history (keys: experience|roles)
    - interests.<profile>.yaml, presentations.<profile>.yaml,
      languages.<profile>.yaml, coursework.<profile>.yaml: list values or
      top-level dict with the list key.
    """
    if not profile:
        return data

    out = dict(data)
    cfg_dir = Path("config")
    prof_dir = cfg_dir / "profiles" / str(profile)

    # Profile (new structured location preferred)
    prof_cfg_new = prof_dir / "profile.yaml"
    prof_cfg_old = cfg_dir / f"profile.{profile}.yaml"
    for prof_cfg in (prof_cfg_new, prof_cfg_old):
        if prof_cfg.exists():
            try:
                prof_data = read_yaml_or_json(str(prof_cfg))
                for k in ("name", "headline", "summary", "email", "phone", "location", "website", "linkedin", "github"):
                    v = prof_data.get(k)
                    if v:
                        out[k] = v
                if isinstance(prof_data.get("contact"), dict):
                    for k in ("email", "phone", "location", "website", "linkedin", "github"):
                        v = prof_data["contact"].get(k)
                        if v and not out.get(k):
                            out[k] = v
                    if isinstance(prof_data["contact"].get("links"), list):
                        out["links"] = prof_data["contact"]["links"]
                if isinstance(prof_data.get("interests"), list):
                    out["interests"] = prof_data["interests"]
                if isinstance(prof_data.get("presentations"), list):
                    out["presentations"] = prof_data["presentations"]
                break
            except Exception:
                pass  # nosec B110 - profile load failure

    # Skills groups
    skills_groups_new = prof_dir / "skills_groups.yaml"
    skills_groups_old = cfg_dir / f"skills_groups.{profile}.yaml"
    for skills_groups in (skills_groups_new, skills_groups_old):
        if skills_groups.exists():
            try:
                out["skills_groups"] = read_yaml_or_json(str(skills_groups)).get("groups", [])
                break
            except Exception:
                pass  # nosec B110 - skills_groups load failure

    # Experience
    exp_cfg_new = prof_dir / "experience.yaml"
    exp_cfg_old = cfg_dir / f"experience.{profile}.yaml"
    for exp_cfg in (exp_cfg_new, exp_cfg_old):
        if exp_cfg.exists():
            try:
                exp_data = read_yaml_or_json(str(exp_cfg))
                exp_list = exp_data.get("experience") or exp_data.get("roles")
                if isinstance(exp_list, list) and exp_list:
                    out["experience"] = exp_list
                break
            except Exception:
                pass  # nosec B110 - experience load failure

    # Simple list overlays
    for key in ("interests", "presentations", "languages", "coursework", "education", "certifications"):
        p_new = prof_dir / f"{key}.yaml"
        p_old = cfg_dir / f"{key}.{profile}.yaml"
        for p in (p_new, p_old):
            if p.exists():
                try:
                    d = read_yaml_or_json(str(p))
                    if isinstance(d, dict) and isinstance(d.get(key), list):
                        out[key] = d.get(key)
                    elif isinstance(d, list):
                        out[key] = d
                    break
                except Exception:
                    pass  # nosec B110 - overlay load failure

    return out
