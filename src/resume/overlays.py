from __future__ import annotations

from pathlib import Path
from typing import Any

from .io_utils import read_yaml_or_json


# Fields to copy from profile config
_PROFILE_FIELDS = ("name", "headline", "summary", "email", "phone", "location", "website", "linkedin", "github")
_CONTACT_FIELDS = ("email", "phone", "location", "website", "linkedin", "github")

# Overlay file names; used both for loading and legacy-exists checks.
_OVERLAY_NAMES = (
    "profile", "skills_groups", "experience", "interests",
    "presentations", "projects", "languages", "coursework",
    "education", "certifications",
)

# Root of the packaged config tree; anchored to this file, not the CWD.
_PACKAGED_CONFIG_DIR = Path(__file__).parent / "config"


def _validate_profile_name(profile: str) -> None:
    """Reject profile names that could cause path traversal.

    Accepts plain name segments such as ``sample``, ``brian``, ``tech-company``.
    Rejects anything with path separators, ``..``, or a leading ``.``.

    Raises:
        ValueError: On unsafe profile names.
    """
    parts = Path(profile).parts
    if (
        not parts
        or len(parts) != 1
        or parts[0] in (".", "..")
        or parts[0].startswith(".")
    ):
        raise ValueError(
            f"Profile name {profile!r} must be a plain name segment "
            "(no path separators, '..', or leading '.')"
        )


def resolve_profile_dir(profile: str) -> Path | None:
    """Resolve the profile overlay directory, first hit wins.

    Search order:

    1. ``<config_home>/resume/profiles/<profile>`` — private profiles
       (honours ``DANCING_BEAR_CONFIG_HOME`` / ``XDG_CONFIG_HOME``).
    2. CWD ``config/profiles/<profile>`` — backward compat for existing scripts.
    3. ``<package>/config/profiles/<profile>`` — packaged profiles (e.g. ``sample``).

    Args:
        profile: Profile name; must be a plain name segment (validated here).

    Returns:
        First existing directory, or ``None`` when none is found.

    Raises:
        ValueError: If the profile name contains path-traversal characters.
    """
    _validate_profile_name(profile)
    from core.paths import config_home
    for candidate in (
        config_home() / "resume" / "profiles" / profile,
        Path("config") / "profiles" / profile,
        _PACKAGED_CONFIG_DIR / "profiles" / profile,
    ):
        if candidate.is_dir():
            return candidate
    return None


def _searched_dirs(profile: str) -> list[Path]:
    """Return the directories :func:`resolve_profile_dir` would have searched."""
    from core.paths import config_home
    return [
        config_home() / "resume" / "profiles" / profile,
        Path("config") / "profiles" / profile,
        _PACKAGED_CONFIG_DIR / "profiles" / profile,
    ]


def _try_load_from_paths(paths: tuple[Path, ...]) -> dict[str, Any] | None:
    """Try to load YAML/JSON from first existing path."""
    for p in paths:
        if p.exists():
            try:
                return read_yaml_or_json(str(p))
            except Exception:  # nosec B110 - skip malformed/unreadable files
                pass
    return None


def _get_overlay_paths(prof_dir: Path, cfg_dir: Path, profile: str, name: str) -> tuple[Path, Path]:
    """Get new and legacy paths for an overlay file."""
    return prof_dir / f"{name}.yaml", cfg_dir / f"{name}.{profile}.yaml"


def _apply_profile_config(out: dict[str, Any], prof_data: dict[str, Any]) -> None:
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

    for key in ("interests", "presentations", "projects"):
        if isinstance(prof_data.get(key), list):
            out[key] = prof_data[key]


def _load_skills_groups(prof_dir: Path, cfg_dir: Path, profile: str) -> list[Any] | None:
    """Load skills_groups from overlay."""
    paths = _get_overlay_paths(prof_dir, cfg_dir, profile, "skills_groups")
    if (data := _try_load_from_paths(paths)):
        return data.get("groups", [])
    return None


def _load_experience(prof_dir: Path, cfg_dir: Path, profile: str) -> list[Any] | None:
    """Load experience from overlay."""
    paths = _get_overlay_paths(prof_dir, cfg_dir, profile, "experience")
    if (data := _try_load_from_paths(paths)):
        exp_list = data.get("experience") or data.get("roles")
        if isinstance(exp_list, list) and exp_list:
            return exp_list
    return None


def _load_list_overlay(prof_dir: Path, cfg_dir: Path, profile: str, key: str) -> list[Any] | None:
    """Load a simple list overlay (interests, languages, etc.)."""
    paths = _get_overlay_paths(prof_dir, cfg_dir, profile, key)
    if (data := _try_load_from_paths(paths)):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
        if isinstance(data, list):
            return data
    return None


def apply_profile_overlays(data: dict[str, Any], profile: str | None) -> dict[str, Any]:
    """Overlay profile-specific config files onto *data*.

    Locates the profile directory via :func:`resolve_profile_dir` (config_home →
    CWD → packaged), then loads each overlay file in turn.  Legacy flat files
    under CWD ``config/`` (e.g. ``config/profile.<prefix>.yaml``) are still
    checked as a secondary source for each overlay type.

    Args:
        data: Base candidate document (dict).
        profile: Profile name, or ``None`` / empty string for a no-op.

    Returns:
        New dict with overlaid values; *data* is not mutated.

    Raises:
        ValueError: If the profile name contains path-traversal characters.
        CLIError(ExitCode.NOT_FOUND): If the profile is not found in any
            location AND no legacy flat files exist under CWD ``config/``.
    """
    if not profile:
        return data

    _validate_profile_name(profile)

    out = dict(data)
    cfg_dir = Path("config")
    prof_dir = resolve_profile_dir(profile)

    if prof_dir is None:
        # No directory found anywhere.  Before erroring, check whether legacy
        # flat files (config/<name>.<profile>.yaml) exist in the CWD — a user
        # running from the repo root may have only the old layout.
        legacy_found = any(
            (cfg_dir / f"{name}.{profile}.yaml").exists()
            for name in _OVERLAY_NAMES
        )
        if not legacy_found:
            from core.cli_errors import CLIError, ExitCode
            searched = "\n  ".join(str(p) for p in _searched_dirs(profile))
            raise CLIError(
                f"Profile '{profile}' not found. No directory at:\n  {searched}",
                ExitCode.NOT_FOUND,
            )
        # Legacy flat files exist; set prof_dir to the conventional CWD location
        # so _get_overlay_paths can build the new-style path (which won't exist —
        # only the legacy flat files will load).
        prof_dir = cfg_dir / "profiles" / profile

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
    for key in ("interests", "presentations", "projects", "languages", "coursework", "education", "certifications"):
        if (items := _load_list_overlay(prof_dir, cfg_dir, profile, key)):
            out[key] = items

    return out
