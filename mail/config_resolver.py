from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple, Optional, Dict


def _config_roots() -> list[str]:
    roots: list[str] = []
    env_cfg = os.environ.get("CREDENTIALS")
    if env_cfg:
        roots.append(os.path.expanduser(os.path.dirname(env_cfg)))
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        roots.append(os.path.expanduser(xdg))
    roots.append(os.path.expanduser("~/.config"))
    return roots


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for p in paths:
        if not p:
            continue
        if p in seen:
            continue
        seen.add(p)
        ordered.append(p)
    return ordered


# Support new defaults plus legacy paths; merge values where possible.
_INI_PATHS = _dedupe([
    os.path.expanduser(os.environ.get("CREDENTIALS", "")) if os.environ.get("CREDENTIALS") else "",
    *(os.path.join(root, "credentials.ini") for root in _config_roots()),
    *(os.path.join(root, "sre-utils", "credentials.ini") for root in _config_roots()),
    *(os.path.join(root, "sreutils", "credentials.ini") for root in _config_roots()),
    os.path.expanduser("~/.sre-utils/credentials.ini"),
])
_SECTION = "mail_assistant"
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
        except Exception:
            continue
        for section in cp.sections():
            sec = merged_sections.setdefault(section, {})
            for k, v in cp.items(section):
                sec.setdefault(k, v)
    return merged_sections


def _write_ini(
    creds: Optional[str],
    token: Optional[str],
    *,
    profile: Optional[str] = None,
    outlook_client_id: Optional[str] = None,
    tenant: Optional[str] = None,
    outlook_token: Optional[str] = None,
) -> None:
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
    section = _SECTION if not profile else f"{_SECTION}.{profile}"
    if not cp.has_section(section):
        cp.add_section(section)
    if creds:
        cp.set(section, "credentials", str(creds))
    if token:
        cp.set(section, "token", str(token))
    if outlook_client_id:
        cp.set(section, "outlook_client_id", str(outlook_client_id))
    if tenant:
        cp.set(section, "tenant", str(tenant))
    if outlook_token:
        cp.set(section, "outlook_token", str(outlook_token))
    Path(os.path.dirname(dest)).mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        cp.write(fh)


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
    *,
    profile: Optional[str],
    credentials: Optional[str] = None,
    token: Optional[str] = None,
    outlook_client_id: Optional[str] = None,
    tenant: Optional[str] = None,
    outlook_token: Optional[str] = None,
) -> None:
    """Persist any provided settings to the INI under the given profile.

    Only provided values are written; others are left unchanged.
    """
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

    Looks under section [mail_assistant] for key 'outlook_client_id' or
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
