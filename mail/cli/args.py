"""Shared CLI argument builders for Mail Assistant.

Small helpers to attach common Gmail/Outlook auth/cache flags to
argparse parsers. Kept dependency-light and import-safe.
"""
from __future__ import annotations

from core.cli_args import (
    GmailAuthConfig,
    OutlookAuthConfig,
    add_gmail_auth_args as _add_gmail_auth_args,
    add_outlook_auth_args as _add_outlook_auth_args,
)

def add_gmail_common_args(parser):
    """Add common Gmail auth arguments.

    Can use either legacy style or config object:
        add_gmail_common_args(parser)  # legacy
        _add_gmail_auth_args(parser, GmailAuthConfig(cache_help="Custom help"))  # new
    """
    return _add_gmail_auth_args(
        parser,
        include_cache=True,
        cache_help="Cache directory (optional)",
    )


def add_outlook_common_args(parser):
    """Add common Outlook auth arguments.

    Can use either legacy style or config object:
        add_outlook_common_args(parser)  # legacy
        _add_outlook_auth_args(parser, OutlookAuthConfig(tenant_default="consumers"))  # new
    """
    return _add_outlook_auth_args(parser, tenant_default="consumers")
