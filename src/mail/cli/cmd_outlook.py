"""Outlook command group registration for Mail Assistant CLI."""
from __future__ import annotations

from typing import Any

from core.cli_framework import CLIApp
from core.cli_help_text import HELP_PAGE_SIZE, HELP_START_DATE, HELP_YAML_OUT

# One argparse argument: the flag names, plus the kwargs forwarded to
# add_argument(). Values are heterogeneous (str, bool, int), hence Any.
ArgSpec = tuple[tuple[str, ...], dict[str, Any]]

# Repeated help-text strings extracted as module-level constants
HELP_CLIENT_ID = "Azure app (client) ID"
HELP_TENANT = "AAD tenant"
HELP_TOKEN_CACHE = "Path to token cache JSON"  # nosec B105 - argparse help text, not a credential

_ACCOUNTS_CONFIG: ArgSpec = (("--accounts-config",), {"default": "config/accounts.yaml"})
_ACCOUNT: ArgSpec = (("--account",), {"help": "Account name for defaults"})

# Shared Outlook auth trio used by most subcommands
_OUTLOOK_AUTH_ARGS: tuple[ArgSpec, ...] = (
    (("--client-id",), {"help": HELP_CLIENT_ID}),
    (("--tenant",), {"default": "consumers", "help": HELP_TENANT}),
    (("--token",), {"help": HELP_TOKEN_CACHE}),
)

# Cache-related args shared across several list/export commands
_CACHE_ARGS: tuple[ArgSpec, ...] = (
    (("--use-cache",), {"action": "store_true", "help": "Use cached rules"}),
    (("--cache-ttl",), {"type": int, "default": 600, "help": "Cache TTL seconds"}),
)

# Move-to-folders flag pair used by rules.plan, rules.sync, rules.sweep
_MOVE_TO_FOLDERS_ARGS: tuple[ArgSpec, ...] = (
    (("--move-to-folders",), {"action": "store_true", "dest": "move_to_folders", "default": True}),
    (("--categories-only",), {"action": "store_false", "dest": "move_to_folders"}),
)

_DRY_RUN: ArgSpec = (("--dry-run",), {"action": "store_true"})


def register_outlook_commands(app: CLIApp) -> object:
    """Register all outlook subcommands on app and return the outlook group."""
    from ..outlook.commands import (
        run_outlook_messages_search,
        run_outlook_messages_summarize,
        run_outlook_rules_list,
        run_outlook_rules_export,
        run_outlook_rules_sync,
        run_outlook_rules_plan,
        run_outlook_rules_delete,
        run_outlook_rules_sweep,
        run_outlook_rules_prune_empty,
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
    from ..config_resolver import (
        default_outlook_flow_path,
        default_outlook_token_path,
    )

    _default_outlook_flow = default_outlook_flow_path()
    _default_outlook_token = default_outlook_token_path()

    # (subcommand, help, handler, args — full arg list, not appended)
    specs: list[tuple[str, str, Any, list[ArgSpec]]] = [
        # outlook auth subgroup
        ("auth.device-code", "Initiate device-code login (non-blocking)", run_outlook_auth_device_code, [
            (("--client-id",), {"help": HELP_CLIENT_ID}),
            (("--tenant",), {"default": "consumers", "help": HELP_TENANT}),
            (("--out",), {"default": _default_outlook_flow, "help": f"Path to store device-flow JSON (default: {_default_outlook_flow})"}),
        ]),
        ("auth.poll", "Poll device-code flow and write token cache", run_outlook_auth_poll, [
            (("--flow",), {"default": _default_outlook_flow, "help": f"Path to device-flow JSON (default: {_default_outlook_flow})"}),
            (("--token",), {"default": _default_outlook_token, "help": f"Path to token cache output (default: {_default_outlook_token})"}),  # nosec B105 - argparse help text, not a credential
        ]),
        ("auth.ensure", "Ensure valid Outlook token (silent refresh or device-code)", run_outlook_auth_ensure, [
            (("--client-id",), {"help": HELP_CLIENT_ID}),
            (("--tenant",), {"default": "consumers", "help": HELP_TENANT}),
            (("--token",), {"help": HELP_TOKEN_CACHE}),
        ]),
        ("auth.validate", "Validate Outlook token non-interactively", run_outlook_auth_validate, [
            (("--client-id",), {"help": HELP_CLIENT_ID}),
            (("--tenant",), {"default": "consumers", "help": HELP_TENANT}),
            (("--token",), {"help": HELP_TOKEN_CACHE}),
        ]),
        # outlook rules subgroup
        ("rules.list", "List Outlook Inbox rules", run_outlook_rules_list, [
            *_OUTLOOK_AUTH_ARGS,
            *_CACHE_ARGS,
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        ("rules.export", "Export Outlook rules to filters YAML", run_outlook_rules_export, [
            *_OUTLOOK_AUTH_ARGS,
            (("--out",), {"required": True, "help": HELP_YAML_OUT}),
            (("--use-cache",), {"action": "store_true"}),
            (("--cache-ttl",), {"type": int, "default": 600}),
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        ("rules.plan", "Plan Outlook rule changes from filters YAML", run_outlook_rules_plan, [
            *_OUTLOOK_AUTH_ARGS,
            (("--config",), {"required": True, "help": "Filters YAML"}),
            (("--use-cache",), {"action": "store_true"}),
            (("--cache-ttl",), {"type": int, "default": 600}),
            *_MOVE_TO_FOLDERS_ARGS,
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        ("rules.sync", "Sync rules from filters YAML into Outlook Inbox", run_outlook_rules_sync, [
            *_OUTLOOK_AUTH_ARGS,
            (("--config",), {"required": True, "help": "Filters YAML"}),
            _DRY_RUN,
            *_MOVE_TO_FOLDERS_ARGS,
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
            (("--delete-missing",), {"action": "store_true", "help": "Delete rules not in YAML"}),
        ]),
        ("rules.delete", "Delete an Outlook rule by ID", run_outlook_rules_delete, [
            *_OUTLOOK_AUTH_ARGS,
            (("--id",), {"required": True, "help": "Rule ID to delete"}),
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        ("rules.prune-empty", "Delete Outlook rules with no conditions or actions", run_outlook_rules_prune_empty, [
            *_OUTLOOK_AUTH_ARGS,
            (("--dry-run",), {"action": "store_true", "help": "Preview changes"}),
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        ("rules.sweep", "Apply folder moves to existing messages", run_outlook_rules_sweep, [
            *_OUTLOOK_AUTH_ARGS,
            (("--config",), {"required": True, "help": "Filters YAML"}),
            (("--days",), {"type": int, "default": 30, "help": "Only sweep messages in last N days"}),
            (("--pages",), {"type": int, "default": 2, "help": "Pages to search per rule"}),
            (("--top",), {"type": int, "default": 25, "help": HELP_PAGE_SIZE}),
            *_MOVE_TO_FOLDERS_ARGS,
            _DRY_RUN,
            (("--clear-cache",), {"action": "store_true", "help": "Clear caches before running"}),
            (("--use-cache",), {"action": "store_true"}),
            (("--cache-ttl",), {"type": int, "default": 600}),
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        # outlook calendar subgroup
        ("calendar.add", "Add a one-time event to a calendar", run_outlook_calendar_add, [
            *_OUTLOOK_AUTH_ARGS,
            (("--calendar",), {"help": "Calendar name (defaults to primary)"}),
            (("--subject",), {"required": True, "help": "Event subject"}),
            (("--start",), {"required": True, "help": "Start datetime ISO"}),
            (("--end",), {"required": True, "help": "End datetime ISO"}),
            (("--tz",), {"help": "Time zone (IANA or Windows)"}),
            (("--location",), {"help": "Location display name"}),
            (("--body-html",), {"dest": "body_html", "help": "HTML body content"}),
            (("--all-day",), {"action": "store_true", "help": "Mark as all-day"}),
            (("--no-reminder",), {"action": "store_true", "help": "No reminders"}),
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        ("calendar.add-recurring", "Add a recurring event with optional exclusions", run_outlook_calendar_add_recurring, [
            *_OUTLOOK_AUTH_ARGS,
            (("--calendar",), {"help": "Calendar name (defaults to primary)"}),
            (("--subject",), {"required": True, "help": "Event subject"}),
            (("--repeat",), {"required": True, "choices": ["daily", "weekly", "monthly"], "help": "Recurrence type"}),
            (("--interval",), {"type": int, "default": 1, "help": "Recurrence interval"}),
            (("--byday",), {"help": "Days for weekly (e.g., MO,WE,FR)"}),
            (("--range-start",), {"required": True, "dest": "range_start", "help": HELP_START_DATE}),
            (("--until",), {"help": "End date YYYY-MM-DD"}),
            (("--count",), {"type": int, "help": "Occurrences count"}),
            (("--start-time",), {"required": True, "help": "Start time HH:MM[:SS]"}),
            (("--end-time",), {"required": True, "help": "End time HH:MM[:SS]"}),
            (("--tz",), {"help": "Time zone (IANA or Windows)"}),
            (("--location",), {"help": "Location display name"}),
            (("--body-html",), {"dest": "body_html", "help": "HTML body content"}),
            (("--exdates",), {"help": "Comma-separated YYYY-MM-DD dates to exclude"}),
            (("--no-reminder",), {"action": "store_true", "help": "No reminders"}),
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        ("calendar.add-from-config", "Add events defined in a YAML file", run_outlook_calendar_add_from_config, [
            *_OUTLOOK_AUTH_ARGS,
            (("--config",), {"required": True, "help": "YAML with events: [] entries"}),
            (("--no-reminder",), {"action": "store_true", "help": "No reminders"}),
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        # outlook categories subgroup
        ("categories.list", "List Outlook categories", run_outlook_categories_list, [
            *_OUTLOOK_AUTH_ARGS,
            (("--use-cache",), {"action": "store_true"}),
            (("--cache-ttl",), {"type": int, "default": 600}),
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        ("categories.export", "Export categories to YAML", run_outlook_categories_export, [
            *_OUTLOOK_AUTH_ARGS,
            (("--out",), {"required": True, "help": HELP_YAML_OUT}),
            (("--use-cache",), {"action": "store_true"}),
            (("--cache-ttl",), {"type": int, "default": 600}),
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        ("categories.sync", "Sync categories from labels YAML", run_outlook_categories_sync, [
            *_OUTLOOK_AUTH_ARGS,
            (("--config",), {"required": True, "help": "Labels YAML"}),
            _DRY_RUN,
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        # outlook folders subgroup
        ("folders.sync", "Create Outlook folders from labels YAML", run_outlook_folders_sync, [
            *_OUTLOOK_AUTH_ARGS,
            (("--config",), {"required": True, "help": "Labels YAML"}),
            _DRY_RUN,
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        # outlook messages subgroup
        ("messages.search", "Search Outlook messages across all folders", run_outlook_messages_search, [
            *_OUTLOOK_AUTH_ARGS,
            (("--query",), {"default": "", "help": "KQL search query"}),
            (("--top",), {"type": int, "default": 50, "help": HELP_PAGE_SIZE}),
            (("--pages",), {"type": int, "default": 3, "help": "Max pages to fetch"}),
            (("--after",), {"help": "Only messages received after ISO date (e.g. 2025-01-01)"}),
            (("--days",), {"type": int, "help": "Only messages from last N days (converted to --after)"}),
            (("--sender",), {"help": "Filter by sender using KQL from: term (email or domain, e.g. brightchamps.com)"}),
            (("--only-inbox",), {"action": "store_true", "help": "Restrict to Inbox folder"}),
            (("--json",), {"action": "store_true", "help": "Output JSON"}),
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
        ("messages.summarize", "Summarize an Outlook message", run_outlook_messages_summarize, [
            *_OUTLOOK_AUTH_ARGS,
            (("--id",), {"help": "Message ID to summarize"}),
            (("--query",), {"help": "KQL query to find message (fallback if --id not given)"}),
            (("--top",), {"type": int, "default": 5, "help": "Max results when searching by query"}),
            (("--pages",), {"type": int, "default": 1, "help": "Pages to fetch when searching by query"}),
            (("--max-words",), {"type": int, "default": 120, "dest": "max_words", "help": "Max words in summary"}),
            (("--out",), {"help": "Write summary to file"}),
            _ACCOUNTS_CONFIG,
            _ACCOUNT,
        ]),
    ]

    outlook_group = app.group("outlook", help="Outlook-specific operations")
    for name, help_text, handler, args in specs:
        outlook_group.register(name, help_text, handler, args)
    return outlook_group
