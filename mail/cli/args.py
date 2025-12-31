"""Shared CLI argument builders for Mail Assistant.

Small helpers to attach common Gmail/Outlook auth/cache flags to
argparse parsers. Kept dependency-light and import-safe.
"""
from __future__ import annotations

from core.cli_args import (
    add_gmail_auth_args as _add_gmail_auth_args,
    add_outlook_auth_args as _add_outlook_auth_args,
)

def add_gmail_common_args(parser):
    """Add common Gmail auth arguments."""
    return _add_gmail_auth_args(
        parser,
        include_cache=True,
        cache_help="Cache directory (optional)",
    )


def add_outlook_common_args(parser):
    """Add common Outlook auth arguments."""
    return _add_outlook_auth_args(parser, tenant_default="consumers")
