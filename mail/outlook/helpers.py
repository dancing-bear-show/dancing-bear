"""Shared helpers for Outlook pipeline."""
from __future__ import annotations

import os
from typing import Optional, Tuple

from core.auth import resolve_outlook_credentials


def norm_label_name_outlook(name: Optional[str], mode: str = "join-dash") -> str:
    """Normalize a Gmail-style nested label to an Outlook-compatible name."""
    parts = (name or "").split("/")
    if not parts:
        return name or ""
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


def _load_accounts_config(cfg_path: str) -> list:
    """Load accounts from config file if it exists."""
    if not (cfg_path and os.path.exists(cfg_path)):
        return []
    from ..yamlio import load_config
    return (load_config(cfg_path) or {}).get("accounts") or []


def _find_outlook_account(accounts: list, account_name: Optional[str]) -> Optional[dict]:
    """Find an Outlook account by name or default to first Outlook account."""
    if not accounts:
        return None
    if account_name:
        chosen = next((a for a in accounts if a.get("name") == account_name), None)
        if chosen:
            return chosen
    return next((a for a in accounts if (a.get("provider") or "").lower() == "outlook"), None)


def _extract_credentials_from_account(account: Optional[dict], client_id: Optional[str],
                                      tenant: Optional[str], token_path: Optional[str],
                                      cache_dir: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Extract credentials from account config, falling back to provided values."""
    if not account:
        return client_id, tenant, token_path, cache_dir

    new_client_id = account.get("client_id") or account.get("application_id") or account.get("credentials")
    new_tenant = account.get("tenant")
    new_token = account.get("token")
    new_cache = account.get("cache")

    return (
        new_client_id or client_id,
        new_tenant or tenant,
        token_path or new_token,
        new_cache or cache_dir
    )


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

    cfg_path = getattr(args, "accounts_config", None)
    acc_name = getattr(args, "account", None)
    accounts = _load_accounts_config(cfg_path)

    if not client_id:
        chosen = _find_outlook_account(accounts, acc_name)
        client_id, tenant, token_path, cache_dir = _extract_credentials_from_account(
            chosen, client_id, tenant, token_path, cache_dir
        )

    # Try picking up cache from accounts config even if client_id was set via profile
    if not cache_dir:
        chosen = _find_outlook_account(accounts, acc_name)
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
