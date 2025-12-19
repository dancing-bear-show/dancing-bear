from __future__ import annotations

def add_common_outlook_args(sp):
    sp.add_argument("--client-id", help="Azure app (client) ID; defaults from profile or env")
    sp.add_argument("--tenant", default="consumers", help="AAD tenant (default: consumers)")
    sp.add_argument("--token", help="Path to token cache JSON (optional)")
    return sp


def add_common_gmail_auth_args(sp):
    sp.add_argument("--credentials", type=str)
    sp.add_argument("--token", type=str)
    sp.add_argument("--cache", type=str)
    return sp


def add_common_gmail_paging_args(sp, *, default_days: int, default_pages: int, default_page_size: int):
    sp.add_argument("--days", type=int, default=default_days, help=f"Look back N days (default {default_days})")
    sp.add_argument("--pages", type=int, default=default_pages, help=f"Max pages (default {default_pages})")
    sp.add_argument("--page-size", type=int, default=default_page_size, help=f"Page size (default {default_page_size})")
    return sp

