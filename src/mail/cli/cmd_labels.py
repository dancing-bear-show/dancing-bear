"""Labels command group registration for Mail Assistant CLI."""
from __future__ import annotations

from core.cli_framework import CLIApp
from core.cli_help_text import HELP_YAML_OUT


def register_labels_commands(app: CLIApp) -> object:
    """Register all labels subcommands on app and return the labels group."""
    from ..labels.commands import (
        run_labels_plan,
        run_labels_sync,
        run_labels_export,
        run_labels_list,
        run_labels_doctor,
        run_labels_prune_empty,
        run_labels_learn,
        run_labels_apply_suggestions,
        run_labels_delete,
        run_labels_sweep_parents,
    )

    labels_group = app.group("labels", help="Gmail labels operations")

    @labels_group.command("list", help="List Gmail labels")
    @labels_group.argument("--credentials", help="Path to OAuth credentials.json")
    @labels_group.argument("--token", help="Path to token.json")
    @labels_group.argument("--json", action="store_true", help="Output JSON instead of table")
    def cmd_labels_list(args) -> int:
        return run_labels_list(args)

    @labels_group.command("export", help="Export Gmail labels to YAML")
    @labels_group.argument("--credentials", help="Path to OAuth credentials.json")
    @labels_group.argument("--token", help="Path to token.json")
    @labels_group.argument("--out", required=True, help=HELP_YAML_OUT)
    def cmd_labels_export(args) -> int:
        return run_labels_export(args)

    @labels_group.command("sync", help="Sync Gmail labels from YAML config")
    @labels_group.argument("--credentials", help="Path to OAuth credentials.json")
    @labels_group.argument("--token", help="Path to token.json")
    @labels_group.argument("--config", required=True, help="Labels YAML config")
    @labels_group.argument("--dry-run", action="store_true", help="Preview changes")
    @labels_group.argument("--delete-missing", action="store_true", help="Delete labels not in config")
    def cmd_labels_sync(args) -> int:
        return run_labels_sync(args)

    @labels_group.command("plan", help="Plan label changes from YAML config")
    @labels_group.argument("--credentials", help="Path to OAuth credentials.json")
    @labels_group.argument("--token", help="Path to token.json")
    @labels_group.argument("--config", required=True, help="Labels YAML config")
    def cmd_labels_plan(args) -> int:
        return run_labels_plan(args)

    @labels_group.command("doctor", help="Check for label inconsistencies")
    @labels_group.argument("--credentials", help="Path to OAuth credentials.json")
    @labels_group.argument("--token", help="Path to token.json")
    def cmd_labels_doctor(args) -> int:
        return run_labels_doctor(args)

    @labels_group.command("prune-empty", help="Delete empty labels")
    @labels_group.argument("--credentials", help="Path to OAuth credentials.json")
    @labels_group.argument("--token", help="Path to token.json")
    @labels_group.argument("--dry-run", action="store_true", help="Preview changes")
    def cmd_labels_prune_empty(args) -> int:
        return run_labels_prune_empty(args)

    @labels_group.command("learn", help="Learn label patterns from existing messages")
    @labels_group.argument("--credentials", help="Path to OAuth credentials.json")
    @labels_group.argument("--token", help="Path to token.json")
    @labels_group.argument("--out", help="Output suggestions YAML")
    @labels_group.argument("--days", type=int, default=30, help="Days of messages to analyze")
    def cmd_labels_learn(args) -> int:
        return run_labels_learn(args)

    @labels_group.command("apply-suggestions", help="Apply learned label suggestions")
    @labels_group.argument("--credentials", help="Path to OAuth credentials.json")
    @labels_group.argument("--token", help="Path to token.json")
    @labels_group.argument("--config", required=True, help="Suggestions YAML from learn")
    @labels_group.argument("--dry-run", action="store_true", help="Preview changes")
    def cmd_labels_apply_suggestions(args) -> int:
        return run_labels_apply_suggestions(args)

    @labels_group.command("delete", help="Delete a specific label")
    @labels_group.argument("--credentials", help="Path to OAuth credentials.json")
    @labels_group.argument("--token", help="Path to token.json")
    @labels_group.argument("--name", required=True, help="Label name to delete")
    def cmd_labels_delete(args) -> int:
        return run_labels_delete(args)

    @labels_group.command("sweep-parents", help="Clean up orphan parent labels")
    @labels_group.argument("--credentials", help="Path to OAuth credentials.json")
    @labels_group.argument("--token", help="Path to token.json")
    @labels_group.argument("--dry-run", action="store_true", help="Preview changes")
    def cmd_labels_sweep_parents(args) -> int:
        return run_labels_sweep_parents(args)

    return labels_group
