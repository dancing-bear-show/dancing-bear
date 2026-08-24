"""Shared constants used across multiple domains.

This module consolidates duplicate constants that were scattered across
mail, calendars, phone, and apple_music modules.
"""

from __future__ import annotations

import configparser
import os
from typing import Iterable

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

    _cred_ini = "credentials.ini"
    for root in _config_roots():
        paths.append(os.path.join(root, _cred_ini))

    # Dedupe while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p and p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


IniSections = dict[str, dict[str, str]]


def _parse_ini_file(path: str) -> IniSections | None:
    """Parse one INI file into a plain dict; return None if unreadable.

    ConfigParser.read() swallows open/permission errors and reports which
    files it actually parsed, so the return value is checked: an unreadable
    file must be treated as absent rather than as an empty config, or it
    would shadow later readable files in the search order.
    """
    cp = configparser.ConfigParser(interpolation=None)
    try:
        parsed_files = cp.read(path)
    except Exception:  # nosec B110 - malformed ini is treated as absent
        return None
    if not parsed_files:
        return None
    return {section: dict(cp.items(section)) for section in cp.sections()}


def _ini_satisfies(
    parsed: IniSections,
    require_section: str | None,
    require_option: str | None,
) -> bool:
    """Return True when parsed INI content meets the caller's requirements."""
    if require_section is None:
        return True
    section = parsed.get(require_section)
    if section is None:
        return False
    return require_option is None or require_option in section


def _read_ini_candidate(
    path: str,
    require_section: str | None,
    require_option: str | None,
) -> tuple[str, IniSections] | None:
    """Read and validate one candidate path. Returns (expanded_path, sections) or None."""
    if not path:
        return None
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        return None
    parsed = _parse_ini_file(expanded)
    if parsed is None:
        return None
    if not _ini_satisfies(parsed, require_section, require_option):
        return None
    return expanded, parsed


def read_credential_ini_first(
    explicit: str | None = None,
    search_paths: Iterable[str] | None = None,
    require_section: str | None = None,
    require_option: str | None = None,
) -> tuple[str | None, IniSections]:
    """Read credentials INI from the first matching path.

    Returns ``(path, sections)`` for the first readable file found, or
    ``(None, {})`` when none match.

    When ``require_section`` is given, files lacking that section are skipped
    and the search continues, so an empty or unrelated file earlier in the
    search order does not shadow a later one that actually defines the
    profile. ``require_option`` narrows this further to files whose
    ``require_section`` also defines that key. Without either, the first
    readable file wins outright.
    """
    if require_option is not None and require_section is None:
        raise ValueError("require_option requires require_section")
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    candidates.extend(credential_ini_paths() if search_paths is None else search_paths)

    for path in candidates:
        found = _read_ini_candidate(path, require_section, require_option)
        if found is not None:
            return found
    return None, {}


def read_credential_ini_merged(
    search_paths: Iterable[str] | None = None,
) -> IniSections:
    """Read and merge credentials INI across every existing path.

    Sections are merged key-by-key with **first path winning** per key, so an
    earlier file's value is never overwritten by a later one, but a later file
    can supply keys the earlier one omitted. Unreadable files are skipped.

    Use this when configuration is legitimately spread across locations
    (e.g. a legacy path plus a preferred one).
    """
    merged: IniSections = {}
    paths = credential_ini_paths() if search_paths is None else search_paths
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        parsed = _parse_ini_file(path)
        if parsed is None:
            continue
        for section, values in parsed.items():
            target = merged.setdefault(section, {})
            for key, value in values.items():
                target.setdefault(key, value)
    return merged


# -----------------------------------------------------------------------------
# Microsoft Graph API
# -----------------------------------------------------------------------------

GRAPH_API_URL = "https://graph.microsoft.com/v1.0"
GRAPH_DEFAULT_SCOPE = "https://graph.microsoft.com/.default"

GRAPH_API_SCOPES = [
    "Mail.ReadWrite",
    "Mail.ReadWrite.Shared",
    "MailboxSettings.ReadWrite",
    "Calendars.ReadWrite",
]

# Default token cache path for Outlook/MSAL
DEFAULT_OUTLOOK_TOKEN_CACHE = ".cache/.msal_token.json"  # noqa: S105  # nosec B105 - file path, not a secret


# -----------------------------------------------------------------------------
# HTTP and timeouts
# -----------------------------------------------------------------------------

# Default timeout for HTTP requests: (connect_seconds, read_seconds)
DEFAULT_REQUEST_TIMEOUT: tuple[int, int] = (10, 30)


# -----------------------------------------------------------------------------
# Date/time formatting
# -----------------------------------------------------------------------------

# ISO time suffixes for full-day range queries
DAY_START_TIME = "T00:00:00"
DAY_END_TIME = "T23:59:59"

# strftime formats for ISO datetime
FMT_DATETIME = "%Y-%m-%dT%H:%M"
FMT_DATETIME_SEC = "%Y-%m-%dT%H:%M:%S"
FMT_DAY_START = "%Y-%m-%dT00:00:00"
FMT_DAY_END = "%Y-%m-%dT23:59:59"
