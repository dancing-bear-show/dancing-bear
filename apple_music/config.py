"""Shared config helpers for Apple Music assistant."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Dict, Tuple

DEFAULT_PROFILE = "musickit.personal"
DEFAULT_CREDENTIAL_PATHS = [
    lambda: os.environ.get("CREDENTIALS"),
    lambda: os.path.join(os.environ.get("XDG_CONFIG_HOME", ""), "credentials.ini")
    if os.environ.get("XDG_CONFIG_HOME")
    else None,
    lambda: os.path.expanduser("~/.config/credentials.ini"),
    lambda: os.path.join(os.environ.get("XDG_CONFIG_HOME", ""), "sre-utils", "credentials.ini")
    if os.environ.get("XDG_CONFIG_HOME")
    else None,
    lambda: os.path.expanduser("~/.config/sre-utils/credentials.ini"),
    lambda: os.path.expanduser("~/.config/sreutils/credentials.ini"),
    lambda: os.path.expanduser("~/.sre-utils/credentials.ini"),
]


def load_profile(profile: str, explicit_path: str | None) -> Tuple[Path | None, Dict[str, str]]:
    paths = []
    if explicit_path:
        paths.append(explicit_path)
    for resolver in DEFAULT_CREDENTIAL_PATHS:
        candidate = resolver()
        if candidate:
            paths.append(candidate)

    parser = configparser.ConfigParser(interpolation=None)
    for path in paths:
        expanded = os.path.expanduser(path)
        if os.path.isfile(expanded):
            parser.read(expanded)
            if parser.has_section(profile):
                return Path(expanded), dict(parser[profile])
    return None, {}
