"""Auto command group registration for Mail Assistant CLI."""
from __future__ import annotations

from typing import Any

from core.cli_framework import CLIApp
from core.cli_help_text import HELP_CACHE_DIR

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


def register_auto_commands(app: CLIApp) -> object:
    """Register all auto subcommands on app and return the auto group."""
    from ..auto.commands import (
        run_auto_propose,
        run_auto_summary,
        run_auto_apply,
    )

    # (subcommand, help, handler, extra args appended after the shared auth pair)
    specs: list[tuple[str, str, Any, list[ArgSpec]]] = [
        ("propose", "Create proposal for categorizing + archiving mail", run_auto_propose, [
            (("--cache",), {"help": HELP_CACHE_DIR}),
            (("--days",), {"type": int, "default": 7, "help": "Days of messages"}),
            (("--only-inbox",), {"action": "store_true"}),
            (("--pages",), {"type": int, "default": 20, "help": "Pages to fetch"}),
            (("--batch-size",), {"type": int, "default": 500}),
            (("--log",), {"default": "logs/auto_runs.jsonl", "help": "Log file"}),
            (("--protect",), {"action": "append", "default": [], "help": "Protected senders/domains"}),
            (("--out",), {"required": True, "help": "Path to proposal JSON"}),
            (("--dry-run",), {"action": "store_true"}),
        ]),
        ("apply", "Apply a saved proposal (archive + label)", run_auto_apply, [
            (("--cache",), {"help": HELP_CACHE_DIR}),
            (("--proposal",), {"required": True, "help": "Proposal JSON path"}),
            (("--cutoff-days",), {"type": int, "help": "Only apply to messages older than N days"}),
            (("--batch-size",), {"type": int, "default": 500}),
            (("--dry-run",), {"action": "store_true"}),
            (("--log",), {"default": "logs/auto_runs.jsonl", "help": "Log file"}),
        ]),
        ("summary", "Summarize a proposal JSON", run_auto_summary, [
            (("--proposal",), {"required": True, "help": "Proposal JSON path"}),
        ]),
    ]

    auto_group = app.group("auto", help="Gmail: propose/apply categorization + archive")
    for name, help_text, handler, extra in specs:
        # summary does not need auth args
        if name == "summary":
            auto_group.register(name, help_text, handler, extra)
        else:
            auto_group.register(name, help_text, handler, list(_AUTH_ARGS) + extra)
    return auto_group
