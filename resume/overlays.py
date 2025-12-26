from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .io_utils import read_yaml_or_json


# Fields to copy from profile config
_PROFILE_FIELDS = ("name", "headline", "summary", "email", "phone", "location", "website", "linkedin", "github")
_CONTACT_FIELDS = ("email", "phone", "location", "website", "linkedin", "github")


def _try_load_from_paths(paths: Tuple[Path, ...]) -> Optional[Dict[str, Any]]:
    """Try to load YAML/JSON from first existing path."""
    for p in paths:
        if p.exists():
            try:
                return read_yaml_or_json(str(p))
            except Exception:
                pass  # nosec B110
    return None


def _get_overlay_paths(prof_dir: Path, cfg_dir: Path, profile: str, name: str) -> Tuple[Path, Path]:
    """Get new and legacy paths for an overlay file."""
    return prof_dir / f"{name}.yaml", cfg_dir / f"{name}.{profile}.yaml"


def _apply_profile_config(out: Dict[str, Any], prof_data: Dict[str, Any]) -> None:
    """Apply profile fields and nested contact to output."""
    for k in _PROFILE_FIELDS:
        if (v := prof_data.get(k)):
            out[k] = v

    if isinstance(prof_data.get("contact"), dict):
        contact = prof_data["contact"]
        for k in _CONTACT_FIELDS:
            if (v := contact.get(k)) and not out.get(k):
                out[k] = v
        if isinstance(contact.get("links"), list):
            out["links"] = contact["links"]

    for key in ("interests", "presentations"):
        if isinstance(prof_data.get(key), list):
            out[key] = prof_data[key]


def _load_skills_groups(prof_dir: Path, cfg_dir: Path, profile: str) -> Optional[List[Any]]:
    """Load skills_groups from overlay."""
    paths = _get_overlay_paths(prof_dir, cfg_dir, profile, "skills_groups")
    if (data := _try_load_from_paths(paths)):
        return data.get("groups", [])
    return None


def _load_experience(prof_dir: Path, cfg_dir: Path, profile: str) -> Optional[List[Any]]:
    """Load experience from overlay."""
    paths = _get_overlay_paths(prof_dir, cfg_dir, profile, "experience")
    if (data := _try_load_from_paths(paths)):
        exp_list = data.get("experience") or data.get("roles")
        if isinstance(exp_list, list) and exp_list:
            return exp_list
    return None


def _load_list_overlay(prof_dir: Path, cfg_dir: Path, profile: str, key: str) -> Optional[List[Any]]:
    """Load a simple list overlay (interests, languages, etc.)."""
    paths = _get_overlay_paths(prof_dir, cfg_dir, profile, key)
    if (data := _try_load_from_paths(paths)):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
        if isinstance(data, list):
            return data
    return None


def apply_profile_overlays(data: Dict[str, Any], profile: str | None) -> Dict[str, Any]:
    """Overlay profile-specific config files under config/ onto data."""
    if not profile:
        return data

    out = dict(data)
    cfg_dir = Path("config")
    prof_dir = cfg_dir / "profiles" / str(profile)

    # Profile config
    paths = _get_overlay_paths(prof_dir, cfg_dir, profile, "profile")
    if (prof_data := _try_load_from_paths(paths)):
        _apply_profile_config(out, prof_data)

    # Skills groups
    if (skills := _load_skills_groups(prof_dir, cfg_dir, profile)):
        out["skills_groups"] = skills

    # Experience
    if (exp := _load_experience(prof_dir, cfg_dir, profile)):
        out["experience"] = exp

    # Simple list overlays
    for key in ("interests", "presentations", "languages", "coursework", "education", "certifications"):
        if (items := _load_list_overlay(prof_dir, cfg_dir, profile, key)):
            out[key] = items

    return out
