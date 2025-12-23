from __future__ import annotations

"""Shared helpers for Outlook pipeline."""

import os
from typing import Optional, Tuple

from core.auth import resolve_outlook_credentials


def norm_label_name_outlook(name: str, mode: str = "join-dash") -> str:
    """Normalize a Gmail-style nested label to an Outlook-compatible name."""
    parts = (name or "").split("/")
    if not parts:
        return name
    if mode == "first":
        return parts[0]
    if mode == "join-colon":
        return ":".join(parts)
    return "-".join(parts)


OUTLOOK_COLOR_NAMES = {
    "preset0", "preset1", "preset2", "preset3", "preset4", "preset5", "preset6", "preset7",
}


def norm_label_color_outlook(color: Optional[dict]) -> Optional[dict]:
    """Normalize a label color for Outlook."""
    if not isinstance(color, dict):
        return None
    name = color.get("name")
    if name and isinstance(name, str):
        return {"name": name}
    return None


def resolve_outlook_args(args) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Resolve Outlook client credentials from args, env, and config files.

    Returns: (client_id, tenant, token_path, cache_dir)
    """
    profile = getattr(args, "profile", None)
    client_id, tenant, token_path = resolve_outlook_credentials(
        profile,
        getattr(args, "client_id", None),
        getattr(args, "tenant", None),
        getattr(args, "token", None),
    )
    cache_dir = getattr(args, "cache_dir", None) or getattr(args, "cache", None)

    if not client_id:
        cfg_path = getattr(args, "accounts_config", None)
        acc_name = getattr(args, "account", None)
        if cfg_path and os.path.exists(cfg_path):
            from ..yamlio import load_config
            accts = (load_config(cfg_path) or {}).get("accounts") or []
            chosen = None
            if acc_name:
                chosen = next((a for a in accts if a.get("name") == acc_name), None)
            if not chosen:
                chosen = next((a for a in accts if (a.get("provider") or "").lower() == "outlook"), None)
            if chosen:
                client_id = chosen.get("client_id") or chosen.get("application_id") or chosen.get("credentials")
                tenant = chosen.get("tenant") or tenant
                token_path = token_path or chosen.get("token")
                cache_dir = chosen.get("cache") or cache_dir

    # Try picking up cache from accounts config even if client_id was set via profile
    if not cache_dir:
        cfg_path = getattr(args, "accounts_config", None)
        acc_name = getattr(args, "account", None)
        if cfg_path and os.path.exists(cfg_path):
            from ..yamlio import load_config
            accts = (load_config(cfg_path) or {}).get("accounts") or []
            chosen = None
            if acc_name:
                chosen = next((a for a in accts if a.get("name") == acc_name), None)
            if not chosen:
                chosen = next((a for a in accts if (a.get("provider") or "").lower() == "outlook"), None)
            if chosen:
                cache_dir = chosen.get("cache") or cache_dir

    return client_id, tenant, token_path, cache_dir


def get_outlook_client(args):
    """Get an authenticated OutlookClient from args.

    Returns: (client, error_code) - client is None if error, error_code is 0 if success.
    """
    try:
        from ..outlook_api import OutlookClient
    except Exception as e:
        print(f"Outlook features unavailable: {e}")
        return None, 1

    client_id, tenant, token_path, cache_dir = resolve_outlook_args(args)
    if not client_id:
        print("Missing --client-id. Set MAIL_ASSISTANT_OUTLOOK_CLIENT_ID, or provide --accounts-config with an Outlook account.")
        return None, 2

    client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token_path, cache_dir=cache_dir)
    client.authenticate()
    return client, 0
