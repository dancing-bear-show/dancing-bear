"""Forwarding command group registration for Mail Assistant CLI."""
from __future__ import annotations

from typing import Any

from core.cli_framework import CLIApp

# One argparse argument: the flag names, plus the kwargs forwarded to
# add_argument(). Values are heterogeneous (str, bool, int), hence Any.
ArgSpec = tuple[tuple[str, ...], dict[str, Any]]

# Repeated help-text strings extracted as module-level constants
HELP_CREDENTIALS = "Path to OAuth credentials.json"
HELP_TOKEN = "Path to token.json"  # nosec B105 - argparse help text, not a credential

_AUTH_ARGS: tuple[ArgSpec, ...] = (
    (("--credentials",), {"help": HELP_CREDENTIALS}),
    (("--token",), {"help": HELP_TOKEN}),
)


def register_forwarding_commands(app: CLIApp) -> object:
    """Register all forwarding subcommands on app and return the forwarding group."""
    from ..forwarding.commands import (
        run_forwarding_list,
        run_forwarding_add,
        run_forwarding_status,
        run_forwarding_enable,
        run_forwarding_disable,
    )

    # (subcommand, help, handler, extra args appended after the shared auth pair)
    specs: list[tuple[str, str, Any, list[ArgSpec]]] = [
        ("list", "List forwarding addresses", run_forwarding_list, []),
        ("add", "Add a forwarding address", run_forwarding_add, [
            (("--email",), {"required": True, "help": "Email address to add"}),
        ]),
        ("status", "Check forwarding status", run_forwarding_status, []),
        ("enable", "Enable forwarding", run_forwarding_enable, [
            (("--email",), {"required": True, "help": "Address to forward to"}),
        ]),
        ("disable", "Disable forwarding", run_forwarding_disable, []),
    ]

    forwarding_group = app.group("forwarding", help="Gmail forwarding configuration")
    for name, help_text, handler, extra in specs:
        forwarding_group.register(name, help_text, handler, list(_AUTH_ARGS) + extra)
    return forwarding_group
