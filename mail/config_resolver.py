from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Optional, Dict

from core.constants import credential_ini_paths, _config_roots


# Use shared credential paths from core.constants
_INI_PATHS = credential_ini_paths()
_SECTION = "mail"
_DEFAULT_CONFIG_DIR = _config_roots()[0]
DEFAULT_GMAIL_CREDENTIALS = os.path.join(_DEFAULT_CONFIG_DIR, "credentials.json")
DEFAULT_GMAIL_TOKEN = os.path.join(_DEFAULT_CONFIG_DIR, "token.json")
DEFAULT_OUTLOOK_TOKEN = os.path.join(_DEFAULT_CONFIG_DIR, "outlook_token.json")
DEFAULT_OUTLOOK_FLOW = os.path.join(_DEFAULT_CONFIG_DIR, "msal_flow.json")


def expand_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return path
    return os.path.expanduser(path)


def default_gmail_credentials_path() -> str:
    return DEFAULT_GMAIL_CREDENTIALS


def default_gmail_token_path() -> str:
    return DEFAULT_GMAIL_TOKEN


def default_outlook_token_path() -> str:
    return DEFAULT_OUTLOOK_TOKEN


def default_outlook_flow_path() -> str:
    return DEFAULT_OUTLOOK_FLOW


@dataclass
class ProfileSettings:
    """Settings for a mail profile to persist to INI configuration."""

    profile: Optional[str] = None
    credentials: Optional[str] = None
    token: Optional[str] = None
    outlook_client_id: Optional[str] = None
    tenant: Optional[str] = None
    outlook_token: Optional[str] = None


def _read_ini() -> Dict[str, Dict[str, str]]:
    try:
        import configparser
    except Exception:
        return {}
    merged_sections: Dict[str, Dict[str, str]] = {}
    # Prefer legacy (hyphen) values first, then fill missing from preferred path
    for p in _INI_PATHS:
        if not os.path.exists(p):
            continue
        cp = configparser.ConfigParser()
        try:
            cp.read(p)
        except Exception:  # nosec B112 - skip on error
            continue
        for section in cp.sections():
            sec = merged_sections.setdefault(section, {})
            for k, v in cp.items(section):
                sec.setdefault(k, v)
    return merged_sections


def _write_ini_from_settings(settings: ProfileSettings) -> None:
    """Write profile settings to INI configuration file."""
    try:
        import configparser
    except Exception:
        return
    # Choose destination: write back to the first existing path, else to legacy (with hyphen)
    dest = next((p for p in _INI_PATHS if os.path.exists(p)), _INI_PATHS[0])
    cp = configparser.ConfigParser()
    if os.path.exists(dest):
        try:
            cp.read(dest)
        except Exception:
            cp = configparser.ConfigParser()
    section = _SECTION if not settings.profile else f"{_SECTION}.{settings.profile}"
    if not cp.has_section(section):
        cp.add_section(section)
    if settings.credentials:
        cp.set(section, "credentials", str(settings.credentials))
    if settings.token:
        cp.set(section, "token", str(settings.token))
    if settings.outlook_client_id:
        cp.set(section, "outlook_client_id", str(settings.outlook_client_id))
    if settings.tenant:
        cp.set(section, "tenant", str(settings.tenant))
    if settings.outlook_token:
        cp.set(section, "outlook_token", str(settings.outlook_token))
    Path(os.path.dirname(dest)).mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        cp.write(fh)


def _write_ini(
    creds: Optional[str],
    token: Optional[str],
    *,
    profile: Optional[str] = None,
    outlook_client_id: Optional[str] = None,
    tenant: Optional[str] = None,
    outlook_token: Optional[str] = None,
) -> None:
    """Write profile settings to INI (backward-compatible wrapper).

    Prefer using persist_profile_settings() for new code.
    """
    settings = ProfileSettings(
        profile=profile,
        credentials=creds,
        token=token,
        outlook_client_id=outlook_client_id,
        tenant=tenant,
        outlook_token=outlook_token,
    )
    _write_ini_from_settings(settings)


def resolve_paths(
    *,
    arg_credentials: Optional[str],
    arg_token: Optional[str],
) -> Tuple[str, str]:
    ini = _read_ini()
    # Use default section; profile-aware variant below
    sec = ini.get(_SECTION, {})
    creds = arg_credentials or sec.get("credentials") or DEFAULT_GMAIL_CREDENTIALS
    token = arg_token or sec.get("token") or DEFAULT_GMAIL_TOKEN
    return expand_path(creds), expand_path(token)


def resolve_paths_profile(
    *,
    arg_credentials: Optional[str],
    arg_token: Optional[str],
    profile: Optional[str],
) -> Tuple[str, str]:
    if profile:
        sec = _get_ini_section(profile)
        creds = arg_credentials or sec.get("credentials") or DEFAULT_GMAIL_CREDENTIALS
        token = arg_token or sec.get("token") or DEFAULT_GMAIL_TOKEN
        return expand_path(creds), expand_path(token)
    return resolve_paths(arg_credentials=arg_credentials, arg_token=arg_token)


def persist_if_provided(*, arg_credentials: Optional[str], arg_token: Optional[str], profile: Optional[str] = None) -> None:
    # Persist only when caller explicitly provided values (so we don't overwrite
    # ini with defaults).
    if arg_credentials or arg_token:
        _write_ini(arg_credentials, arg_token, profile=profile)


def persist_profile_settings(
    settings: Optional[ProfileSettings] = None,
    *,
    profile: Optional[str] = None,
    credentials: Optional[str] = None,
    token: Optional[str] = None,
    outlook_client_id: Optional[str] = None,
    tenant: Optional[str] = None,
    outlook_token: Optional[str] = None,
) -> None:
    """Persist profile settings to the INI configuration file.

    Args:
        settings: ProfileSettings object (preferred for new code)
        profile: Profile name (for backward compatibility)
        credentials: Gmail credentials path (for backward compatibility)
        token: Gmail token path (for backward compatibility)
        outlook_client_id: Outlook client ID (for backward compatibility)
        tenant: Outlook tenant (for backward compatibility)
        outlook_token: Outlook token path (for backward compatibility)

    Only provided values are written; others are left unchanged.
    """
    if settings is not None:
        _write_ini_from_settings(settings)
    else:
        # Backward compatibility: construct settings from individual parameters
        _write_ini(
            credentials,
            token,
            profile=profile,
            outlook_client_id=outlook_client_id,
            tenant=tenant,
            outlook_token=outlook_token,
        )


def _get_ini_section(profile: Optional[str]) -> Dict[str, str]:
    ini = _read_ini()
    if profile:
        sec = ini.get(f"{_SECTION}.{profile}")
        if sec:
            return sec
    return ini.get(_SECTION, {})


def get_outlook_client_id(profile: Optional[str] = None) -> Optional[str]:
    """Return Outlook (Microsoft Graph) client_id from INI if present.

    Looks under section [mail] for key 'outlook_client_id' or
    a generic 'client_id'. Returns None if not found.
    """
    sec = _get_ini_section(profile)
    return sec.get("outlook_client_id") or sec.get("client_id")


def get_outlook_tenant(profile: Optional[str] = None) -> Optional[str]:
    sec = _get_ini_section(profile)
    return sec.get("tenant")


def get_outlook_token_path(profile: Optional[str] = None) -> Optional[str]:
    sec = _get_ini_section(profile)
    # Allow storing outlook token cache path as 'outlook_token' or reuse generic 'token'
    token = sec.get("outlook_token") or sec.get("token") or DEFAULT_OUTLOOK_TOKEN
    return expand_path(token)
