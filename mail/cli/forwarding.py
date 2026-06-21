"""Forwarding CLI registration.

Centralized wiring for the `forwarding` command group to keep `__main__` lean
and consistent with other CLI modules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .args import add_gmail_common_args as _add_gmail_args


@dataclass
class ForwardingHandlers:
    """Handler functions for forwarding subcommands."""

    f_list: Any
    f_add: Any
    f_status: Any
    f_enable: Any
    f_disable: Any


def register(subparsers, *, handlers: ForwardingHandlers):
    p_fwd = subparsers.add_parser("forwarding", help="Manage forwarding addresses")
    _add_gmail_args(p_fwd)
    sub_fwd = p_fwd.add_subparsers(dest="forwarding_cmd")

    p_fwd_list = sub_fwd.add_parser("list", help="List forwarding addresses and verification status")
    p_fwd_list.set_defaults(func=handlers.f_list)

    p_fwd_add = sub_fwd.add_parser(
        "add", help="Add a forwarding address (Gmail will send a verification email)"
    )
    p_fwd_add.add_argument("--email", required=True)
    p_fwd_add.set_defaults(func=handlers.f_add)

    p_fwd_status = sub_fwd.add_parser(
        "status", help="Show Gmail account-level auto-forwarding settings"
    )
    p_fwd_status.set_defaults(func=handlers.f_status)

    p_fwd_enable = sub_fwd.add_parser(
        "enable", help="Enable account-level auto-forwarding to an email"
    )
    p_fwd_enable.add_argument("--email", required=True, help="Verified forwarding destination email")
    p_fwd_enable.add_argument(
        "--disposition",
        choices=["leaveInInbox", "archive", "trash", "markRead"],
        default="leaveInInbox",
        help="What to do with Gmail's copy (default: leaveInInbox)",
    )
    p_fwd_enable.set_defaults(func=handlers.f_enable)

    p_fwd_disable = sub_fwd.add_parser("disable", help="Disable account-level auto-forwarding")
    p_fwd_disable.set_defaults(func=handlers.f_disable)
