"""Filters command group registration for Mail Assistant CLI."""
from __future__ import annotations

from core.cli_framework import CLIApp
from core.cli_help_text import HELP_START_DATE, HELP_YAML_OUT


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

    filters_group = app.group("filters", help="Gmail filters operations")

    @filters_group.command("list", help="List Gmail filters")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--json", action="store_true", help="Output JSON")
    def cmd_filters_list(args) -> int:
        return run_filters_list(args)

    @filters_group.command("export", help="Export Gmail filters to YAML")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--out", required=True, help=HELP_YAML_OUT)
    def cmd_filters_export(args) -> int:
        return run_filters_export(args)

    @filters_group.command("sync", help="Sync Gmail filters from YAML config")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--config", required=True, help="Filters YAML config")
    @filters_group.argument("--dry-run", action="store_true", help="Preview changes")
    @filters_group.argument("--delete-missing", action="store_true", help="Delete filters not in config")
    @filters_group.argument("--require-forward-verified", action="store_true", help="Require forward address verified")
    def cmd_filters_sync(args) -> int:
        return run_filters_sync(args)

    @filters_group.command("plan", help="Plan filter changes from YAML config")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--config", required=True, help="Filters YAML config")
    def cmd_filters_plan(args) -> int:
        return run_filters_plan(args)

    @filters_group.command("impact", help="Count messages that would match each filter")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--config", required=True, help="Filters YAML config")
    @filters_group.argument("--days", type=int, default=30, help="Days of messages to check")
    def cmd_filters_impact(args) -> int:
        return run_filters_impact(args)

    @filters_group.command("sweep", help="Apply filter actions to existing messages")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--config", required=True, help="Filters YAML config")
    @filters_group.argument("--days", type=int, default=30, help="Days of messages to sweep")
    @filters_group.argument("--dry-run", action="store_true", help="Preview changes")
    @filters_group.argument("--batch-size", type=int, default=500, help="Batch size for modifications")
    def cmd_filters_sweep(args) -> int:
        return run_filters_sweep(args)

    @filters_group.command("sweep-range", help="Apply filters to a date range of messages")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--config", required=True, help="Filters YAML config")
    @filters_group.argument("--start", required=True, help=HELP_START_DATE)
    @filters_group.argument("--end", required=True, help="End date YYYY-MM-DD")
    @filters_group.argument("--dry-run", action="store_true", help="Preview changes")
    @filters_group.argument("--batch-size", type=int, default=500, help="Batch size")
    def cmd_filters_sweep_range(args) -> int:
        return run_filters_sweep_range(args)

    @filters_group.command("delete", help="Delete a specific filter by ID")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--id", required=True, help="Filter ID to delete")
    def cmd_filters_delete(args) -> int:
        return run_filters_delete(args)

    @filters_group.command("prune-empty", help="Delete filters with no actions")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--dry-run", action="store_true", help="Preview changes")
    def cmd_filters_prune_empty(args) -> int:
        return run_filters_prune_empty(args)

    @filters_group.command("add-forward-by-label", help="Add forwarding filter by label")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--label", required=True, help="Label to forward")
    @filters_group.argument("--to", required=True, help="Forward address")
    @filters_group.argument("--dry-run", action="store_true", help="Preview changes")
    def cmd_filters_add_forward_by_label(args) -> int:
        return run_filters_add_forward_by_label(args)

    @filters_group.command("add-from-token", help="Add filter from token-based rule")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--from-token", required=True, dest="from_token", help="Token in from address")
    @filters_group.argument("--label", required=True, help="Label to apply")
    @filters_group.argument("--dry-run", action="store_true", help="Preview changes")
    def cmd_filters_add_from_token(args) -> int:
        return run_filters_add_from_token(args)

    @filters_group.command("rm-from-token", help="Remove filter matching from token")
    @filters_group.argument("--credentials", help="Path to OAuth credentials.json")
    @filters_group.argument("--token", help="Path to token.json")
    @filters_group.argument("--from-token", required=True, dest="from_token", help="Token in from address")
    @filters_group.argument("--dry-run", action="store_true", help="Preview changes")
    def cmd_filters_rm_from_token(args) -> int:
        return run_filters_rm_from_token(args)

    return filters_group
