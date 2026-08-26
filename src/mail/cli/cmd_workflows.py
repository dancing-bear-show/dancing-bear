"""Workflows command group registration for Mail Assistant CLI."""
from __future__ import annotations

from typing import Any

from core.cli_framework import CLIApp

# One argparse argument: the flag names, plus the kwargs forwarded to
# add_argument(). Values are heterogeneous (str, bool, int), hence Any.
ArgSpec = tuple[tuple[str, ...], dict[str, Any]]


def register_workflows_commands(app: CLIApp) -> object:
    """Register all workflows subcommands on app and return the workflows group."""
    from ..config_cli.commands import (
        run_workflows_gmail_from_unified,
        run_workflows_from_unified,
    )

    # (subcommand, help, handler, args)
    specs: list[tuple[str, str, Any, list[ArgSpec]]] = [
        ("gmail-from-unified", "Derive Gmail filters from unified YAML, plan, and optionally apply", run_workflows_gmail_from_unified, [
            (("--config",), {"help": "Unified filters YAML (default: ~/.config/dancing-bear/filters_unified.yaml)"}),
            (("--out-dir",), {"default": "out", "help": "Directory for artifacts"}),
            (("--delete-missing",), {"action": "store_true", "help": "Include deletions"}),
            (("--apply",), {"action": "store_true", "help": "Apply changes after planning"}),
        ]),
        ("from-unified", "Derive provider configs from unified, plan per provider, optionally apply", run_workflows_from_unified, [
            (("--config",), {"help": "Unified filters YAML (default: ~/.config/dancing-bear/filters_unified.yaml)"}),
            (("--out-dir",), {"default": "out", "help": "Directory for artifacts"}),
            (("--providers",), {"help": "Comma-separated providers (gmail,outlook)"}),
            (("--delete-missing",), {"action": "store_true", "help": "Include deletions"}),
            (("--apply",), {"action": "store_true", "help": "Apply changes after planning"}),
            (("--accounts-config",), {"default": "config/accounts.yaml", "help": "Accounts YAML for Outlook defaults"}),
            (("--account",), {"help": "Account name for Outlook"}),
            (("--outlook-move-to-folders",), {"action": "store_true", "dest": "outlook_move_to_folders", "default": True}),
            (("--no-outlook-move-to-folders",), {"action": "store_false", "dest": "outlook_move_to_folders"}),
        ]),
    ]

    workflows_group = app.group("workflows", help="Agentic workflows that chain plan/apply steps")
    for name, help_text, handler, args in specs:
        workflows_group.register(name, help_text, handler, args)
    return workflows_group
