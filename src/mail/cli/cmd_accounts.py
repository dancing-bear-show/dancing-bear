"""Accounts command group registration for Mail Assistant CLI."""
from __future__ import annotations

from typing import Any

from core.cli_framework import CLIApp
from core.cli_help_text import HELP_ACCOUNTS, HELP_ACCOUNTS_LIST, HELP_OUT_DIR

# One argparse argument: the flag names, plus the kwargs forwarded to
# add_argument(). Values are heterogeneous (str, bool, int), hence Any.
ArgSpec = tuple[tuple[str, ...], dict[str, Any]]

_CONFIG_ARG: ArgSpec = (("--config",), {"required": True, "help": HELP_ACCOUNTS})
_ACCOUNTS_ARG: ArgSpec = (("--accounts",), {"help": HELP_ACCOUNTS_LIST})
_DRY_RUN: ArgSpec = (("--dry-run",), {"action": "store_true"})


def register_accounts_commands(app: CLIApp) -> object:
    """Register all accounts subcommands on app and return the accounts group."""
    from ..accounts.commands import (
        run_accounts_list,
        run_accounts_export_labels,
        run_accounts_sync_labels,
        run_accounts_export_filters,
        run_accounts_sync_filters,
        run_accounts_plan_labels,
        run_accounts_plan_filters,
        run_accounts_export_signatures,
        run_accounts_sync_signatures,
    )

    # (subcommand, help, handler, args)
    specs: list[tuple[str, str, Any, list[ArgSpec]]] = [
        ("list", "List configured accounts", run_accounts_list, [
            _CONFIG_ARG,
            (("--accounts",), {"help": "Comma-separated list of accounts to include"}),
            _DRY_RUN,
        ]),
        ("export-labels", "Export labels from all accounts", run_accounts_export_labels, [
            _CONFIG_ARG,
            _ACCOUNTS_ARG,
            (("--out-dir",), {"required": True, "help": HELP_OUT_DIR}),
            _DRY_RUN,
        ]),
        ("sync-labels", "Sync labels to all accounts", run_accounts_sync_labels, [
            _CONFIG_ARG,
            _ACCOUNTS_ARG,
            (("--labels",), {"required": True, "help": "Labels YAML"}),
            _DRY_RUN,
        ]),
        ("export-filters", "Export filters from all accounts", run_accounts_export_filters, [
            _CONFIG_ARG,
            _ACCOUNTS_ARG,
            (("--out-dir",), {"required": True, "help": HELP_OUT_DIR}),
            _DRY_RUN,
        ]),
        ("sync-filters", "Sync filters to all accounts", run_accounts_sync_filters, [
            _CONFIG_ARG,
            _ACCOUNTS_ARG,
            (("--filters",), {"required": True, "help": "Filters YAML"}),
            (("--require-forward-verified",), {"action": "store_true"}),
            _DRY_RUN,
        ]),
        ("plan-labels", "Plan label changes for all accounts", run_accounts_plan_labels, [
            _CONFIG_ARG,
            _ACCOUNTS_ARG,
            (("--labels",), {"required": True, "help": "Labels YAML"}),
            _DRY_RUN,
        ]),
        ("plan-filters", "Plan filter changes for all accounts", run_accounts_plan_filters, [
            _CONFIG_ARG,
            _ACCOUNTS_ARG,
            (("--filters",), {"required": True, "help": "Filters YAML"}),
            _DRY_RUN,
        ]),
        ("export-signatures", "Export signatures from all accounts", run_accounts_export_signatures, [
            _CONFIG_ARG,
            _ACCOUNTS_ARG,
            (("--out-dir",), {"required": True, "help": HELP_OUT_DIR}),
            _DRY_RUN,
        ]),
        ("sync-signatures", "Sync signatures to all accounts", run_accounts_sync_signatures, [
            _CONFIG_ARG,
            _ACCOUNTS_ARG,
            (("--send-as",), {"help": "Send-as address"}),
            _DRY_RUN,
        ]),
    ]

    accounts_group = app.group("accounts", help="Operate across multiple email accounts/providers")
    for name, help_text, handler, args in specs:
        accounts_group.register(name, help_text, handler, args)
    return accounts_group
