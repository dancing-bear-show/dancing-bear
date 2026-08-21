"""Labels command group registration for Mail Assistant CLI."""
from __future__ import annotations

from typing import Any

from core.cli_framework import CLIApp
from core.cli_help_text import HELP_YAML_OUT

# One argparse argument: the flag names, plus the kwargs forwarded to
# add_argument(). Values are heterogeneous (str, bool, int), hence Any.
ArgSpec = tuple[tuple[str, ...], dict[str, Any]]

# Every labels subcommand takes the same OAuth pair, so it is declared once here
# rather than repeated per command.
_AUTH_ARGS: tuple[ArgSpec, ...] = (
    (("--credentials",), {"help": "Path to OAuth credentials.json"}),
    (("--token",), {"help": "Path to token.json"}),
)

_DRY_RUN: ArgSpec = (("--dry-run",), {"action": "store_true", "help": "Preview changes"})


def register_labels_commands(app: CLIApp) -> object:
    """Register all labels subcommands on app and return the labels group."""
    from ..labels.commands_plan import (
        run_labels_plan,
        run_labels_sync,
        run_labels_export,
        run_labels_list,
    )
    from ..labels.commands_doctor import (
        run_labels_doctor,
        run_labels_prune_empty,
        run_labels_learn,
        run_labels_apply_suggestions,
        run_labels_delete,
        run_labels_sweep_parents,
    )

    # (subcommand, help, handler, extra args appended after the shared auth pair)
    specs: list[tuple[str, str, Any, list[ArgSpec]]] = [
        ("list", "List Gmail labels", run_labels_list, [
            (("--json",), {"action": "store_true", "help": "Output JSON instead of table"}),
        ]),
        ("export", "Export Gmail labels to YAML", run_labels_export, [
            (("--out",), {"required": True, "help": HELP_YAML_OUT}),
        ]),
        ("sync", "Sync Gmail labels from YAML config", run_labels_sync, [
            (("--config",), {"required": True, "help": "Labels YAML config"}),
            _DRY_RUN,
            (("--delete-missing",), {"action": "store_true", "help": "Delete labels not in config"}),
        ]),
        ("plan", "Plan label changes from YAML config", run_labels_plan, [
            (("--config",), {"required": True, "help": "Labels YAML config"}),
        ]),
        ("doctor", "Check for label inconsistencies", run_labels_doctor, []),
        ("prune-empty", "Delete empty labels", run_labels_prune_empty, [_DRY_RUN]),
        ("learn", "Learn label patterns from existing messages", run_labels_learn, [
            (("--out",), {"help": "Output suggestions YAML"}),
            (("--days",), {"type": int, "default": 30, "help": "Days of messages to analyze"}),
        ]),
        ("apply-suggestions", "Apply learned label suggestions", run_labels_apply_suggestions, [
            (("--config",), {"required": True, "help": "Suggestions YAML from learn"}),
            _DRY_RUN,
        ]),
        ("delete", "Delete a specific label", run_labels_delete, [
            (("--name",), {"required": True, "help": "Label name to delete"}),
        ]),
        ("sweep-parents", "Clean up orphan parent labels", run_labels_sweep_parents, [_DRY_RUN]),
    ]

    labels_group = app.group("labels", help="Gmail labels operations")
    for name, help_text, handler, extra in specs:
        labels_group.register(name, help_text, handler, list(_AUTH_ARGS) + extra)
    return labels_group
