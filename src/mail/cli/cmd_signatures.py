"""Signatures command group registration for Mail Assistant CLI."""
from __future__ import annotations

from typing import Any

from core.cli_framework import CLIApp
from core.cli_help_text import HELP_OUT_DIR

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


def register_signatures_commands(app: CLIApp) -> object:
    """Register all signatures subcommands on app and return the signatures group."""
    from ..signatures.commands import (
        run_signatures_export,
        run_signatures_sync,
        run_signatures_normalize,
    )

    # (subcommand, help, handler, extra args appended after the shared auth pair)
    specs: list[tuple[str, str, Any, list[ArgSpec]]] = [
        ("export", "Export Gmail signatures to files", run_signatures_export, [
            (("--out-dir",), {"required": True, "help": HELP_OUT_DIR}),
        ]),
        ("sync", "Sync signatures from files to Gmail", run_signatures_sync, [
            (("--in-dir",), {"required": True, "help": "Input directory with signatures"}),
            (("--dry-run",), {"action": "store_true", "help": "Preview changes"}),
        ]),
        ("normalize", "Normalize signature HTML", run_signatures_normalize, [
            (("--input",), {"required": True, "help": "Input HTML file"}),
            (("--output",), {"required": True, "help": "Output HTML file"}),
        ]),
    ]

    signatures_group = app.group("signatures", help="Gmail signatures operations")
    for name, help_text, handler, extra in specs:
        # normalize does not need auth args
        if name == "normalize":
            signatures_group.register(name, help_text, handler, extra)
        else:
            signatures_group.register(name, help_text, handler, list(_AUTH_ARGS) + extra)
    return signatures_group
