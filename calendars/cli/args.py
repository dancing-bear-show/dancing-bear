"""CLI argument helpers and help string constants for calendar."""
from __future__ import annotations

from core.cli_args import add_gmail_auth_args as _add_gmail_auth_args
from core.cli_args import add_outlook_auth_args as _add_outlook_auth_args


# Help string constants to avoid duplication
HELP_START_DATE = "Start date YYYY-MM-DD (default: 30 days ago)"
HELP_END_DATE = "End date YYYY-MM-DD (default: 180 days ahead)"
HELP_CALENDAR_DEFAULT = "Calendar name (defaults to event.calendar or primary)"
HELP_CONFIG_EVENTS = "YAML with events: [] entries"
HELP_DRY_RUN = "Preview changes without writing"
HELP_DEFAULT_CALENDAR = "Default calendar name to include in plan entries"
HELP_INBOX_ONLY = "Restrict to Inbox (adds in:inbox)"


def add_common_outlook_args(sp):
    return _add_outlook_auth_args(sp, tenant_default="consumers")


def add_common_gmail_auth_args(sp):
    return _add_gmail_auth_args(sp, include_cache=True)


def add_common_gmail_paging_args(sp, *, default_days: int, default_pages: int, default_page_size: int):
    sp.add_argument("--days", type=int, default=default_days, help=f"Look back N days (default {default_days})")
    sp.add_argument("--pages", type=int, default=default_pages, help=f"Max pages (default {default_pages})")
    sp.add_argument("--page-size", type=int, default=default_page_size, help=f"Page size (default {default_page_size})")
    return sp
