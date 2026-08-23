"""Helper utilities for accounts commands."""
from __future__ import annotations

from typing import Iterable

from core.cli_errors import UsageError

from ..config_resolver import (
    default_gmail_credentials_path,
    default_gmail_token_path,
    expand_path,
)
from core.yamlio import load_config


def _lazy_gmail_client():
    """Lazy import of GmailClient to avoid import-time dependencies."""
    from ..gmail_api import GmailClient
    return GmailClient


def load_accounts(path: str) -> list[dict]:
    """Load accounts from a YAML config file."""
    cfg = load_config(path)
    accts = cfg.get("accounts") or []
    return [a for a in accts if isinstance(a, dict)]


def iter_accounts(accts: list[dict], names: str | None) -> Iterable[dict]:
    """Iterate over accounts, optionally filtering by comma-separated names."""
    allow = None
    if names:
        allow = {n.strip() for n in names.split(',') if n.strip()}
    for a in accts:
        if allow and a.get("name") not in allow:
            continue
        yield a


def _outlook_client_kwargs(acc: dict) -> dict:
    """Extract and validate Outlook client-construction kwargs from an account dict."""
    client_id = acc.get("client_id") or acc.get("application_id") or acc.get("credentials")
    if not client_id:
        raise SystemExit(f"Outlook account {acc.get('name')} missing client_id")
    return {
        "client_id": client_id,
        "tenant": acc.get("tenant") or "consumers",
        "token_path": expand_path(acc.get("token")),
        "cache_dir": acc.get("cache"),
    }


def build_client_for_account(acc: dict):
    """Build a raw client for an account (GmailClient or OutlookClient)."""
    provider = str(acc.get("provider") or "").lower()
    if provider == "gmail":
        gmail_client_cls = _lazy_gmail_client()
        creds = expand_path(acc.get("credentials") or default_gmail_credentials_path())
        token = expand_path(acc.get("token") or default_gmail_token_path())
        return gmail_client_cls(
            credentials_path=creds,
            token_path=token,
            cache_dir=acc.get("cache"),
        )
    if provider == "outlook":
        try:
            from core.outlook import OutlookClient  # type: ignore
        except Exception as e:
            raise SystemExit(f"Outlook provider unavailable: {e}")
        return OutlookClient(**_outlook_client_kwargs(acc))
    raise SystemExit(f"Unsupported provider: {provider or '<missing>'} for account {acc.get('name')}")


def require_provider_capability(provider, capability: str, acc: dict) -> None:
    """Raise UsageError if provider does not support the given capability.

    Uses provider.capabilities() (returns set[str]) to guard capability-specific
    pipelines at the CLI layer, replacing per-call string-branch checks.

    Args:
        provider: A BaseProvider instance with a capabilities() method.
        capability: The capability key to require (e.g. 'filters', 'labels').
        acc: The account dict (used in the error message for context).
    """
    if capability not in provider.capabilities():
        name = acc.get("name") or acc.get("provider") or "unknown"
        raise UsageError(
            f"Provider for account '{name}' does not support '{capability}'. "
            f"Supported: {sorted(provider.capabilities()) or ['none']}"
        )


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
        return OutlookProvider(**_outlook_client_kwargs(acc))
    raise SystemExit(f"Unsupported provider: {provider or '<missing>'} for account {acc.get('name')}")
