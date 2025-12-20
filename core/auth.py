from __future__ import annotations

"""Shared auth/context factories for Gmail and Outlook."""

from typing import Optional


def resolve_outlook_credentials(
    profile: Optional[str],
    client_id: Optional[str],
    tenant: Optional[str],
    token_path: Optional[str],
):
    """Return (client_id, tenant, token_path) folded over env/profile defaults."""
    import os
    from mail_assistant.config_resolver import (
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
    from calendar_assistant.context import OutlookContext as DefaultContext
    from calendar_assistant.outlook_service import OutlookService as DefaultService

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
    from calendar_assistant.gmail_service import GmailService as DefaultService  # reuse existing helper

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
    *,
    profile_attr: str = "profile",
    client_id_attr: str = "client_id",
    tenant_attr: str = "tenant",
    token_attr: str = "token",
    context_cls=None,
    service_cls=None,
):
    """Instantiate an OutlookService using argparse-like args."""
    return build_outlook_service(
        profile=getattr(args, profile_attr, None),
        client_id=getattr(args, client_id_attr, None),
        tenant=getattr(args, tenant_attr, None),
        token_path=getattr(args, token_attr, None),
        context_cls=context_cls,
        service_cls=service_cls,
    )


def build_gmail_service_from_args(
    args,
    *,
    profile_attr: str = "profile",
    credentials_attr: str = "credentials",
    token_attr: str = "token",
    cache_attr: str = "cache",
    service_cls=None,
):
    """Instantiate a GmailService using argparse-like args."""
    return build_gmail_service(
        profile=getattr(args, profile_attr, None),
        cache_dir=getattr(args, cache_attr, None),
        credentials_path=getattr(args, credentials_attr, None),
        token_path=getattr(args, token_attr, None),
        service_cls=service_cls,
    )
