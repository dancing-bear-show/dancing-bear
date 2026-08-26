"""Config command group registration for Mail Assistant CLI."""
from __future__ import annotations

from typing import Any

from core.cli_framework import CLIApp

# One argparse argument: the flag names, plus the kwargs forwarded to
# add_argument(). Values are heterogeneous (str, bool, int), hence Any.
ArgSpec = tuple[tuple[str, ...], dict[str, Any]]


def register_config_commands(app: CLIApp) -> object:
    """Register all config subcommands on app and return the config group."""
    from ..config_cli.commands import (
        run_config_inspect,
        run_config_derive_labels,
        run_config_derive_filters,
        run_config_optimize_filters,
        run_config_audit_filters,
    )

    # (subcommand, help, handler, args)
    specs: list[tuple[str, str, Any, list[ArgSpec]]] = [
        ("inspect", "Show config with redacted secrets", run_config_inspect, [
            (("--path",), {"default": "~/.config/credentials.ini", "help": "Path to INI file"}),
            (("--section",), {"help": "Only show a specific section"}),
            (("--only-mail",), {"action": "store_true", "help": "Restrict to mail.* sections"}),
        ]),
        ("derive.labels", "Derive Gmail and Outlook labels YAML from unified", run_config_derive_labels, [
            (("--in",), {"dest": "in_path", "required": True, "help": "Unified labels YAML"}),
            (("--out-gmail",), {"required": True, "help": "Output Gmail labels YAML"}),
            (("--out-outlook",), {"required": True, "help": "Output Outlook categories YAML"}),
        ]),
        ("derive.filters", "Derive Gmail and Outlook filters YAML from unified", run_config_derive_filters, [
            (("--in",), {"dest": "in_path", "help": "Unified filters YAML (default: ~/.config/dancing-bear/filters_unified.yaml)"}),
            (("--out-gmail",), {"required": True, "help": "Output Gmail filters YAML"}),
            (("--out-outlook",), {"required": True, "help": "Output Outlook rules YAML"}),
            (("--outlook-move-to-folders",), {"action": "store_true", "dest": "outlook_move_to_folders", "default": True, "help": "Encode moveToFolder (default on)"}),
            (("--no-outlook-move-to-folders",), {"action": "store_false", "dest": "outlook_move_to_folders", "help": "Categories-only on Outlook"}),
            (("--outlook-archive-on-remove-inbox",), {"action": "store_true", "dest": "outlook_archive_on_remove_inbox", "help": "Move to Archive when INBOX removed"}),
        ]),
        ("optimize.filters", "Optimize unified configs by merging similar rules", run_config_optimize_filters, [
            (("--in",), {"dest": "in_path", "help": "Unified filters YAML (default: ~/.config/dancing-bear/filters_unified.yaml)"}),
            (("--out",), {"required": True, "help": "Output optimized YAML"}),
            (("--merge-threshold",), {"type": int, "default": 2, "help": "Minimum rules to merge"}),
            (("--preview",), {"action": "store_true", "help": "Print merge summary"}),
        ]),
        ("audit.filters", "Audit unified coverage vs provider exports", run_config_audit_filters, [
            (("--in",), {"dest": "in_path", "help": "Unified filters YAML (default: ~/.config/dancing-bear/filters_unified.yaml)"}),
            (("--export",), {"dest": "export_path", "required": True, "help": "Gmail exported filters YAML"}),
            (("--preview-missing",), {"action": "store_true", "help": "List missing rules"}),
        ]),
    ]

    config_group = app.group("config", help="Inspect and manage configuration")
    for name, help_text, handler, args in specs:
        config_group.register(name, help_text, handler, args)
    return config_group
