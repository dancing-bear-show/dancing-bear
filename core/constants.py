"""Shared constants used across multiple domains.

This module consolidates duplicate constants that were scattered across
mail, calendars, phone, apple_music, and metals modules.
"""

from __future__ import annotations

import os
from typing import Tuple

# -----------------------------------------------------------------------------
# Credential paths
# -----------------------------------------------------------------------------

def _config_roots() -> list[str]:
    """Return ordered list of config root directories."""
    roots: list[str] = []
    env_cfg = os.environ.get("CREDENTIALS")
    if env_cfg:
        roots.append(os.path.expanduser(os.path.dirname(env_cfg)))
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        roots.append(os.path.expanduser(xdg))
    roots.append(os.path.expanduser("~/.config"))
    return roots


def credential_ini_paths() -> list[str]:
    """Return ordered list of credential.ini paths to search.

    Used by mail, apple_music, phone, and other modules.
    """
    paths: list[str] = []

    # Environment override first
    env_creds = os.environ.get("CREDENTIALS")
    if env_creds:
        paths.append(os.path.expanduser(env_creds))

    # Standard and legacy paths under each config root
    for root in _config_roots():
        paths.append(os.path.join(root, "credentials.ini"))
        paths.append(os.path.join(root, "sre-utils", "credentials.ini"))
        paths.append(os.path.join(root, "sreutils", "credentials.ini"))

    # Legacy standalone path
    paths.append(os.path.expanduser("~/.sre-utils/credentials.ini"))

    # Dedupe while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p and p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


# -----------------------------------------------------------------------------
# Microsoft Graph API
# -----------------------------------------------------------------------------

GRAPH_API_URL = "https://graph.microsoft.com/v1.0"

GRAPH_API_SCOPES = [
    "Mail.ReadWrite",
    "Mail.ReadWrite.Shared",
    "MailboxSettings.ReadWrite",
    "Calendars.ReadWrite",
]

# Default token cache path for Outlook/MSAL
DEFAULT_OUTLOOK_TOKEN_CACHE = ".cache/.msal_token.json"


# -----------------------------------------------------------------------------
# HTTP and timeouts
# -----------------------------------------------------------------------------

# Default timeout for HTTP requests: (connect_seconds, read_seconds)
DEFAULT_REQUEST_TIMEOUT: Tuple[int, int] = (10, 30)


# -----------------------------------------------------------------------------
# CLI defaults
# -----------------------------------------------------------------------------

DEFAULT_DAYS_BACK = 30
DEFAULT_DAYS_FORWARD = 180
DEFAULT_PAGE_SIZE = 500
