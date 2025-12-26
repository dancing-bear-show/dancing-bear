"""Shared config helpers for Apple Music assistant."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Dict, Tuple

from core.constants import credential_ini_paths

DEFAULT_PROFILE = "musickit.personal"


def load_profile(profile: str, explicit_path: str | None) -> Tuple[Path | None, Dict[str, str]]:
    paths = []
    if explicit_path:
        paths.append(explicit_path)
    paths.extend(credential_ini_paths())

    parser = configparser.ConfigParser(interpolation=None)
    for path in paths:
        expanded = os.path.expanduser(path)
        if os.path.isfile(expanded):
            parser.read(expanded)
            if parser.has_section(profile):
                return Path(expanded), dict(parser[profile])
    return None, {}
