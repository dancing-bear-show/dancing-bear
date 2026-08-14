"""Shared config helpers for Apple Music assistant."""

from __future__ import annotations

from pathlib import Path

from core.constants import read_credential_ini_first

DEFAULT_PROFILE = "musickit.personal"


def load_profile(profile: str, explicit_path: str | None) -> tuple[Path | None, dict[str, str]]:
    path, sections = read_credential_ini_first(explicit_path, require_section=profile)
    if path is None:
        return None, {}
    return Path(path), sections[profile]
