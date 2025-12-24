from __future__ import annotations

from typing import Dict, Optional
from ..providers.gmail import GmailProvider
from ..config_resolver import resolve_paths_profile, persist_if_provided


def gmail_provider_from_args(args):
    """Construct a GmailProvider from argparse-like args with credentials/token/cache.

    Does not authenticate; caller decides when to call authenticate().
    """
    arg_creds = getattr(args, "credentials", None)
    arg_tok = getattr(args, "token", None)
    creds_path, tok_path = resolve_paths_profile(arg_credentials=arg_creds, arg_token=arg_tok, profile=getattr(args, 'profile', None))
    # Persist explicit inputs for future runs
    persist_if_provided(arg_credentials=arg_creds, arg_token=arg_tok, profile=getattr(args, 'profile', None))
    return GmailProvider(
        credentials_path=creds_path,
        token_path=tok_path,
        cache_dir=getattr(args, "cache", None),
    )


def with_gmail_client(func):
    """Decorator that authenticates a Gmail client and attaches it to args.

    Attaches the client as `args._gmail_client` before invoking the function.
    """
    def wrapper(args, *a, **kw):  # type: ignore[no-untyped-def]
        client = gmail_provider_from_args(args)
        client.authenticate()
        try:
            setattr(args, "_gmail_client", client)
        except Exception:
            pass  # nosec B110 - non-critical attribute set
        return func(args, *a, **kw)

    return wrapper


def gmail_client_authenticated(args):
    """Return an authenticated GmailProvider built from args.

    Convenience wrapper to reduce repeated provider+authenticate boilerplate.
    """
    client = gmail_provider_from_args(args)
    client.authenticate()
    return client


def add_outlook_common_args(parser):
    # Backward shim: kept for compatibility; prefer mail.cli.args
    from ..cli.args import add_outlook_common_args as _impl
    return _impl(parser)


def preview_criteria(criteria: Optional[Dict]) -> str:
    """Return a concise preview of criteria for display.

    Shows from/to/subject if present; elides long query bodies.
    """
    c = criteria or {}
    parts = []
    for k in ("from", "to", "subject"):
        v = c.get(k)
        if v:
            parts.append(f"{k}:{v}")
    if c.get("query"):
        parts.append("query=…")
    return " ".join(parts) if parts else "<complex>"
