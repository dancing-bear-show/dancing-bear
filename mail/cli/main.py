"""Mail Assistant CLI using CLIApp framework.

This CLI provides Gmail and Outlook mail management operations including:
- Labels/categories management
- Filters/rules sync
- Messages search, summarize, reply
- Forwarding configuration
- Signatures management
- Multi-account operations
"""

from __future__ import annotations

from typing import Optional, List

from core.assistant import BaseAssistant
from core.cli_framework import CLIApp

from ..config_resolver import (
    default_gmail_credentials_path,
    default_gmail_token_path,
    default_outlook_flow_path,
    default_outlook_token_path,
)
# Pipeline command imports
from ..signatures.commands import (
    run_signatures_export,
    run_signatures_sync,
    run_signatures_normalize,
)
from ..auto.commands import (
    run_auto_propose,
    run_auto_summary,
    run_auto_apply,
)
from ..forwarding.commands import (
    run_forwarding_list,
    run_forwarding_add,
    run_forwarding_status,
    run_forwarding_enable,
    run_forwarding_disable,
)
from ..outlook.commands import (
    run_outlook_rules_list,
    run_outlook_rules_export,
    run_outlook_rules_sync,
    run_outlook_rules_plan,
    run_outlook_rules_delete,
    run_outlook_rules_sweep,
    run_outlook_categories_list,
    run_outlook_categories_export,
    run_outlook_categories_sync,
    run_outlook_folders_sync,
    run_outlook_calendar_add,
    run_outlook_calendar_add_recurring,
    run_outlook_calendar_add_from_config,
    run_outlook_auth_device_code,
    run_outlook_auth_poll,
    run_outlook_auth_ensure,
    run_outlook_auth_validate,
)
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
from ..messages_cli.commands import (
    run_messages_search,
    run_messages_summarize,
    run_messages_reply,
    run_messages_apply_scheduled,
)
from ..config_cli.commands import (
    run_auth,
    run_backup,
    run_cache_stats,
    run_cache_clear,
    run_cache_prune,
    run_config_inspect,
    run_config_derive_labels,
    run_config_derive_filters,
    run_config_optimize_filters,
    run_config_audit_filters,
    run_workflows_gmail_from_unified,
    run_workflows_from_unified,
    run_env_setup,
)


assistant = BaseAssistant(
    "mail",
    "agentic: mail\n- Use .llm/UNIFIED.llm and CONTEXT.md if present\n- Key commands: ./bin/mail-assistant --help, make test",
)

app = CLIApp(
    "mail-assistant",
    "Mail Assistant CLI for Gmail and Outlook management",
    add_common_args=False,
)

# Default paths for credentials
_default_gmail_credentials = default_gmail_credentials_path()
_default_gmail_token = default_gmail_token_path()
_default_outlook_flow = default_outlook_flow_path()
_default_outlook_token = default_outlook_token_path()


def _lazy_emit_agentic():
    from ..agentic import emit_agentic_context
    return emit_agentic_context


# --- auth command ---
@app.command("auth", help="Authenticate with the mail provider")
@app.argument("--credentials", help=f"Path to OAuth credentials.json (default: {_default_gmail_credentials})")
@app.argument("--token", help=f"Path to token.json (default: {_default_gmail_token})")
@app.argument("--validate", action="store_true", help="Validate existing Gmail token non-interactively")
def cmd_auth(args) -> int:
    return run_auth(args)


# --- backup command ---
@app.command("backup", help="Backup Gmail labels and filters to a timestamped folder")
@app.argument("--credentials", help="Path to OAuth credentials.json")
@app.argument("--token", help="Path to token.json")
@app.argument("--out-dir", help="Output directory (default backups/<timestamp>)")
def cmd_backup(args) -> int:
    return run_backup(args)


# --- labels group ---
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
@labels_group.argument("--out", required=True, help="Output YAML path")
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


# --- filters group ---
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
@filters_group.argument("--out", required=True, help="Output YAML path")
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
@filters_group.argument("--start", required=True, help="Start date YYYY-MM-DD")
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


# --- messages group ---
messages_group = app.group("messages", help="Search, summarize, and reply to messages (Gmail)")


@messages_group.command("search", help="Search for messages and list candidates")
@messages_group.argument("--credentials", help="Path to OAuth credentials.json")
@messages_group.argument("--token", help="Path to token.json")
@messages_group.argument("--query", default="", help="Gmail search query")
@messages_group.argument("--days", type=int, help="Restrict to last N days")
@messages_group.argument("--only-inbox", action="store_true", help="Restrict to inbox")
@messages_group.argument("--max-results", type=int, default=5, help="Max results")
@messages_group.argument("--json", action="store_true", help="Output JSON")
def cmd_messages_search(args) -> int:
    return run_messages_search(args)


@messages_group.command("summarize", help="Summarize a message's content")
@messages_group.argument("--credentials", help="Path to OAuth credentials.json")
@messages_group.argument("--token", help="Path to token.json")
@messages_group.argument("--id", help="Message ID to summarize")
@messages_group.argument("--query", help="Fallback query if id not given")
@messages_group.argument("--days", type=int, help="Restrict query to last N days")
@messages_group.argument("--only-inbox", action="store_true")
@messages_group.argument("--latest", action="store_true", help="Pick latest matching message")
@messages_group.argument("--out", help="Write summary to file")
@messages_group.argument("--max-words", type=int, default=120, help="Max words in summary")
def cmd_messages_summarize(args) -> int:
    return run_messages_summarize(args)


@messages_group.command("reply", help="Draft or send a reply for a message")
@messages_group.argument("--credentials", help="Path to OAuth credentials.json")
@messages_group.argument("--token", help="Path to token.json")
@messages_group.argument("--id", help="Message ID to reply to")
@messages_group.argument("--query", help="Fallback query if id not given")
@messages_group.argument("--days", type=int, help="Restrict query to last N days")
@messages_group.argument("--only-inbox", action="store_true")
@messages_group.argument("--latest", action="store_true", help="Pick latest matching message")
@messages_group.argument("--points", help="Inline bullet points to address")
@messages_group.argument("--points-file", help="YAML file with reply plan")
@messages_group.argument("--tone", default="friendly", help="Reply tone")
@messages_group.argument("--signoff", default="Thanks,", help="Sign-off text")
@messages_group.argument("--include-summary", action="store_true", help="Include auto-summary")
@messages_group.argument("--include-quote", action="store_true", help="Quote original message")
@messages_group.argument("--cc", action="append", default=[], help="CC recipients")
@messages_group.argument("--bcc", action="append", default=[], help="BCC recipients")
@messages_group.argument("--subject", help="Override subject")
@messages_group.argument("--draft-out", help="Write .eml preview path (dry-run)")
@messages_group.argument("--apply", action="store_true", help="Send the reply")
@messages_group.argument("--send-at", help="Schedule send at 'YYYY-MM-DD HH:MM'")
@messages_group.argument("--send-in", help="Schedule send in relative time like '2h30m'")
@messages_group.argument("--plan", action="store_true", help="Plan-only: print intent and exit")
@messages_group.argument("--create-draft", action="store_true", help="Create Gmail Draft (no send)")
def cmd_messages_reply(args) -> int:
    return run_messages_reply(args)


@messages_group.command("apply-scheduled", help="Send scheduled messages that are due")
@messages_group.argument("--max", type=int, default=10, help="Max messages to send")
@messages_group.argument("--profile", help="Only send for specific profile")
def cmd_messages_apply_scheduled(args) -> int:
    return run_messages_apply_scheduled(args)


# --- cache group ---
cache_group = app.group("cache", help="Manage local message cache")


@cache_group.command("stats", help="Show cache stats")
@cache_group.argument("--cache", required=True, help="Cache directory root")
def cmd_cache_stats(args) -> int:
    return run_cache_stats(args)


@cache_group.command("clear", help="Delete entire cache")
@cache_group.argument("--cache", required=True, help="Cache directory root")
def cmd_cache_clear(args) -> int:
    return run_cache_clear(args)


@cache_group.command("prune", help="Prune files older than N days")
@cache_group.argument("--cache", required=True, help="Cache directory root")
@cache_group.argument("--days", type=int, required=True, help="Days threshold")
def cmd_cache_prune(args) -> int:
    return run_cache_prune(args)


# --- auto group ---
auto_group = app.group("auto", help="Gmail: propose/apply categorization + archive")


@auto_group.command("propose", help="Create proposal for categorizing + archiving mail")
@auto_group.argument("--credentials", help="Path to OAuth credentials.json")
@auto_group.argument("--token", help="Path to token.json")
@auto_group.argument("--cache", help="Cache directory")
@auto_group.argument("--days", type=int, default=7, help="Days of messages")
@auto_group.argument("--only-inbox", action="store_true")
@auto_group.argument("--pages", type=int, default=20, help="Pages to fetch")
@auto_group.argument("--batch-size", type=int, default=500)
@auto_group.argument("--log", default="logs/auto_runs.jsonl", help="Log file")
@auto_group.argument("--protect", action="append", default=[], help="Protected senders/domains")
@auto_group.argument("--out", required=True, help="Path to proposal JSON")
@auto_group.argument("--dry-run", action="store_true")
def cmd_auto_propose(args) -> int:
    return run_auto_propose(args)


@auto_group.command("apply", help="Apply a saved proposal (archive + label)")
@auto_group.argument("--credentials", help="Path to OAuth credentials.json")
@auto_group.argument("--token", help="Path to token.json")
@auto_group.argument("--cache", help="Cache directory")
@auto_group.argument("--proposal", required=True, help="Proposal JSON path")
@auto_group.argument("--cutoff-days", type=int, help="Only apply to messages older than N days")
@auto_group.argument("--batch-size", type=int, default=500)
@auto_group.argument("--dry-run", action="store_true")
@auto_group.argument("--log", default="logs/auto_runs.jsonl", help="Log file")
def cmd_auto_apply(args) -> int:
    return run_auto_apply(args)


@auto_group.command("summary", help="Summarize a proposal JSON")
@auto_group.argument("--proposal", required=True, help="Proposal JSON path")
def cmd_auto_summary(args) -> int:
    return run_auto_summary(args)


# --- forwarding group ---
forwarding_group = app.group("forwarding", help="Gmail forwarding configuration")


@forwarding_group.command("list", help="List forwarding addresses")
@forwarding_group.argument("--credentials", help="Path to OAuth credentials.json")
@forwarding_group.argument("--token", help="Path to token.json")
def cmd_forwarding_list(args) -> int:
    return run_forwarding_list(args)


@forwarding_group.command("add", help="Add a forwarding address")
@forwarding_group.argument("--credentials", help="Path to OAuth credentials.json")
@forwarding_group.argument("--token", help="Path to token.json")
@forwarding_group.argument("--email", required=True, help="Email address to add")
def cmd_forwarding_add(args) -> int:
    return run_forwarding_add(args)


@forwarding_group.command("status", help="Check forwarding status")
@forwarding_group.argument("--credentials", help="Path to OAuth credentials.json")
@forwarding_group.argument("--token", help="Path to token.json")
def cmd_forwarding_status(args) -> int:
    return run_forwarding_status(args)


@forwarding_group.command("enable", help="Enable forwarding")
@forwarding_group.argument("--credentials", help="Path to OAuth credentials.json")
@forwarding_group.argument("--token", help="Path to token.json")
@forwarding_group.argument("--email", required=True, help="Address to forward to")
def cmd_forwarding_enable(args) -> int:
    return run_forwarding_enable(args)


@forwarding_group.command("disable", help="Disable forwarding")
@forwarding_group.argument("--credentials", help="Path to OAuth credentials.json")
@forwarding_group.argument("--token", help="Path to token.json")
def cmd_forwarding_disable(args) -> int:
    return run_forwarding_disable(args)


# --- signatures group ---
signatures_group = app.group("signatures", help="Gmail signatures operations")


@signatures_group.command("export", help="Export Gmail signatures to files")
@signatures_group.argument("--credentials", help="Path to OAuth credentials.json")
@signatures_group.argument("--token", help="Path to token.json")
@signatures_group.argument("--out-dir", required=True, help="Output directory")
def cmd_signatures_export(args) -> int:
    return run_signatures_export(args)


@signatures_group.command("sync", help="Sync signatures from files to Gmail")
@signatures_group.argument("--credentials", help="Path to OAuth credentials.json")
@signatures_group.argument("--token", help="Path to token.json")
@signatures_group.argument("--in-dir", required=True, help="Input directory with signatures")
@signatures_group.argument("--dry-run", action="store_true", help="Preview changes")
def cmd_signatures_sync(args) -> int:
    return run_signatures_sync(args)


@signatures_group.command("normalize", help="Normalize signature HTML")
@signatures_group.argument("--input", required=True, help="Input HTML file")
@signatures_group.argument("--output", required=True, help="Output HTML file")
def cmd_signatures_normalize(args) -> int:
    return run_signatures_normalize(args)


# --- config group ---
config_group = app.group("config", help="Inspect and manage configuration")


@config_group.command("inspect", help="Show config with redacted secrets")
@config_group.argument("--path", default="~/.config/credentials.ini", help="Path to INI file")
@config_group.argument("--section", help="Only show a specific section")
@config_group.argument("--only-mail", action="store_true", help="Restrict to mail.* sections")
def cmd_config_inspect(args) -> int:
    return run_config_inspect(args)


@config_group.command("derive.labels", help="Derive Gmail and Outlook labels YAML from unified")
@config_group.argument("--in", dest="in_path", required=True, help="Unified labels YAML")
@config_group.argument("--out-gmail", required=True, help="Output Gmail labels YAML")
@config_group.argument("--out-outlook", required=True, help="Output Outlook categories YAML")
def cmd_config_derive_labels(args) -> int:
    return run_config_derive_labels(args)


@config_group.command("derive.filters", help="Derive Gmail and Outlook filters YAML from unified")
@config_group.argument("--in", dest="in_path", required=True, help="Unified filters YAML")
@config_group.argument("--out-gmail", required=True, help="Output Gmail filters YAML")
@config_group.argument("--out-outlook", required=True, help="Output Outlook rules YAML")
@config_group.argument("--outlook-move-to-folders", action="store_true", dest="outlook_move_to_folders", default=True, help="Encode moveToFolder (default on)")
@config_group.argument("--no-outlook-move-to-folders", action="store_false", dest="outlook_move_to_folders", help="Categories-only on Outlook")
@config_group.argument("--outlook-archive-on-remove-inbox", action="store_true", dest="outlook_archive_on_remove_inbox", help="Move to Archive when INBOX removed")
def cmd_config_derive_filters(args) -> int:
    return run_config_derive_filters(args)


@config_group.command("optimize.filters", help="Optimize unified configs by merging similar rules")
@config_group.argument("--in", dest="in_path", required=True, help="Unified filters YAML")
@config_group.argument("--out", required=True, help="Output optimized YAML")
@config_group.argument("--merge-threshold", type=int, default=2, help="Minimum rules to merge")
@config_group.argument("--preview", action="store_true", help="Print merge summary")
def cmd_config_optimize_filters(args) -> int:
    return run_config_optimize_filters(args)


@config_group.command("audit.filters", help="Audit unified coverage vs provider exports")
@config_group.argument("--in", dest="in_path", required=True, help="Unified filters YAML")
@config_group.argument("--export", dest="export_path", required=True, help="Gmail exported filters YAML")
@config_group.argument("--preview-missing", action="store_true", help="List missing rules")
def cmd_config_audit_filters(args) -> int:
    return run_config_audit_filters(args)


# --- workflows group ---
workflows_group = app.group("workflows", help="Agentic workflows that chain plan/apply steps")


@workflows_group.command("gmail-from-unified", help="Derive Gmail filters from unified YAML, plan, and optionally apply")
@workflows_group.argument("--config", required=True, help="Unified filters YAML")
@workflows_group.argument("--out-dir", default="out", help="Directory for artifacts")
@workflows_group.argument("--delete-missing", action="store_true", help="Include deletions")
@workflows_group.argument("--apply", action="store_true", help="Apply changes after planning")
def cmd_workflows_gmail_from_unified(args) -> int:
    return run_workflows_gmail_from_unified(args)


@workflows_group.command("from-unified", help="Derive provider configs from unified, plan per provider, optionally apply")
@workflows_group.argument("--config", required=True, help="Unified filters YAML")
@workflows_group.argument("--out-dir", default="out", help="Directory for artifacts")
@workflows_group.argument("--providers", help="Comma-separated providers (gmail,outlook)")
@workflows_group.argument("--delete-missing", action="store_true", help="Include deletions")
@workflows_group.argument("--apply", action="store_true", help="Apply changes after planning")
@workflows_group.argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for Outlook defaults")
@workflows_group.argument("--account", help="Account name for Outlook")
@workflows_group.argument("--outlook-move-to-folders", action="store_true", dest="outlook_move_to_folders", default=True)
@workflows_group.argument("--no-outlook-move-to-folders", action="store_false", dest="outlook_move_to_folders")
def cmd_workflows_from_unified(args) -> int:
    return run_workflows_from_unified(args)


# --- env group ---
env_group = app.group("env", help="Environment setup and verification")


@env_group.command("setup", help="Prepare venv and persisted credentials (INI)")
@env_group.argument("--venv-dir", default=".venv", help="Virtualenv directory")
@env_group.argument("--no-venv", action="store_true", help="Skip creating virtualenv")
@env_group.argument("--skip-install", action="store_true", help="Skip pip install")
@env_group.argument("--credentials", help=f"Path to Gmail credentials.json (default: {_default_gmail_credentials})")
@env_group.argument("--token", help=f"Path to Gmail token.json (default: {_default_gmail_token})")
@env_group.argument("--outlook-client-id", help="Azure app (client) ID")
@env_group.argument("--tenant", help="AAD tenant (e.g., consumers)")
@env_group.argument("--outlook-token", help="Path to Outlook token cache JSON")
@env_group.argument("--copy-gmail-example", dest="copy_gmail_example", action="store_true", default=True)
@env_group.argument("--no-copy-gmail-example", dest="copy_gmail_example", action="store_false")
def cmd_env_setup(args) -> int:
    return run_env_setup(args)


# --- accounts group ---
accounts_group = app.group("accounts", help="Operate across multiple email accounts/providers")


@accounts_group.command("list", help="List configured accounts")
@accounts_group.argument("--config", required=True, help="Accounts YAML")
@accounts_group.argument("--accounts", help="Comma-separated list of accounts to include")
@accounts_group.argument("--dry-run", action="store_true")
def cmd_accounts_list(args) -> int:
    return run_accounts_list(args)


@accounts_group.command("export-labels", help="Export labels from all accounts")
@accounts_group.argument("--config", required=True, help="Accounts YAML")
@accounts_group.argument("--accounts", help="Comma-separated list of accounts")
@accounts_group.argument("--out-dir", required=True, help="Output directory")
@accounts_group.argument("--dry-run", action="store_true")
def cmd_accounts_export_labels(args) -> int:
    return run_accounts_export_labels(args)


@accounts_group.command("sync-labels", help="Sync labels to all accounts")
@accounts_group.argument("--config", required=True, help="Accounts YAML")
@accounts_group.argument("--accounts", help="Comma-separated list of accounts")
@accounts_group.argument("--labels", required=True, help="Labels YAML")
@accounts_group.argument("--dry-run", action="store_true")
def cmd_accounts_sync_labels(args) -> int:
    return run_accounts_sync_labels(args)


@accounts_group.command("export-filters", help="Export filters from all accounts")
@accounts_group.argument("--config", required=True, help="Accounts YAML")
@accounts_group.argument("--accounts", help="Comma-separated list of accounts")
@accounts_group.argument("--out-dir", required=True, help="Output directory")
@accounts_group.argument("--dry-run", action="store_true")
def cmd_accounts_export_filters(args) -> int:
    return run_accounts_export_filters(args)


@accounts_group.command("sync-filters", help="Sync filters to all accounts")
@accounts_group.argument("--config", required=True, help="Accounts YAML")
@accounts_group.argument("--accounts", help="Comma-separated list of accounts")
@accounts_group.argument("--filters", required=True, help="Filters YAML")
@accounts_group.argument("--require-forward-verified", action="store_true")
@accounts_group.argument("--dry-run", action="store_true")
def cmd_accounts_sync_filters(args) -> int:
    return run_accounts_sync_filters(args)


@accounts_group.command("plan-labels", help="Plan label changes for all accounts")
@accounts_group.argument("--config", required=True, help="Accounts YAML")
@accounts_group.argument("--accounts", help="Comma-separated list of accounts")
@accounts_group.argument("--labels", required=True, help="Labels YAML")
@accounts_group.argument("--dry-run", action="store_true")
def cmd_accounts_plan_labels(args) -> int:
    return run_accounts_plan_labels(args)


@accounts_group.command("plan-filters", help="Plan filter changes for all accounts")
@accounts_group.argument("--config", required=True, help="Accounts YAML")
@accounts_group.argument("--accounts", help="Comma-separated list of accounts")
@accounts_group.argument("--filters", required=True, help="Filters YAML")
@accounts_group.argument("--dry-run", action="store_true")
def cmd_accounts_plan_filters(args) -> int:
    return run_accounts_plan_filters(args)


@accounts_group.command("export-signatures", help="Export signatures from all accounts")
@accounts_group.argument("--config", required=True, help="Accounts YAML")
@accounts_group.argument("--accounts", help="Comma-separated list of accounts")
@accounts_group.argument("--out-dir", required=True, help="Output directory")
@accounts_group.argument("--dry-run", action="store_true")
def cmd_accounts_export_signatures(args) -> int:
    return run_accounts_export_signatures(args)


@accounts_group.command("sync-signatures", help="Sync signatures to all accounts")
@accounts_group.argument("--config", required=True, help="Accounts YAML")
@accounts_group.argument("--accounts", help="Comma-separated list of accounts")
@accounts_group.argument("--send-as", help="Send-as address")
@accounts_group.argument("--dry-run", action="store_true")
def cmd_accounts_sync_signatures(args) -> int:
    return run_accounts_sync_signatures(args)


# --- outlook group ---
outlook_group = app.group("outlook", help="Outlook-specific operations")

# outlook auth subgroup
@outlook_group.command("auth.device-code", help="Initiate device-code login (non-blocking)")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--out", default=_default_outlook_flow, help=f"Path to store device-flow JSON (default: {_default_outlook_flow})")
def cmd_outlook_auth_device_code(args) -> int:
    return run_outlook_auth_device_code(args)


@outlook_group.command("auth.poll", help="Poll device-code flow and write token cache")
@outlook_group.argument("--flow", default=_default_outlook_flow, help=f"Path to device-flow JSON (default: {_default_outlook_flow})")
@outlook_group.argument("--token", default=_default_outlook_token, help=f"Path to token cache output (default: {_default_outlook_token})")
def cmd_outlook_auth_poll(args) -> int:
    return run_outlook_auth_poll(args)


@outlook_group.command("auth.ensure", help="Ensure valid Outlook token (silent refresh or device-code)")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
def cmd_outlook_auth_ensure(args) -> int:
    return run_outlook_auth_ensure(args)


@outlook_group.command("auth.validate", help="Validate Outlook token non-interactively")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
def cmd_outlook_auth_validate(args) -> int:
    return run_outlook_auth_validate(args)


# outlook rules subgroup
@outlook_group.command("rules.list", help="List Outlook Inbox rules")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--use-cache", action="store_true", help="Use cached rules")
@outlook_group.argument("--cache-ttl", type=int, default=600, help="Cache TTL seconds")
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_rules_list(args) -> int:
    return run_outlook_rules_list(args)


@outlook_group.command("rules.export", help="Export Outlook rules to filters YAML")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--out", required=True, help="Output YAML path")
@outlook_group.argument("--use-cache", action="store_true")
@outlook_group.argument("--cache-ttl", type=int, default=600)
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_rules_export(args) -> int:
    return run_outlook_rules_export(args)


@outlook_group.command("rules.plan", help="Plan Outlook rule changes from filters YAML")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--config", required=True, help="Filters YAML")
@outlook_group.argument("--use-cache", action="store_true")
@outlook_group.argument("--cache-ttl", type=int, default=600)
@outlook_group.argument("--move-to-folders", action="store_true", dest="move_to_folders", default=True)
@outlook_group.argument("--categories-only", action="store_false", dest="move_to_folders")
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_rules_plan(args) -> int:
    return run_outlook_rules_plan(args)


@outlook_group.command("rules.sync", help="Sync rules from filters YAML into Outlook Inbox")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--config", required=True, help="Filters YAML")
@outlook_group.argument("--dry-run", action="store_true")
@outlook_group.argument("--move-to-folders", action="store_true", dest="move_to_folders", default=True)
@outlook_group.argument("--categories-only", action="store_false", dest="move_to_folders")
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
@outlook_group.argument("--delete-missing", action="store_true", help="Delete rules not in YAML")
def cmd_outlook_rules_sync(args) -> int:
    return run_outlook_rules_sync(args)


@outlook_group.command("rules.delete", help="Delete an Outlook rule by ID")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--id", required=True, help="Rule ID to delete")
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_rules_delete(args) -> int:
    return run_outlook_rules_delete(args)


@outlook_group.command("rules.sweep", help="Apply folder moves to existing messages")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--config", required=True, help="Filters YAML")
@outlook_group.argument("--days", type=int, default=30, help="Only sweep messages in last N days")
@outlook_group.argument("--pages", type=int, default=2, help="Pages to search per rule")
@outlook_group.argument("--top", type=int, default=25, help="Page size")
@outlook_group.argument("--move-to-folders", action="store_true", dest="move_to_folders", default=True)
@outlook_group.argument("--categories-only", action="store_false", dest="move_to_folders")
@outlook_group.argument("--dry-run", action="store_true")
@outlook_group.argument("--clear-cache", action="store_true", help="Clear caches before running")
@outlook_group.argument("--use-cache", action="store_true")
@outlook_group.argument("--cache-ttl", type=int, default=600)
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_rules_sweep(args) -> int:
    return run_outlook_rules_sweep(args)


# outlook calendar subgroup
@outlook_group.command("calendar.add", help="Add a one-time event to a calendar")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", help="Calendar name (defaults to primary)")
@outlook_group.argument("--subject", required=True, help="Event subject")
@outlook_group.argument("--start", required=True, help="Start datetime ISO")
@outlook_group.argument("--end", required=True, help="End datetime ISO")
@outlook_group.argument("--tz", help="Time zone (IANA or Windows)")
@outlook_group.argument("--location", help="Location display name")
@outlook_group.argument("--body-html", dest="body_html", help="HTML body content")
@outlook_group.argument("--all-day", action="store_true", help="Mark as all-day")
@outlook_group.argument("--no-reminder", action="store_true", help="No reminders")
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_calendar_add(args) -> int:
    return run_outlook_calendar_add(args)


@outlook_group.command("calendar.add-recurring", help="Add a recurring event with optional exclusions")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", help="Calendar name (defaults to primary)")
@outlook_group.argument("--subject", required=True, help="Event subject")
@outlook_group.argument("--repeat", required=True, choices=["daily", "weekly", "monthly"], help="Recurrence type")
@outlook_group.argument("--interval", type=int, default=1, help="Recurrence interval")
@outlook_group.argument("--byday", help="Days for weekly (e.g., MO,WE,FR)")
@outlook_group.argument("--range-start", required=True, dest="range_start", help="Start date YYYY-MM-DD")
@outlook_group.argument("--until", help="End date YYYY-MM-DD")
@outlook_group.argument("--count", type=int, help="Occurrences count")
@outlook_group.argument("--start-time", required=True, help="Start time HH:MM[:SS]")
@outlook_group.argument("--end-time", required=True, help="End time HH:MM[:SS]")
@outlook_group.argument("--tz", help="Time zone (IANA or Windows)")
@outlook_group.argument("--location", help="Location display name")
@outlook_group.argument("--body-html", dest="body_html", help="HTML body content")
@outlook_group.argument("--exdates", help="Comma-separated YYYY-MM-DD dates to exclude")
@outlook_group.argument("--no-reminder", action="store_true", help="No reminders")
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_calendar_add_recurring(args) -> int:
    return run_outlook_calendar_add_recurring(args)


@outlook_group.command("calendar.add-from-config", help="Add events defined in a YAML file")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--config", required=True, help="YAML with events: [] entries")
@outlook_group.argument("--no-reminder", action="store_true", help="No reminders")
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_calendar_add_from_config(args) -> int:
    return run_outlook_calendar_add_from_config(args)


# outlook categories subgroup
@outlook_group.command("categories.list", help="List Outlook categories")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--use-cache", action="store_true")
@outlook_group.argument("--cache-ttl", type=int, default=600)
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_categories_list(args) -> int:
    return run_outlook_categories_list(args)


@outlook_group.command("categories.export", help="Export categories to YAML")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--out", required=True, help="Output YAML path")
@outlook_group.argument("--use-cache", action="store_true")
@outlook_group.argument("--cache-ttl", type=int, default=600)
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_categories_export(args) -> int:
    return run_outlook_categories_export(args)


@outlook_group.command("categories.sync", help="Sync categories from labels YAML")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--config", required=True, help="Labels YAML")
@outlook_group.argument("--dry-run", action="store_true")
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_categories_sync(args) -> int:
    return run_outlook_categories_sync(args)


# outlook folders subgroup
@outlook_group.command("folders.sync", help="Create Outlook folders from labels YAML")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--config", required=True, help="Labels YAML")
@outlook_group.argument("--dry-run", action="store_true")
@outlook_group.argument("--accounts-config", default="config/accounts.yaml")
@outlook_group.argument("--account", help="Account name for defaults")
def cmd_outlook_folders_sync(args) -> int:
    return run_outlook_folders_sync(args)


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the Mail Assistant CLI."""
    # Install conservative secret shielding for stdout/stderr (env-toggled)
    # This is best-effort: if masking module is unavailable or fails to initialize,
    # the CLI continues normally without output masking.
    try:
        from ..utils.secrets import install_output_masking_from_env as _install_mask
        _install_mask()
    except Exception as e:  # nosec B110 - best-effort masking, safe to continue without
        import sys
        print(f"Warning: Output masking unavailable ({type(e).__name__}), continuing without secret shielding", file=sys.stderr)

    parser = app.build_parser()
    # Add top-level args before agentic flags
    parser.add_argument("--profile", help="Credentials profile (INI section suffix)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    assistant.add_agentic_flags(parser)

    args = parser.parse_args(argv)

    agentic_result = assistant.maybe_emit_agentic(
        args,
        emit_func=_lazy_emit_agentic(),
    )
    if agentic_result is not None:
        return agentic_result

    cmd_func = getattr(args, "_cmd_func", None)
    if not cmd_func:
        parser.print_help()
        return 0

    return int(cmd_func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
