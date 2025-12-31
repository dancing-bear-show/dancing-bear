"""Registration helper for Gmail calendar-related subcommands."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class GmailCommandCallbacks:
    """Callbacks and helpers for Gmail calendar CLI registration."""

    f_scan_classes: Callable
    f_scan_receipts: Callable
    f_scan_activerh: Callable
    f_mail_list: Callable
    f_sweep_top: Callable
    add_common_gmail_auth_args: Callable
    add_common_gmail_paging_args: Callable


def register(subparsers, callbacks: GmailCommandCallbacks):
    """Register Gmail scan subcommands under the 'gmail' subparser."""
    from .args import HELP_INBOX_ONLY, HELP_DEFAULT_CALENDAR

    p_gmail = subparsers.add_parser("gmail", help="Gmail scan helpers for calendar")
    sub_g = p_gmail.add_subparsers(dest="gmail_cmd")

    # scan-classes
    p_g_scan = sub_g.add_parser("scan-classes", help="Scan recent Gmail for class schedules and output a plan")
    callbacks.add_common_gmail_auth_args(p_g_scan)
    p_g_scan.add_argument("--from-text", dest="from_text", default="active rh", help="Text to match sender (Gmail query)")
    p_g_scan.add_argument("--query", help="Raw Gmail query to use instead of --from-text/--days")
    callbacks.add_common_gmail_paging_args(p_g_scan, default_days=60, default_pages=5, default_page_size=100)
    p_g_scan.add_argument("--inbox-only", action="store_true", help=HELP_INBOX_ONLY)
    p_g_scan.add_argument("--out", help="Optional output YAML plan path (events: [])")
    p_g_scan.add_argument("--calendar", help=HELP_DEFAULT_CALENDAR)
    p_g_scan.set_defaults(func=callbacks.f_scan_classes)

    # scan-receipts
    p_g_rcpts = sub_g.add_parser("scan-receipts", help="Scan Gmail receipts (ActiveRH) and extract recurring events")
    callbacks.add_common_gmail_auth_args(p_g_rcpts)
    p_g_rcpts.add_argument("--from-text", dest="from_text", default="richmondhill.ca", help="Sender filter (Gmail query)")
    p_g_rcpts.add_argument("--query", help="Raw Gmail query to use instead of --from-text/--days")
    callbacks.add_common_gmail_paging_args(p_g_rcpts, default_days=365, default_pages=5, default_page_size=100)
    p_g_rcpts.add_argument("--out", required=True, help="Output YAML plan path (events: [])")
    p_g_rcpts.add_argument("--calendar", help=HELP_DEFAULT_CALENDAR)
    p_g_rcpts.set_defaults(func=callbacks.f_scan_receipts)

    # scan-activerh
    p_g_arh = sub_g.add_parser("scan-activerh", help="Generic scan for ActiveRH receipts across programs")
    callbacks.add_common_gmail_auth_args(p_g_arh)
    p_g_arh.add_argument("--query", help="Raw Gmail query (overrides defaults)")
    callbacks.add_common_gmail_paging_args(p_g_arh, default_days=365, default_pages=10, default_page_size=100)
    p_g_arh.add_argument("--out", required=True, help="Output YAML plan path (events: [])")
    p_g_arh.add_argument("--calendar", help=HELP_DEFAULT_CALENDAR)
    p_g_arh.set_defaults(func=callbacks.f_scan_activerh)

    # mail-list
    p_g_list = sub_g.add_parser("mail-list", help="List recent Gmail messages (read-only)")
    callbacks.add_common_gmail_auth_args(p_g_list)
    p_g_list.add_argument("--from-text", dest="from_text", help="Optional sender filter (adds from:")
    p_g_list.add_argument("--query", help="Raw Gmail query; overrides defaults")
    callbacks.add_common_gmail_paging_args(p_g_list, default_days=7, default_pages=1, default_page_size=10)
    p_g_list.add_argument("--inbox-only", action="store_true", help=HELP_INBOX_ONLY)
    p_g_list.set_defaults(func=callbacks.f_mail_list)

    # sweep-top
    p_g_sweep = sub_g.add_parser("sweep-top", help="Find top frequent senders in Inbox over a window")
    callbacks.add_common_gmail_auth_args(p_g_sweep)
    p_g_sweep.add_argument("--days", type=int, default=10, help="Look back N days (default 10)")
    p_g_sweep.add_argument("--pages", type=int, default=5, help="Max pages to fetch (default 5)")
    p_g_sweep.add_argument("--page-size", type=int, default=100, help="Page size (default 100)")
    p_g_sweep.add_argument("--top", type=int, default=10, help="How many top senders to show (default 10)")
    p_g_sweep.add_argument("--inbox-only", action="store_true", help=HELP_INBOX_ONLY)
    p_g_sweep.add_argument("--out", help="Optional suggested Gmail filters YAML path")
    p_g_sweep.set_defaults(func=callbacks.f_sweep_top)

    return p_gmail
