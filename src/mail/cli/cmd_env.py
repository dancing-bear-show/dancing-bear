"""Env command group registration for Mail Assistant CLI."""
from __future__ import annotations

from typing import Any

from core.cli_framework import CLIApp

# One argparse argument: the flag names, plus the kwargs forwarded to
# add_argument(). Values are heterogeneous (str, bool, int), hence Any.
ArgSpec = tuple[tuple[str, ...], dict[str, Any]]

# Repeated help-text strings extracted as module-level constants
HELP_CLIENT_ID = "Azure app (client) ID"
HELP_TENANT = "AAD tenant"


def register_env_commands(app: CLIApp) -> object:
    """Register all env subcommands on app and return the env group."""
    from ..config_cli.commands import run_env_setup
    from ..config_resolver import (
        default_gmail_credentials_path,
        default_gmail_token_path,
    )

    _default_gmail_credentials = default_gmail_credentials_path()
    _default_gmail_token = default_gmail_token_path()

    # (subcommand, help, handler, args)
    specs: list[tuple[str, str, Any, list[ArgSpec]]] = [
        ("setup", "Prepare venv and persisted credentials (INI)", run_env_setup, [
            (("--venv-dir",), {"default": ".venv", "help": "Virtualenv directory"}),
            (("--no-venv",), {"action": "store_true", "help": "Skip creating virtualenv"}),
            (("--skip-install",), {"action": "store_true", "help": "Skip pip install"}),
            (("--credentials",), {"help": f"Path to Gmail credentials.json (default: {_default_gmail_credentials})"}),
            (("--token",), {"help": f"Path to Gmail token.json (default: {_default_gmail_token})"}),  # nosec B105 - argparse help text, not a credential
            (("--outlook-client-id",), {"help": HELP_CLIENT_ID}),
            (("--tenant",), {"help": f"{HELP_TENANT} (e.g., consumers)"}),
            (("--outlook-token",), {"help": "Path to Outlook token cache JSON"}),
            (("--copy-gmail-example",), {"dest": "copy_gmail_example", "action": "store_true", "default": True}),
            (("--no-copy-gmail-example",), {"dest": "copy_gmail_example", "action": "store_false"}),
        ]),
    ]

    env_group = app.group("env", help="Environment setup and verification")
    for name, help_text, handler, args in specs:
        env_group.register(name, help_text, handler, args)
    return env_group
