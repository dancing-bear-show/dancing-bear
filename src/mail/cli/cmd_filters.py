"""Filters command group registration for Mail Assistant CLI."""
from __future__ import annotations

from core.cli_framework import CLIApp
from core.cli_help_text import HELP_START_DATE, HELP_YAML_OUT

# Every filters subcommand takes the same OAuth pair, so it is declared once
# here rather than repeated per command.
_AUTH_ARGS = (
    (("--credentials",), {"help": "Path to OAuth credentials.json"}),
    (("--token",), {"help": "Path to token.json"}),
)

_DRY_RUN = (("--dry-run",), {"action": "store_true", "help": "Preview changes"})
_CONFIG = (("--config",), {"required": True, "help": "Filters YAML config"})


def register_filters_commands(app: CLIApp) -> object:
    """Register all filters subcommands on app and return the filters group."""
    from ..filters.commands import (
        run_filters_plan,
        run_filters_sync,
        run_filters_export,
        run_filters_list,
        run_filters_delete,
        run_filters_impact,
        run_filters_sweep,
        run_filters_sweep_range,
        run_filters_prune_empty,
        run_filters_add_forward_by_label,
        run_filters_add_from_token,
        run_filters_rm_from_token,
    )

    from_token_arg = (
        ("--from-token",),
        {"required": True, "dest": "from_token", "help": "Token in from address"},
    )

    # (subcommand, help, handler, extra args appended after the shared auth pair)
    specs = [
        ("list", "List Gmail filters", run_filters_list, [
            (("--json",), {"action": "store_true", "help": "Output JSON"}),
        ]),
        ("export", "Export Gmail filters to YAML", run_filters_export, [
            (("--out",), {"required": True, "help": HELP_YAML_OUT}),
        ]),
        ("sync", "Sync Gmail filters from YAML config", run_filters_sync, [
            _CONFIG,
            _DRY_RUN,
            (("--delete-missing",), {"action": "store_true", "help": "Delete filters not in config"}),
            (("--require-forward-verified",), {
                "action": "store_true", "help": "Require forward address verified",
            }),
        ]),
        ("plan", "Plan filter changes from YAML config", run_filters_plan, [_CONFIG]),
        ("impact", "Count messages that would match each filter", run_filters_impact, [
            _CONFIG,
            (("--days",), {"type": int, "default": 30, "help": "Days of messages to check"}),
        ]),
        ("sweep", "Apply filter actions to existing messages", run_filters_sweep, [
            _CONFIG,
            (("--days",), {"type": int, "default": 30, "help": "Days of messages to sweep"}),
            _DRY_RUN,
            (("--batch-size",), {"type": int, "default": 500, "help": "Batch size for modifications"}),
        ]),
        ("sweep-range", "Apply filters to a date range of messages", run_filters_sweep_range, [
            _CONFIG,
            (("--start",), {"required": True, "help": HELP_START_DATE}),
            (("--end",), {"required": True, "help": "End date YYYY-MM-DD"}),
            _DRY_RUN,
            (("--batch-size",), {"type": int, "default": 500, "help": "Batch size"}),
        ]),
        ("delete", "Delete a specific filter by ID", run_filters_delete, [
            (("--id",), {"required": True, "help": "Filter ID to delete"}),
        ]),
        ("prune-empty", "Delete filters with no actions", run_filters_prune_empty, [_DRY_RUN]),
        ("add-forward-by-label", "Add forwarding filter by label", run_filters_add_forward_by_label, [
            (("--label",), {"required": True, "help": "Label to forward"}),
            (("--to",), {"required": True, "help": "Forward address"}),
            _DRY_RUN,
        ]),
        ("add-from-token", "Add filter from token-based rule", run_filters_add_from_token, [
            from_token_arg,
            (("--label",), {"required": True, "help": "Label to apply"}),
            _DRY_RUN,
        ]),
        ("rm-from-token", "Remove filter matching from token", run_filters_rm_from_token, [
            from_token_arg,
            _DRY_RUN,
        ]),
    ]

    filters_group = app.group("filters", help="Gmail filters operations")
    for name, help_text, handler, extra in specs:
        filters_group.register(name, help_text, handler, list(_AUTH_ARGS) + extra)
    return filters_group
