"""Shared auth/context factories for Gmail and Outlook."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class OutlookServiceArgsConfig:
    """Configuration for extracting Outlook service arguments from args object."""

    profile_attr: str = "profile"
    client_id_attr: str = "client_id"
    tenant_attr: str = "tenant"
    token_attr: str = "token"  # noqa: S107 - attribute name, not a secret


@dataclass
class GmailServiceArgsConfig:
    """Configuration for extracting Gmail service arguments from args object."""

    profile_attr: str = "profile"
    credentials_attr: str = "credentials"
    token_attr: str = "token"  # noqa: S107 - attribute name, not a secret
    cache_attr: str = "cache"


def resolve_gmail_credentials(
    profile: Optional[str],
    credentials_path: Optional[str],
    token_path: Optional[str],
) -> Tuple[str, str]:
    """Return (credentials_path, token_path) folded over env/profile defaults.

    Resolution order: CLI arg > environment > INI profile > default paths.
    """
    import os
    from mail.config_resolver import (
        resolve_paths_profile,
        DEFAULT_GMAIL_CREDENTIALS,
        DEFAULT_GMAIL_TOKEN,
    )

    # Use config_resolver for profile-aware resolution
    resolved_creds, resolved_token = resolve_paths_profile(
        arg_credentials=credentials_path,
        arg_token=token_path,
        profile=profile,
    )

    # Environment variable fallbacks
    if not resolved_creds or resolved_creds == DEFAULT_GMAIL_CREDENTIALS:
        env_creds = os.environ.get("MAIL_ASSISTANT_GMAIL_CREDENTIALS")
        if env_creds:
            resolved_creds = os.path.expanduser(env_creds)

    if not resolved_token or resolved_token == DEFAULT_GMAIL_TOKEN:
        env_token = os.environ.get("MAIL_ASSISTANT_GMAIL_TOKEN")
        if env_token:
            resolved_token = os.path.expanduser(env_token)

    return resolved_creds, resolved_token


def resolve_outlook_credentials(
    profile: Optional[str],
    client_id: Optional[str],
    tenant: Optional[str],
    token_path: Optional[str],
):
    """Return (client_id, tenant, token_path) folded over env/profile defaults."""
    import os
    from mail.config_resolver import (
        get_outlook_client_id,
        get_outlook_tenant,
        get_outlook_token_path,
    )

    resolved_client = (
        client_id
        or os.environ.get("MAIL_ASSISTANT_OUTLOOK_CLIENT_ID")
        or get_outlook_client_id(profile)
    )
    resolved_tenant = (
        tenant
        or os.environ.get("MAIL_ASSISTANT_OUTLOOK_TENANT")
        or get_outlook_tenant(profile)
        or "consumers"
    )
    resolved_token = token_path or get_outlook_token_path(profile)
    if resolved_token:
        resolved_token = os.path.expanduser(resolved_token)
    return resolved_client, resolved_tenant, resolved_token


def build_outlook_service(
    profile: Optional[str] = None,
    client_id: Optional[str] = None,
    tenant: Optional[str] = None,
    token_path: Optional[str] = None,
    context_cls=None,
    service_cls=None,
):
    """Instantiate OutlookService with a shared resolver."""
    from calendars.context import OutlookContext as DefaultContext
    from calendars.outlook_service import OutlookService as DefaultService

    context_cls = context_cls or DefaultContext
    service_cls = service_cls or DefaultService
    cid, ten, tok = resolve_outlook_credentials(profile, client_id, tenant, token_path)
    return service_cls(context_cls(client_id=cid, tenant=ten, token_path=tok, profile=profile))


def build_gmail_service(
    profile: Optional[str] = None,
    cache_dir: Optional[str] = None,
    credentials_path: Optional[str] = None,
    token_path: Optional[str] = None,
    service_cls=None,
):
    """Instantiate a GmailService (via existing CLI helper resolution)."""
    from types import SimpleNamespace
    from calendars.gmail_service import GmailService as DefaultService  # reuse existing helper

    service_cls = service_cls or DefaultService
    args = SimpleNamespace(
        profile=profile,
        credentials=credentials_path,
        token=token_path,
        cache=cache_dir,
    )
    svc = service_cls.from_args(args)
    svc.authenticate()
    return svc


def build_outlook_service_from_args(
    args,
    config: Optional[OutlookServiceArgsConfig] = None,
    context_cls=None,
    service_cls=None,
):
    """Instantiate an OutlookService using argparse-like args.

    Args:
        args: Argparse namespace or object with service configuration attributes
        config: Optional configuration for attribute names (uses defaults if None)
        context_cls: Optional custom context class
        service_cls: Optional custom service class

    Returns:
        Configured OutlookService instance
    """
    cfg = config or OutlookServiceArgsConfig()
    return build_outlook_service(
        profile=getattr(args, cfg.profile_attr, None),
        client_id=getattr(args, cfg.client_id_attr, None),
        tenant=getattr(args, cfg.tenant_attr, None),
        token_path=getattr(args, cfg.token_attr, None),
        context_cls=context_cls,
        service_cls=service_cls,
    )


def build_gmail_service_from_args(
    args,
    config: Optional[GmailServiceArgsConfig] = None,
    service_cls=None,
):
    """Instantiate a GmailService using argparse-like args.

    Args:
        args: Argparse namespace or object with service configuration attributes
        config: Optional configuration for attribute names (uses defaults if None)
        service_cls: Optional custom service class

    Returns:
        Authenticated GmailService instance
    """
    cfg = config or GmailServiceArgsConfig()
    return build_gmail_service(
        profile=getattr(args, cfg.profile_attr, None),
        cache_dir=getattr(args, cfg.cache_attr, None),
        credentials_path=getattr(args, cfg.credentials_attr, None),
        token_path=getattr(args, cfg.token_attr, None),
        service_cls=service_cls,
    )
