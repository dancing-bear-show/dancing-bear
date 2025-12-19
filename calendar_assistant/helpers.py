from __future__ import annotations

"""Shared helper functions for calendar assistant."""

from argparse import Namespace

from personal_core.auth import build_gmail_service as _build_gmail_service

from .gmail_service import GmailService


def build_gmail_service_from_args(args: Namespace) -> GmailService:
    """Instantiate an authenticated GmailService from argparse-like args."""
    return _build_gmail_service(
        profile=getattr(args, "profile", None),
        cache_dir=getattr(args, "cache", None),
        credentials_path=getattr(args, "credentials", None),
        token_path=getattr(args, "token", None),
        service_cls=GmailService,
    )
