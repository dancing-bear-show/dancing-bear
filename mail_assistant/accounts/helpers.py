from __future__ import annotations

"""Helper utilities for accounts commands."""

from typing import Iterable, Optional

from ..config_resolver import (
    default_gmail_credentials_path,
    default_gmail_token_path,
    expand_path,
)
from ..yamlio import load_config


def _lazy_gmail_client():
    """Lazy import of GmailClient to avoid import-time dependencies."""
    from ..gmail_api import GmailClient
    return GmailClient


def load_accounts(path: str) -> list[dict]:
    """Load accounts from a YAML config file."""
    cfg = load_config(path)
    accts = cfg.get("accounts") or []
    return [a for a in accts if isinstance(a, dict)]


def iter_accounts(accts: list[dict], names: Optional[str]) -> Iterable[dict]:
    """Iterate over accounts, optionally filtering by comma-separated names."""
    allow = None
    if names:
        allow = {n.strip() for n in names.split(',') if n.strip()}
    for a in accts:
        if allow and a.get("name") not in allow:
            continue
        yield a


def build_client_for_account(acc: dict):
    """Build a raw client for an account (GmailClient or OutlookClient)."""
    provider = str(acc.get("provider") or "").lower()
    if provider == "gmail":
        GmailClient = _lazy_gmail_client()
        creds = expand_path(acc.get("credentials") or default_gmail_credentials_path())
        token = expand_path(acc.get("token") or default_gmail_token_path())
        return GmailClient(
            credentials_path=creds,
            token_path=token,
            cache_dir=acc.get("cache"),
        )
    if provider == "outlook":
        try:
            from ..outlook_api import OutlookClient  # type: ignore
        except Exception as e:
            raise SystemExit(f"Outlook provider unavailable: {e}")
        client_id = acc.get("client_id") or acc.get("application_id") or acc.get("credentials")
        if not client_id:
            raise SystemExit(f"Outlook account {acc.get('name')} missing client_id")
        tenant = acc.get("tenant") or "consumers"
        token_path = expand_path(acc.get("token"))
        return OutlookClient(client_id=client_id, tenant=tenant, token_path=token_path, cache_dir=acc.get("cache"))
    raise SystemExit(f"Unsupported provider: {provider or '<missing>'} for account {acc.get('name')}")


def build_provider_for_account(acc: dict):
    """Return a provider-like object for an account.

    For Gmail, returns a GmailProvider adapter. For Outlook, returns the
    existing OutlookProvider which already exposes a compatible surface for
    labels/filters used by accounts commands.
    """
    provider = str(acc.get("provider") or "").lower()
    if provider == "gmail":
        from ..providers.gmail import GmailProvider
        creds = expand_path(acc.get("credentials") or default_gmail_credentials_path())
        token = expand_path(acc.get("token") or default_gmail_token_path())
        return GmailProvider(
            credentials_path=creds,
            token_path=token,
            cache_dir=acc.get("cache"),
        )
    if provider == "outlook":
        try:
            from ..providers.outlook import OutlookProvider  # type: ignore
        except Exception as e:
            raise SystemExit(f"Outlook provider unavailable: {e}")
        client_id = acc.get("client_id") or acc.get("application_id") or acc.get("credentials")
        if not client_id:
            raise SystemExit(f"Outlook account {acc.get('name')} missing client_id")
        tenant = acc.get("tenant") or "consumers"
        token_path = expand_path(acc.get("token"))
        return OutlookProvider(client_id=client_id, tenant=tenant, token_path=token_path, cache_dir=acc.get("cache"))
    raise SystemExit(f"Unsupported provider: {provider or '<missing>'} for account {acc.get('name')}")
