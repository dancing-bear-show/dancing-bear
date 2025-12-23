"""
Mail Assistant CLI

This is a hand-restored implementation sufficient to provide a working CLI
and a foundation for rebuilding features. It avoids importing optional
dependencies (like PyYAML or Google APIs) at module import time so that
`python -m mail_assistant --help` works even if those packages are missing.
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path
from typing import Optional, Iterable
from .utils.cli_helpers import with_gmail_client as _with_gmail_client
from core.assistant import BaseAssistant
from core.auth import resolve_outlook_credentials
from .config_resolver import (
    default_gmail_credentials_path,
    default_gmail_token_path,
    default_outlook_flow_path,
    default_outlook_token_path,
    expand_path,
    resolve_paths_profile,
)
from .utils.plan import print_plan_summary

# Pipeline command imports
from .signatures.commands import (
    run_signatures_export,
    run_signatures_sync,
    run_signatures_normalize,
)
from .auto.commands import (
    run_auto_propose,
    run_auto_summary,
    run_auto_apply,
)
from .forwarding.commands import (
    run_forwarding_list,
    run_forwarding_add,
    run_forwarding_status,
    run_forwarding_enable,
    run_forwarding_disable,
)
from .outlook.commands import (
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
from .outlook.helpers import resolve_outlook_args as _resolve_outlook_args


CLI_DESCRIPTION = "Mail Assistant CLI"


assistant = BaseAssistant(
    "mail_assistant",
    "agentic: mail_assistant\n- Use .llm/UNIFIED.llm and CONTEXT.md if present\n- Key commands: ./bin/mail-assistant --help, make test",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
    assistant.add_agentic_flags(parser)
    parser.add_argument("--profile", help="Credentials profile (INI section suffix, e.g., gmail_personal)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging for long operations")
    sub = parser.add_subparsers(dest="command")
    from .cli.args import add_gmail_common_args as _add_gmail_args
    default_gmail_credentials = default_gmail_credentials_path()
    default_gmail_token = default_gmail_token_path()
    default_outlook_flow = default_outlook_flow_path()
    default_outlook_token = default_outlook_token_path()

    # auth
    p_auth = sub.add_parser("auth", help="Authenticate with the mail provider")
    p_auth.add_argument("--credentials", type=str, help=f"Path to OAuth credentials.json (default: {default_gmail_credentials})")
    p_auth.add_argument("--token", type=str, help=f"Path to token.json (writeable; default: {default_gmail_token})")
    p_auth.add_argument("--validate", action="store_true", help="Validate existing Gmail token non-interactively (no browser)")
    p_auth.set_defaults(func=_cmd_auth)

    # labels group (registered via helper)
    from .cli.labels import register as _register_labels

    _register_labels(
        sub,
        f_list=_cmd_labels_list,
        f_sync=_cmd_labels_sync,
        f_export=_cmd_labels_export,
        f_plan=_cmd_labels_plan,
        f_doctor=_cmd_labels_doctor,
        f_prune_empty=_cmd_labels_prune_empty,
        f_learn=_cmd_labels_learn,
        f_apply_suggestions=_cmd_labels_apply_suggestions,
        f_delete=_cmd_labels_delete,
        f_sweep_parents=_cmd_labels_sweep_parents,
    )

    # filters group (registered via helper)
    from .cli.filters import register as _register_filters

    _register_filters(
        sub,
        f_list=_cmd_filters_list,
        f_export=_cmd_filters_export,
        f_sync=_cmd_filters_sync,
        f_plan=_cmd_filters_plan,
        f_impact=_cmd_filters_impact,
        f_sweep=_cmd_filters_sweep,
        f_sweep_range=_cmd_filters_sweep_range,
        f_delete=_cmd_filters_delete,
        f_prune_empty=_cmd_filters_prune_empty,
        f_add_forward_by_label=_cmd_filters_add_forward_by_label,
        f_add_from_token=_cmd_filters_add_from_token,
        f_rm_from_token=_cmd_filters_rm_from_token,
    )

    # messages group (search, summarize, reply)
    p_msgs = sub.add_parser("messages", help="Search, summarize, and reply to messages (Gmail)")
    _add_gmail_args(p_msgs)
    sub_msgs = p_msgs.add_subparsers(dest="messages_cmd")

    # messages search
    p_msgs_search = sub_msgs.add_parser("search", help="Search for messages and list candidates")
    p_msgs_search.add_argument("--query", type=str, default="", help="Gmail search query (e.g., from:foo@example.com)")
    p_msgs_search.add_argument("--days", type=int, help="Restrict to last N days")
    p_msgs_search.add_argument("--only-inbox", action="store_true", help="Restrict search to inbox")
    p_msgs_search.add_argument("--max-results", type=int, default=5)
    p_msgs_search.add_argument("--json", action="store_true", help="Output JSON instead of table")
    p_msgs_search.set_defaults(func=_cmd_messages_search)

    # messages summarize
    p_msgs_sum = sub_msgs.add_parser("summarize", help="Summarize a message's content")
    p_msgs_sum.add_argument("--id", type=str, help="Message ID to summarize")
    p_msgs_sum.add_argument("--query", type=str, help="Fallback query to pick latest message if id not given")
    p_msgs_sum.add_argument("--days", type=int, help="Restrict query to last N days")
    p_msgs_sum.add_argument("--only-inbox", action="store_true")
    p_msgs_sum.add_argument("--latest", action="store_true", help="Pick latest matching message when using --query")
    p_msgs_sum.add_argument("--out", type=str, help="Write summary to this file (else stdout)")
    p_msgs_sum.add_argument("--max-words", type=int, default=120)
    p_msgs_sum.set_defaults(func=_cmd_messages_summarize)

    # messages reply
    p_msgs_reply = sub_msgs.add_parser("reply", help="Draft or send a reply for a message")
    p_msgs_reply.add_argument("--id", type=str, help="Message ID to reply to")
    p_msgs_reply.add_argument("--query", type=str, help="Fallback query to pick latest message if id not given")
    p_msgs_reply.add_argument("--days", type=int, help="Restrict query to last N days")
    p_msgs_reply.add_argument("--only-inbox", action="store_true")
    p_msgs_reply.add_argument("--latest", action="store_true", help="Pick latest matching message when using --query")
    p_msgs_reply.add_argument("--points", type=str, help="Inline bullet points to address in reply")
    p_msgs_reply.add_argument("--points-file", type=str, help="YAML file with reply plan (goals, tone, signoff, ask)")
    p_msgs_reply.add_argument("--tone", type=str, default="friendly")
    p_msgs_reply.add_argument("--signoff", type=str, default="Thanks,")
    p_msgs_reply.add_argument("--include-summary", action="store_true", help="Include an auto-summary at top")
    p_msgs_reply.add_argument("--include-quote", action="store_true", help="Quote the original message below")
    p_msgs_reply.add_argument("--cc", action="append", default=[], help="CC recipients (repeatable)")
    p_msgs_reply.add_argument("--bcc", action="append", default=[], help="BCC recipients (repeatable)")
    p_msgs_reply.add_argument("--subject", type=str, help="Override subject (defaults to Re: original)")
    p_msgs_reply.add_argument("--draft-out", type=str, help="Write a .eml preview to this path (dry-run)")
    p_msgs_reply.add_argument("--apply", action="store_true", help="Send the reply (prints preview or writes .eml otherwise)")
    p_msgs_reply.add_argument("--send-at", type=str, help="Schedule send at local time 'YYYY-MM-DD HH:MM' (implies --apply)")
    p_msgs_reply.add_argument("--send-in", type=str, help="Schedule send in relative time like '2h30m' (implies --apply)")
    p_msgs_reply.add_argument("--plan", action="store_true", help="Plan-only: print intent (to/subject/when) and exit")
    p_msgs_reply.add_argument("--create-draft", action="store_true", help="Create a Gmail Draft (no send)")
    p_msgs_reply.set_defaults(func=_cmd_messages_reply)

    # messages apply-scheduled
    p_msgs_apply = sub_msgs.add_parser("apply-scheduled", help="Send any scheduled messages that are due now")
    p_msgs_apply.add_argument("--max", type=int, default=10, help="Max messages to send in one run")
    p_msgs_apply.add_argument("--profile", type=str, help="Only send for a specific profile")
    p_msgs_apply.set_defaults(func=_cmd_messages_apply_scheduled)

    # backup group
    p_backup = sub.add_parser("backup", help="Backup Gmail labels and filters to a timestamped folder")
    _add_gmail_args(p_backup)
    p_backup.add_argument("--out-dir", help="Output directory (default backups/<timestamp>)")
    p_backup.set_defaults(func=_cmd_backup)

    # cache group (MailCache operations)
    p_cache = sub.add_parser("cache", help="Manage local message cache")
    p_cache.add_argument("--cache", required=True, help="Cache directory root")
    sub_cache = p_cache.add_subparsers(dest="cache_cmd")
    p_cache_stats = sub_cache.add_parser("stats", help="Show cache stats")
    p_cache_stats.set_defaults(func=_cmd_cache_stats)
    p_cache_clear = sub_cache.add_parser("clear", help="Delete entire cache")
    p_cache_clear.set_defaults(func=_cmd_cache_clear)
    p_cache_prune = sub_cache.add_parser("prune", help="Prune files older than N days")
    p_cache_prune.add_argument("--days", type=int, required=True)
    p_cache_prune.set_defaults(func=_cmd_cache_prune)

    # auto-sweep group (Gmail): propose/apply categorization+archive
    p_auto = sub.add_parser("auto", help="Gmail: propose/apply categorization + archive for low-interest inbox mail")
    sub_auto = p_auto.add_subparsers(dest="auto_cmd")
    common_auto = {
        "--credentials": {"type": str},
        "--token": {"type": str},
        "--cache": {"type": str},
        "--days": {"type": int, "default": 7},
        "--only-inbox": {"action": "store_true"},
        "--pages": {"type": int, "default": 20},
        "--batch-size": {"type": int, "default": 500},
        "--log": {"type": str, "default": "logs/auto_runs.jsonl"},
        "--protect": {"action": "append", "default": [], "help": "Protected senders/domains to skip (e.g., wife@example.com, @family.com)"},
    }
    p_auto_propose = sub_auto.add_parser("propose", help="Create a proposal for categorizing + archiving low-interest mail")
    for k, v in common_auto.items():
        p_auto_propose.add_argument(k, **v)
    p_auto_propose.add_argument("--out", required=True, help="Path to proposal JSON")
    p_auto_propose.add_argument("--dry-run", action="store_true")
    p_auto_propose.set_defaults(func=run_auto_propose)

    p_auto_apply = sub_auto.add_parser("apply", help="Apply a saved proposal (archive + label)")
    p_auto_apply.add_argument("--credentials", type=str)
    p_auto_apply.add_argument("--token", type=str)
    p_auto_apply.add_argument("--cache", type=str)
    p_auto_apply.add_argument("--proposal", required=True)
    p_auto_apply.add_argument("--cutoff-days", type=int, help="Only apply to messages older than N days")
    p_auto_apply.add_argument("--batch-size", type=int, default=500)
    p_auto_apply.add_argument("--dry-run", action="store_true")
    p_auto_apply.add_argument("--log", type=str, default="logs/auto_runs.jsonl")
    p_auto_apply.set_defaults(func=run_auto_apply)

    p_auto_summary = sub_auto.add_parser("summary", help="Summarize a proposal JSON")
    p_auto_summary.add_argument("--proposal", required=True)
    p_auto_summary.set_defaults(func=run_auto_summary)

    # forwarding group (registered via helper to keep this lean)
    from .cli.forwarding import register as _register_forwarding

    _register_forwarding(
        sub,
        f_list=run_forwarding_list,
        f_add=run_forwarding_add,
        f_status=run_forwarding_status,
        f_enable=run_forwarding_enable,
        f_disable=run_forwarding_disable,
    )

    # signatures group (registered via helper)
    from .cli.signatures import register as _register_signatures

    _register_signatures(
        sub,
        f_export=run_signatures_export,
        f_sync=run_signatures_sync,
        f_normalize=run_signatures_normalize,
    )

    # config group (inspect/redacted view)
    p_cfg = sub.add_parser("config", help="Inspect and manage configuration")
    sub_cfg = p_cfg.add_subparsers(dest="config_cmd")
    p_cfg_inspect = sub_cfg.add_parser("inspect", help="Show config with redacted secrets")
    p_cfg_inspect.add_argument("--path", default="~/.config/credentials.ini", help="Path to INI file")
    p_cfg_inspect.add_argument("--section", help="Only show a specific section")
    p_cfg_inspect.add_argument("--only-mail", action="store_true", help="Restrict to mail_assistant.* sections")
    p_cfg_inspect.set_defaults(func=_cmd_config_inspect)

    p_cfg_derive = sub_cfg.add_parser("derive", help="Derive provider-specific configs from a unified YAML")
    sub_cfg_derive = p_cfg_derive.add_subparsers(dest="derive_cmd")
    p_cfg_derive_labels = sub_cfg_derive.add_parser("labels", help="Derive Gmail and Outlook labels YAML from unified labels.yaml")
    p_cfg_derive_labels.add_argument("--in", dest="in_path", required=True, help="Unified labels YAML (labels: [])")
    p_cfg_derive_labels.add_argument("--out-gmail", required=True, help="Output Gmail labels YAML")
    p_cfg_derive_labels.add_argument("--out-outlook", required=True, help="Output Outlook categories YAML")
    p_cfg_derive_labels.set_defaults(func=_cmd_config_derive_labels)

    p_cfg_derive_filters = sub_cfg_derive.add_parser("filters", help="Derive Gmail and Outlook filters YAML from unified filters.yaml")
    p_cfg_derive_filters.add_argument("--in", dest="in_path", required=True, help="Unified filters YAML (filters: [])")
    p_cfg_derive_filters.add_argument("--out-gmail", required=True, help="Output Gmail filters YAML")
    p_cfg_derive_filters.add_argument("--out-outlook", required=True, help="Output Outlook rules YAML")
    # Parity default: enable Outlook move-to-folder derivation by default
    p_cfg_derive_filters.set_defaults(outlook_move_to_folders=True)
    p_cfg_derive_filters.add_argument("--outlook-move-to-folders", action="store_true", dest="outlook_move_to_folders", help="Encode moveToFolder from first added label for Outlook (default on)")
    p_cfg_derive_filters.add_argument("--no-outlook-move-to-folders", action="store_false", dest="outlook_move_to_folders", help="Do not encode moveToFolder; categories-only on Outlook")
    p_cfg_derive_filters.add_argument(
        "--outlook-archive-on-remove-inbox",
        action="store_true",
        dest="outlook_archive_on_remove_inbox",
        help="When YAML removes INBOX, derive Outlook rules that move to Archive",
    )
    p_cfg_derive_filters.set_defaults(func=_cmd_config_derive_filters)

    # config optimize
    p_cfg_opt = sub_cfg.add_parser("optimize", help="Optimize unified configs by merging similar rules")
    sub_cfg_opt = p_cfg_opt.add_subparsers(dest="optimize_cmd")
    p_cfg_opt_filters = sub_cfg_opt.add_parser("filters", help="Merge rules with same destination label and simple from criteria")
    p_cfg_opt_filters.add_argument("--in", dest="in_path", required=True, help="Unified filters YAML (filters: [])")
    p_cfg_opt_filters.add_argument("--out", required=True, help="Output optimized unified filters YAML")
    p_cfg_opt_filters.add_argument("--merge-threshold", type=int, default=2, help="Minimum number of rules to merge (default 2)")
    p_cfg_opt_filters.add_argument("--preview", action="store_true", help="Print a summary of merges")
    p_cfg_opt_filters.set_defaults(func=_cmd_config_optimize_filters)

    # config audit
    p_cfg_audit = sub_cfg.add_parser("audit", help="Audit unified coverage vs provider exports")
    sub_cfg_audit = p_cfg_audit.add_subparsers(dest="audit_cmd")
    p_cfg_audit_filters = sub_cfg_audit.add_parser("filters", help="Report percentage of simple Gmail rules not present in unified config")
    p_cfg_audit_filters.add_argument("--in", dest="in_path", required=True, help="Unified filters YAML (filters: [])")
    p_cfg_audit_filters.add_argument("--export", dest="export_path", required=True, help="Gmail exported filters YAML (from 'filters export')")
    p_cfg_audit_filters.add_argument("--preview-missing", action="store_true", help="List a few missing simple rules")
    p_cfg_audit_filters.set_defaults(func=_cmd_config_audit_filters)

    # workflows group (agentic, procedural sequences)
    p_wf = sub.add_parser("workflows", help="Agentic workflows that chain plan/apply steps")
    sub_wf = p_wf.add_subparsers(dest="workflows_cmd")
    p_wf_g = sub_wf.add_parser(
        "gmail-from-unified",
        help="Derive Gmail filters from unified YAML, plan changes, and optionally apply",
    )
    p_wf_g.add_argument("--config", required=True, help="Unified filters YAML (filters: [])")
    p_wf_g.add_argument("--out-dir", default="out", help="Directory for derived/plan artifacts (default: out)")
    p_wf_g.add_argument("--delete-missing", action="store_true", help="Include deletions when applying")
    p_wf_g.add_argument("--apply", action="store_true", help="Apply changes after planning")
    p_wf_g.set_defaults(func=_cmd_workflows_gmail_from_unified)

    p_wf_all = sub_wf.add_parser(
        "from-unified",
        help="Derive provider configs from unified, plan per provider, optionally apply",
    )
    p_wf_all.add_argument("--config", required=True, help="Unified filters YAML (filters: [])")
    p_wf_all.add_argument("--out-dir", default="out", help="Directory for derived/plan artifacts (default: out)")
    p_wf_all.add_argument(
        "--providers",
        help="Comma-separated providers to include (gmail,outlook). Default: auto-detect configured",
    )
    p_wf_all.add_argument("--delete-missing", action="store_true", help="Include deletions when applying")
    p_wf_all.add_argument("--apply", action="store_true", help="Apply changes after planning")
    # Outlook options for discovery/fallbacks
    p_wf_all.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for Outlook defaults")
    p_wf_all.add_argument("--account", help="Account name in accounts config to use for Outlook")
    p_wf_all.add_argument("--outlook-move-to-folders", action="store_true", dest="outlook_move_to_folders", help="Encode moveToFolder from first added label for Outlook (default on)")
    p_wf_all.add_argument("--no-outlook-move-to-folders", action="store_false", dest="outlook_move_to_folders", help="Do not encode moveToFolder; categories-only on Outlook")
    p_wf_all.set_defaults(outlook_move_to_folders=True)
    p_wf_all.set_defaults(func=_cmd_workflows_from_unified)

    # env group (environment setup automation)
    p_env = sub.add_parser("env", help="Environment setup and verification")
    sub_env = p_env.add_subparsers(dest="env_cmd")
    p_env_setup = sub_env.add_parser("setup", help="Prepare venv and persisted credentials (INI)")
    p_env_setup.add_argument("--venv-dir", default=".venv", help="Virtualenv directory (default .venv)")
    p_env_setup.add_argument("--no-venv", action="store_true", help="Skip creating/updating virtualenv")
    p_env_setup.add_argument("--skip-install", action="store_true", help="Skip pip install -e . inside venv")
    # Gmail paths
    p_env_setup.add_argument("--credentials", help=f"Path to Gmail credentials.json to persist in INI (default: {default_gmail_credentials})")
    p_env_setup.add_argument("--token", help=f"Path to Gmail token.json to persist in INI (default: {default_gmail_token})")
    # Outlook settings
    p_env_setup.add_argument("--outlook-client-id", help="Azure app (client) ID to persist in INI")
    p_env_setup.add_argument("--tenant", help="AAD tenant to persist in INI (e.g., consumers)")
    p_env_setup.add_argument("--outlook-token", help="Path to Outlook token cache JSON to persist in INI")
    # Convenience: copy Gmail example to the default external credentials path if missing
    p_env_setup.add_argument(
        "--copy-gmail-example",
        dest="copy_gmail_example",
        action="store_true",
        help=f"Copy credentials.example.json to {default_gmail_credentials} if missing",
    )
    p_env_setup.add_argument("--no-copy-gmail-example", dest="copy_gmail_example", action="store_false")
    p_env_setup.set_defaults(copy_gmail_example=True)
    p_env_setup.set_defaults(func=_cmd_env_setup)

    # accounts group (1-to-many operations across providers)
    p_accts = sub.add_parser("accounts", help="Operate across multiple email accounts/providers")
    sub_accts = p_accts.add_subparsers(dest="accounts_cmd")

    for help_name, func, extra_args in [
        ("list", _cmd_accounts_list, []),
        ("export-labels", _cmd_accounts_export_labels, [("--out-dir", {"required": True})]),
        ("sync-labels", _cmd_accounts_sync_labels, [("--labels", {"required": True})]),
        ("export-filters", _cmd_accounts_export_filters, [("--out-dir", {"required": True})]),
        ("sync-filters", _cmd_accounts_sync_filters, [("--filters", {"required": True}), ("--require-forward-verified", {"action": "store_true"})]),
        ("plan-labels", _cmd_accounts_plan_labels, [("--labels", {"required": True})]),
        ("plan-filters", _cmd_accounts_plan_filters, [("--filters", {"required": True})]),
        ("export-signatures", _cmd_accounts_export_signatures, [("--out-dir", {"required": True})]),
        ("sync-signatures", _cmd_accounts_sync_signatures, [("--send-as", {})]),
    ]:
        sp = sub_accts.add_parser(help_name, help=f"{help_name.replace('-', ' ').title()} across selected accounts")
        sp.add_argument("--config", required=True, help="Accounts YAML with provider/credentials")
        sp.add_argument("--accounts", help="Comma-separated list of account names to include; default all")
        sp.add_argument("--dry-run", action="store_true")
        for arg_name, kwargs in extra_args:
            sp.add_argument(arg_name, **kwargs)
        sp.set_defaults(func=func)

    # outlook group (single-account helpers)
    p_outlook = sub.add_parser("outlook", help="Outlook-specific operations")
    sub_outlook = p_outlook.add_subparsers(dest="outlook_cmd")

    # outlook auth helpers (device-code flow)
    p_outlook_auth = sub_outlook.add_parser("auth", help="Outlook authentication helpers")
    sub_outlook_auth = p_outlook_auth.add_subparsers(dest="outlook_auth_cmd")
    p_outlook_auth_dev = sub_outlook_auth.add_parser(
        "device-code",
        help="Initiate device-code login and print URL + user code (non-blocking)",
    )
    p_outlook_auth_dev.add_argument("--client-id", help="Azure app (client) ID")
    p_outlook_auth_dev.add_argument("--tenant", default="consumers", help="AAD tenant (default: consumers)")
    p_outlook_auth_dev.add_argument(
        "--out",
        default=default_outlook_flow,
        help=f"Path to store the device-flow JSON (default: {default_outlook_flow})",
    )
    p_outlook_auth_dev.set_defaults(func=run_outlook_auth_device_code)

    p_outlook_auth_poll = sub_outlook_auth.add_parser(
        "poll",
        help="Poll a saved device-code flow and write token cache to --token",
    )
    p_outlook_auth_poll.add_argument(
        "--flow",
        default=default_outlook_flow,
        help=f"Path to device-flow JSON (default: {default_outlook_flow})",
    )
    p_outlook_auth_poll.add_argument(
        "--token",
        default=default_outlook_token,
        help=f"Path to token cache JSON output (default: {default_outlook_token})",
    )
    p_outlook_auth_poll.set_defaults(func=run_outlook_auth_poll)

    p_outlook_auth_ensure = sub_outlook_auth.add_parser(
        "ensure",
        help="Ensure a valid Outlook token cache exists (silent refresh or device-code flow if needed)",
    )
    p_outlook_auth_ensure.add_argument("--client-id", help="Azure app (client) ID")
    p_outlook_auth_ensure.add_argument("--tenant", default="consumers", help="AAD tenant (default: consumers)")
    p_outlook_auth_ensure.add_argument("--token", help="Path to token cache JSON (defaults from profile)")
    p_outlook_auth_ensure.set_defaults(func=run_outlook_auth_ensure)

    p_outlook_auth_validate = sub_outlook_auth.add_parser(
        "validate",
        help="Validate Outlook token cache non-interactively (no browser)",
    )
    p_outlook_auth_validate.add_argument("--client-id", help="Azure app (client) ID")
    p_outlook_auth_validate.add_argument("--tenant", default="consumers", help="AAD tenant (default: consumers)")
    p_outlook_auth_validate.add_argument("--token", help="Path to token cache JSON (defaults from profile)")
    p_outlook_auth_validate.set_defaults(func=run_outlook_auth_validate)

    # outlook rules sync: create Outlook inbox rules from YAML DSL
    p_outlook_rules_sync = sub_outlook.add_parser("rules", help="Outlook rules operations")
    sub_outlook_rules = p_outlook_rules_sync.add_subparsers(dest="outlook_rules_cmd")
    p_outlook_rules_list_cmd = sub_outlook_rules.add_parser("list", help="List Outlook Inbox rules")
    from .cli.args import add_outlook_common_args as _add_outlook_args
    _add_outlook_args(p_outlook_rules_list_cmd)
    p_outlook_rules_list_cmd.add_argument("--use-cache", action="store_true", help="Use cached rules if available")
    p_outlook_rules_list_cmd.add_argument("--cache-ttl", type=int, default=600, help="Cache TTL seconds (default 600)")
    p_outlook_rules_list_cmd.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_outlook_rules_list_cmd.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_outlook_rules_list_cmd.set_defaults(func=run_outlook_rules_list)
    p_outlook_rules_export_cmd = sub_outlook_rules.add_parser("export", help="Export Outlook rules to filters YAML")
    _add_outlook_args(p_outlook_rules_export_cmd)
    p_outlook_rules_export_cmd.add_argument("--out", required=True, help="Output YAML path")
    p_outlook_rules_export_cmd.add_argument("--use-cache", action="store_true")
    p_outlook_rules_export_cmd.add_argument("--cache-ttl", type=int, default=600)
    p_outlook_rules_export_cmd.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_outlook_rules_export_cmd.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_outlook_rules_export_cmd.set_defaults(func=run_outlook_rules_export)
    p_outlook_rules_plan_cmd = sub_outlook_rules.add_parser("plan", help="Plan Outlook rule changes from filters YAML")
    _add_outlook_args(p_outlook_rules_plan_cmd)
    p_outlook_rules_plan_cmd.add_argument("--config", required=True, help="Filters YAML (same DSL as Gmail export)")
    p_outlook_rules_plan_cmd.add_argument("--use-cache", action="store_true")
    p_outlook_rules_plan_cmd.add_argument("--cache-ttl", type=int, default=600)
    p_outlook_rules_plan_cmd.set_defaults(move_to_folders=True)
    p_outlook_rules_plan_cmd.add_argument("--move-to-folders", action="store_true", dest="move_to_folders", help="Plan using move-to-folder actions from first added label (default on)")
    p_outlook_rules_plan_cmd.add_argument("--categories-only", action="store_false", dest="move_to_folders", help="Plan without folder moves; categories only")
    p_outlook_rules_plan_cmd.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_outlook_rules_plan_cmd.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_outlook_rules_plan_cmd.set_defaults(func=run_outlook_rules_plan)
    p_outlook_rules_delete_cmd = sub_outlook_rules.add_parser("delete", help="Delete an Outlook rule by ID")
    _add_outlook_args(p_outlook_rules_delete_cmd)
    p_outlook_rules_delete_cmd.add_argument("--id", required=True, help="Rule ID to delete")
    p_outlook_rules_delete_cmd.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_outlook_rules_delete_cmd.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_outlook_rules_delete_cmd.set_defaults(func=run_outlook_rules_delete)

    # outlook calendar helpers
    p_outlook_calendar = sub_outlook.add_parser("calendar", help="Outlook calendar operations")
    sub_outlook_cal = p_outlook_calendar.add_subparsers(dest="outlook_calendar_cmd")

    # Add one-time event
    p_cal_add = sub_outlook_cal.add_parser("add", help="Add a one-time event to a calendar")
    p_cal_add.add_argument("--client-id", help="Azure app (client) ID; defaults from profile or env")
    p_cal_add.add_argument("--tenant", default="consumers", help="AAD tenant (default: consumers)")
    p_cal_add.add_argument("--token", help="Path to token cache JSON (optional)")
    p_cal_add.add_argument("--calendar", help="Calendar name (e.g., Family). Defaults to primary if omitted")
    p_cal_add.add_argument("--subject", required=True, help="Event subject/title")
    p_cal_add.add_argument("--start", required=True, help="Start datetime ISO (YYYY-MM-DDTHH:MM[:SS])")
    p_cal_add.add_argument("--end", required=True, help="End datetime ISO (YYYY-MM-DDTHH:MM[:SS])")
    p_cal_add.add_argument("--tz", help="Time zone (IANA or Windows). Defaults to mailbox setting or UTC")
    p_cal_add.add_argument("--location", help="Location display name")
    p_cal_add.add_argument("--body-html", dest="body_html", help="HTML body content")
    p_cal_add.add_argument("--all-day", action="store_true", help="Mark as all-day (expects date-only start/end)")
    p_cal_add.add_argument("--no-reminder", action="store_true", help="Create event without reminders/alerts")
    p_cal_add.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_cal_add.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_cal_add.set_defaults(func=run_outlook_calendar_add)

    # Add recurring event
    p_cal_add_rec = sub_outlook_cal.add_parser("add-recurring", help="Add a recurring event with optional exclusions")
    p_cal_add_rec.add_argument("--client-id", help="Azure app (client) ID; defaults from profile or env")
    p_cal_add_rec.add_argument("--tenant", default="consumers", help="AAD tenant (default: consumers)")
    p_cal_add_rec.add_argument("--token", help="Path to token cache JSON (optional)")
    p_cal_add_rec.add_argument("--calendar", help="Calendar name (e.g., Family). Defaults to primary if omitted")
    p_cal_add_rec.add_argument("--subject", required=True)
    p_cal_add_rec.add_argument("--repeat", required=True, choices=["daily", "weekly", "monthly"], help="Recurrence type")
    p_cal_add_rec.add_argument("--interval", type=int, default=1, help="Recurrence interval (default 1)")
    p_cal_add_rec.add_argument("--byday", help="Days for weekly, comma-separated (e.g., MO,WE,FR)")
    p_cal_add_rec.add_argument("--range-start", required=True, dest="range_start", help="Start date YYYY-MM-DD for the series")
    p_cal_add_rec.add_argument("--until", help="End date YYYY-MM-DD for the series")
    p_cal_add_rec.add_argument("--count", type=int, help="Occurrences count (alternative to --until)")
    p_cal_add_rec.add_argument("--start-time", required=True, help="Start time HH:MM[:SS]")
    p_cal_add_rec.add_argument("--end-time", required=True, help="End time HH:MM[:SS]")
    p_cal_add_rec.add_argument("--tz", help="Time zone (IANA or Windows). Defaults to mailbox setting or UTC")
    p_cal_add_rec.add_argument("--location", help="Location display name")
    p_cal_add_rec.add_argument("--body-html", dest="body_html", help="HTML body content")
    p_cal_add_rec.add_argument("--exdates", help="Comma-separated YYYY-MM-DD dates to exclude")
    p_cal_add_rec.add_argument("--no-reminder", action="store_true", help="Create series without reminders/alerts")
    p_cal_add_rec.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_cal_add_rec.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_cal_add_rec.set_defaults(func=run_outlook_calendar_add_recurring)

    # Add from config (YAML DSL)
    p_cal_from_cfg = sub_outlook_cal.add_parser("add-from-config", help="Add events defined in a YAML file")
    p_cal_from_cfg.add_argument("--client-id", help="Azure app (client) ID; defaults from profile or env")
    p_cal_from_cfg.add_argument("--tenant", default="consumers", help="AAD tenant (default: consumers)")
    p_cal_from_cfg.add_argument("--token", help="Path to token cache JSON (optional)")
    p_cal_from_cfg.add_argument("--config", required=True, help="YAML with events: [] entries")
    p_cal_from_cfg.add_argument("--no-reminder", action="store_true", help="Create events without reminders/alerts")
    p_cal_from_cfg.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_cal_from_cfg.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_cal_from_cfg.set_defaults(func=run_outlook_calendar_add_from_config)
    p_outlook_rules_sweep_cmd = sub_outlook_rules.add_parser("sweep", help="Apply folder moves to existing messages based on filters YAML")
    p_outlook_rules_sweep_cmd.add_argument("--client-id", help="Azure app (client) ID for device auth; defaults from env or accounts config")
    p_outlook_rules_sweep_cmd.add_argument("--tenant", default="consumers", help="AAD tenant (default: consumers)")
    p_outlook_rules_sweep_cmd.add_argument("--token", help="Path to token cache JSON (optional)")
    p_outlook_rules_sweep_cmd.add_argument("--config", required=True, help="Filters YAML (unified DSL)")
    p_outlook_rules_sweep_cmd.add_argument("--days", type=int, default=30, help="Only sweep messages received in last N days (default 30)")
    p_outlook_rules_sweep_cmd.add_argument("--pages", type=int, default=2, help="Pages to search per rule (default 2)")
    p_outlook_rules_sweep_cmd.add_argument("--top", type=int, default=25, help="Page size (default 25)")
    p_outlook_rules_sweep_cmd.set_defaults(move_to_folders=True)
    p_outlook_rules_sweep_cmd.add_argument("--move-to-folders", action="store_true", dest="move_to_folders", help="Derive folder from first added label when moveToFolder missing (default on)")
    p_outlook_rules_sweep_cmd.add_argument("--categories-only", action="store_false", dest="move_to_folders", help="Do not move; no folder derivation")
    p_outlook_rules_sweep_cmd.add_argument("--dry-run", action="store_true")
    p_outlook_rules_sweep_cmd.add_argument("--clear-cache", action="store_true", help="Clear Outlook sweep caches before running")
    p_outlook_rules_sweep_cmd.add_argument("--use-cache", action="store_true", help="Use cached folder/search data (default if cache exists)")
    p_outlook_rules_sweep_cmd.add_argument("--cache-ttl", type=int, default=600, help="Cache TTL seconds for folder/search caches")
    p_outlook_rules_sweep_cmd.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_outlook_rules_sweep_cmd.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_outlook_rules_sweep_cmd.set_defaults(func=run_outlook_rules_sweep)
    p_outlook_rules_sync_cmd = sub_outlook_rules.add_parser("sync", help="Sync rules from filters YAML into Outlook Inbox")
    p_outlook_rules_sync_cmd.add_argument("--client-id", help="Azure app (client) ID for device auth; defaults from env or accounts config")
    p_outlook_rules_sync_cmd.add_argument("--tenant", default="consumers", help="AAD tenant (default: consumers)")
    p_outlook_rules_sync_cmd.add_argument("--token", help="Path to token cache JSON (optional)")
    p_outlook_rules_sync_cmd.add_argument("--config", required=True, help="Filters YAML (same DSL as Gmail export)")
    p_outlook_rules_sync_cmd.add_argument("--dry-run", action="store_true", help="Print actions without creating rules")
    p_outlook_rules_sync_cmd.set_defaults(move_to_folders=True)
    p_outlook_rules_sync_cmd.add_argument("--move-to-folders", action="store_true", dest="move_to_folders", help="Move to folders matching added labels (default on)")
    p_outlook_rules_sync_cmd.add_argument("--categories-only", action="store_false", dest="move_to_folders", help="Assign categories only (no folder moves)")
    p_outlook_rules_sync_cmd.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_outlook_rules_sync_cmd.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_outlook_rules_sync_cmd.add_argument("--delete-missing", action="store_true", help="Delete Outlook rules not present in YAML")
    p_outlook_rules_sync_cmd.set_defaults(func=run_outlook_rules_sync)

    # outlook categories sync: create/update Outlook categories from labels YAML
    p_outlook_categories = sub_outlook.add_parser("categories", help="Outlook categories operations")
    sub_outlook_categories = p_outlook_categories.add_subparsers(dest="outlook_categories_cmd")
    p_outlook_categories_list = sub_outlook_categories.add_parser("list", help="List Outlook categories")
    _add_outlook_args(p_outlook_categories_list)
    p_outlook_categories_list.add_argument("--use-cache", action="store_true")
    p_outlook_categories_list.add_argument("--cache-ttl", type=int, default=600)
    p_outlook_categories_list.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_outlook_categories_list.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_outlook_categories_list.set_defaults(func=run_outlook_categories_list)
    p_outlook_categories_export = sub_outlook_categories.add_parser("export", help="Export categories to YAML (labels list)")
    _add_outlook_args(p_outlook_categories_export)
    p_outlook_categories_export.add_argument("--out", required=True, help="Output YAML path")
    p_outlook_categories_export.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_outlook_categories_export.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_outlook_categories_export.add_argument("--use-cache", action="store_true")
    p_outlook_categories_export.add_argument("--cache-ttl", type=int, default=600)
    p_outlook_categories_export.set_defaults(func=run_outlook_categories_export)
    p_outlook_categories_sync = sub_outlook_categories.add_parser("sync", help="Sync categories from labels YAML")
    _add_outlook_args(p_outlook_categories_sync)
    p_outlook_categories_sync.add_argument("--config", required=True, help="Labels YAML (same DSL as Gmail export)")
    p_outlook_categories_sync.add_argument("--dry-run", action="store_true")
    p_outlook_categories_sync.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_outlook_categories_sync.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_outlook_categories_sync.set_defaults(func=run_outlook_categories_sync)

    # outlook folders sync: create Outlook folders from Gmail-style label paths
    p_outlook_folders = sub_outlook.add_parser("folders", help="Outlook folders operations")
    sub_outlook_folders = p_outlook_folders.add_subparsers(dest="outlook_folders_cmd")
    p_outlook_folders_sync = sub_outlook_folders.add_parser("sync", help="Create Outlook folders from labels YAML (nested by '/')")
    _add_outlook_args(p_outlook_folders_sync)
    p_outlook_folders_sync.add_argument("--config", required=True, help="Labels YAML (e.g., from Gmail export)")
    p_outlook_folders_sync.add_argument("--dry-run", action="store_true")
    p_outlook_folders_sync.add_argument("--accounts-config", default="config/accounts.yaml", help="Accounts YAML for defaults")
    p_outlook_folders_sync.add_argument("--account", help="Account name in accounts config to use for defaults")
    p_outlook_folders_sync.set_defaults(func=run_outlook_folders_sync)

    return parser


def load_config(path: Optional[str]) -> dict:
    """Load YAML config if available. Returns {} on any error."""
    if not path:
        return {}
    try:
        from .yamlio import load_config as _load
        return _load(path)
    except Exception:
        return {}


def _lazy_gmail_client():
    """Import and construct GmailClient lazily to avoid import errors on help."""
    try:
        from .gmail_api import GmailClient  # local import
    except Exception as e:
        raise SystemExit(f"Gmail features unavailable: {e}")
    return GmailClient


def _load_accounts(path: str) -> list[dict]:
    cfg = load_config(path)
    accts = cfg.get("accounts") or []
    return [a for a in accts if isinstance(a, dict)]


def _iter_accounts(accts: list[dict], names: Optional[str]) -> Iterable[dict]:
    allow = None
    if names:
        allow = {n.strip() for n in names.split(',') if n.strip()}
    for a in accts:
        if allow and a.get("name") not in allow:
            continue
        yield a


def _build_client_for_account(acc: dict):
    provider = str(acc.get("provider") or "").lower()
    if provider == "gmail":
        GmailClient = _lazy_gmail_client()
        creds = expand_path(acc.get("credentials") or default_gmail_credentials_path())
        token = expand_path(acc.get("token") or default_gmail_token_path())
        return GmailClient(
            credentials_path=creds,
            token_path=token,
            cache_dir=acc.get("cache"),
        )
    if provider == "outlook":
        try:
            from .outlook_api import OutlookClient  # type: ignore
        except Exception as e:
            raise SystemExit(f"Outlook provider unavailable: {e}")
        client_id = acc.get("client_id") or acc.get("application_id") or acc.get("credentials")
        if not client_id:
            raise SystemExit(f"Outlook account {acc.get('name')} missing client_id")
        tenant = acc.get("tenant") or "consumers"
        token_path = expand_path(acc.get("token"))
        return OutlookClient(client_id=client_id, tenant=tenant, token_path=token_path, cache_dir=acc.get("cache"))
    raise SystemExit(f"Unsupported provider: {provider or '<missing>'} for account {acc.get('name')}")


def _build_provider_for_account(acc: dict):
    """Return a provider-like object for an account.

    For Gmail, returns a GmailProvider adapter. For Outlook, returns the
    existing OutlookClient which already exposes a compatible surface for
    labels/filters used by accounts commands.
    """
    provider = str(acc.get("provider") or "").lower()
    if provider == "gmail":
        from .providers.gmail import GmailProvider
        creds = expand_path(acc.get("credentials") or default_gmail_credentials_path())
        token = expand_path(acc.get("token") or default_gmail_token_path())
        return GmailProvider(
            credentials_path=creds,
            token_path=token,
            cache_dir=acc.get("cache"),
        )
    if provider == "outlook":
        try:
            from .providers.outlook import OutlookProvider  # type: ignore
        except Exception as e:
            raise SystemExit(f"Outlook provider unavailable: {e}")
        client_id = acc.get("client_id") or acc.get("application_id") or acc.get("credentials")
        if not client_id:
            raise SystemExit(f"Outlook account {acc.get('name')} missing client_id")
        tenant = acc.get("tenant") or "consumers"
        token_path = expand_path(acc.get("token"))
        return OutlookProvider(client_id=client_id, tenant=tenant, token_path=token_path, cache_dir=acc.get("cache"))
    raise SystemExit(f"Unsupported provider: {provider or '<missing>'} for account {acc.get('name')}")


def _cmd_auth(args: argparse.Namespace) -> int:
    from .config_resolver import persist_if_provided
    # Resolve from args or ini
    from .config_resolver import resolve_paths_profile
    creds_path, token_path = resolve_paths_profile(
        arg_credentials=getattr(args, "credentials", None),
        arg_token=getattr(args, "token", None),
        profile=getattr(args, 'profile', None),
    )

    if getattr(args, 'validate', False):
        # Non-interactive token validation for Gmail
        try:
            from google.auth.transport.requests import Request  # type: ignore
            from google.oauth2.credentials import Credentials  # type: ignore
            from googleapiclient.discovery import build  # type: ignore
            from .gmail_api import SCOPES as GMAIL_SCOPES  # type: ignore
        except Exception as e:
            print(f"Gmail validation unavailable (missing deps): {e}")
            return 1
        import os
        if not token_path or not os.path.exists(token_path):
            print(f"Token file not found: {token_path or '<unspecified>'}")
            return 2
        try:
            creds = Credentials.from_authorized_user_file(token_path, scopes=GMAIL_SCOPES)
            if creds and creds.expired and getattr(creds, 'refresh_token', None):
                creds.refresh(Request())
            svc = build("gmail", "v1", credentials=creds)
            _ = svc.users().getProfile(userId="me").execute()
            print("Gmail token valid.")
            return 0
        except Exception as e:
            print(f"Gmail token invalid: {e}")
            return 3

    GmailClient = _lazy_gmail_client()
    client = GmailClient(credentials_path=creds_path, token_path=token_path)
    client.authenticate()
    # Persist explicit inputs into ini for future runs
    persist_if_provided(arg_credentials=getattr(args, "credentials", None), arg_token=getattr(args, "token", None))
    print("Authentication complete.")
    return 0


@_with_gmail_client
def _cmd_labels_list(args: argparse.Namespace) -> int:
    from .utils.cli_helpers import gmail_client_authenticated
    client = getattr(args, "_gmail_client", None) or gmail_client_authenticated(args)
    labels = client.list_labels()
    for lab in labels:
        name = lab.get("name", "<unknown>")
        lab_id = lab.get("id", "")
        print(f"{lab_id}\t{name}")
    return 0


def _cmd_labels_sync(args: argparse.Namespace) -> int:
    from .labels.commands import run_labels_sync

    return run_labels_sync(args)


def _cmd_labels_export(args: argparse.Namespace) -> int:
    from .labels.commands import run_labels_export

    return run_labels_export(args)


def _cmd_labels_plan(args: argparse.Namespace) -> int:
    from .labels.commands import run_labels_plan

    return run_labels_plan(args)


def _analyze_labels(labels: list[dict]) -> dict:
    names = [l.get("name", "") for l in labels if isinstance(l, dict)]
    from collections import Counter
    counts = Counter(names)
    dups = [n for n, c in counts.items() if c > 1]
    parts = [n.split('/') for n in names]
    max_depth = max((len(ps) for ps in parts), default=0)
    top_counts = Counter(ps[0] for ps in parts if ps)
    vis_l = Counter((l.get('labelListVisibility') or 'unset') for l in labels if isinstance(l, dict))
    vis_m = Counter((l.get('messageListVisibility') or 'unset') for l in labels if isinstance(l, dict))
    imapish = [n for n in names if n.startswith('[Gmail]') or n.lower().startswith('imap/')]
    unset_vis = [l.get('name') for l in labels if not l.get('labelListVisibility') or not l.get('messageListVisibility')]
    return {
        'total': len(names),
        'duplicates': dups,
        'max_depth': max_depth,
        'top_counts': dict(top_counts.most_common(10)),
        'vis_label': dict(vis_l),
        'vis_message': dict(vis_m),
        'imapish': imapish,
        'unset_visibility': unset_vis,
    }

from .dsl import (
    normalize_labels_for_outlook as _normalize_labels_for_outlook,
    normalize_filters_for_outlook as _normalize_filters_for_outlook,
    normalize_filter_for_outlook as _normalize_filter_for_outlook,
)


# Normalization helpers moved to mail_assistant.dsl (imported above)


def _cmd_labels_doctor(args: argparse.Namespace) -> int:
    from .utils.cli_helpers import gmail_provider_from_args
    client = gmail_provider_from_args(args)
    client.authenticate()
    labs = client.list_labels(use_cache=getattr(args, 'use_cache', False), ttl=getattr(args, 'cache_ttl', 300))
    info = _analyze_labels(labs)
    print(f"Total labels: {info['total']}")
    print(f"Duplicates: {len(info['duplicates'])}{(' ; ' + ','.join(info['duplicates'])) if info['duplicates'] else ''}")
    print(f"Max depth: {info['max_depth']}")
    print(f"Top-level groups: {info['top_counts']}")
    print(f"Visibility labelListVisibility: {info['vis_label']}")
    print(f"Visibility messageListVisibility: {info['vis_message']}")
    print(f"IMAP-style labels: {len(info['imapish'])}{(' ; ' + ','.join(info['imapish'])) if info['imapish'] else ''}")
    print(f"Unset visibility count: {len(info['unset_visibility'])}")

    # Enforce defaults if requested
    changed = 0
    if args.set_visibility:
        for l in labs:
            if l.get('type') == 'system':
                continue
            name = l.get('name')
            body = {"name": name}
            need = False
            if not l.get('labelListVisibility'):
                body['labelListVisibility'] = 'labelShow'
                need = True
            if not l.get('messageListVisibility'):
                body['messageListVisibility'] = 'show'
                need = True
            if need:
                client.update_label(l.get('id', ''), body)
                print(f"Updated visibility: {name}")
                changed += 1

    # Redirects passed as old=new
    if args.imap_redirect:
        map_pairs = []
        for spec in args.imap_redirect:
            if '=' in spec:
                old, new = spec.split('=', 1)
                map_pairs.append((old.strip(), new.strip()))
        if map_pairs:
            name_to_id = client.get_label_id_map()
            for old, new in map_pairs:
                old_id = name_to_id.get(old)
                new_id = name_to_id.get(new) or client.ensure_label(new)
                if not old_id or not new_id:
                    print(f"Skip redirect: {old}->{new} (missing label)")
                    continue
                ids = client.list_message_ids(label_ids=[old_id], max_pages=50, page_size=500)
                from .utils.batch import apply_in_chunks
                apply_in_chunks(
                    lambda chunk: client.batch_modify_messages(
                        chunk, add_label_ids=[new_id], remove_label_ids=[old_id]
                    ),
                    ids,
                    500,
                )
                print(f"Redirected {len(ids)} messages {old} -> {new}")
                changed += 1

    # Deletes
    if args.imap_delete:
        name_to_id = client.get_label_id_map()
        for name in args.imap_delete:
            lid = name_to_id.get(name)
            if lid:
                client.delete_label(lid)
                print(f"Deleted label: {name}")
                changed += 1

    if changed:
        print(f"Applied {changed} change(s).")
    return 0


def _cmd_labels_prune_empty(args: argparse.Namespace) -> int:
    from .utils.cli_helpers import gmail_provider_from_args
    import time
    client = gmail_provider_from_args(args)
    client.authenticate()
    labels = client.list_labels()
    deleted = 0
    def _delete_with_retry(label_id: str, name: str) -> bool:
        last_err = None
        for i in range(3):
            try:
                client.delete_label(label_id)
                print(f"Deleted label: {name}")
                return True
            except Exception as e:
                last_err = e
                time.sleep(1.5 * (2 ** i))
        print(f"Warning: failed to delete label {name}: {last_err}")
        return False
    processed = 0
    limit = int(getattr(args, 'limit', 0) or 0)
    sleep_s = float(getattr(args, 'sleep_sec', 0.0) or 0.0)
    for lab in labels:
        if lab.get("type") != "user":
            continue
        if int(lab.get("messagesTotal", 0)) == 0:
            name = lab.get("name")
            if args.dry_run:
                print(f"Would delete label: {name}")
            else:
                if _delete_with_retry(lab.get("id", ""), name or ""):
                    deleted += 1
                    processed += 1
                    if sleep_s > 0:
                        time.sleep(sleep_s)
                    if limit and processed >= limit:
                        break
            if args.dry_run and limit:
                processed += 1
                if processed >= limit:
                    break
    print(f"Prune complete. Deleted: {deleted}")
    return 0


def _cmd_labels_learn(args: argparse.Namespace) -> int:
    GmailClient = _lazy_gmail_client()
    creds_path, tok_path = resolve_paths_profile(
        arg_credentials=args.credentials,
        arg_token=args.token,
        profile=getattr(args, "profile", None),
    )
    client = GmailClient(
        credentials_path=creds_path,
        token_path=tok_path,
        cache_dir=args.cache,
    )
    client.authenticate()
    q = _build_gmail_query({}, days=args.days, only_inbox=args.only_inbox)
    ids = client.list_message_ids(query=q, max_pages=100)
    msgs = client.get_messages_metadata(ids, use_cache=True)
    # Protected list
    prot = [p.strip().lower() for p in (args.protect or []) if p and isinstance(p, str)]
    def is_protected(from_val: str) -> bool:
        f = (from_val or '').lower()
        if '<' in f and '>' in f:
            try:
                f = f.split('<')[-1].split('>')[0]
            except Exception:
                pass
        f = f.strip()
        dom = f.split('@')[-1] if '@' in f else f
        for p in prot:
            if not p:
                continue
            if p.startswith('@'):
                if f.endswith(p) or dom == p.lstrip('@'):
                    return True
            elif p in (f,):
                return True
        return False

    from collections import Counter, defaultdict
    domain_counts = Counter()
    domain_hints = defaultdict(lambda: {"list": 0, "promotions": 0})
    for m in msgs:
        hdrs = client.headers_to_dict(m)
        frm = hdrs.get('from','')
        if is_protected(frm):
            continue
        # derive domain
        f = frm
        if '<' in f and '>' in f:
            try:
                f = f.split('<')[-1].split('>')[0]
            except Exception:
                pass
        dom = f.split('@')[-1].lower().strip() if '@' in f else f.lower().strip()
        if not dom:
            continue
        domain_counts[dom] += 1
        # hints
        if 'list-unsubscribe' in hdrs or 'list-id' in hdrs:
            domain_hints[dom]['list'] += 1
        labs = set(m.get('labelIds') or [])
        if 'CATEGORY_PROMOTIONS' in labs:
            domain_hints[dom]['promotions'] += 1

    suggestions = []
    for dom, cnt in domain_counts.items():
        if cnt < int(args.min_count):
            continue
        hints = domain_hints[dom]
        label = None
        if hints['promotions'] >= max(1, cnt // 3):
            label = 'Lists/Commercial'
        elif hints['list'] >= max(1, cnt // 3):
            label = 'Lists/Newsletters'
        if not label:
            continue
        suggestions.append({
            'domain': dom,
            'label': label,
            'count': cnt,
            'hints': hints,
        })

    out_doc = { 'suggestions': suggestions, 'params': {'days': int(args.days), 'min_count': int(args.min_count)} }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(__import__('yaml').safe_dump(out_doc, sort_keys=False), encoding='utf-8')
    print(f"Wrote {len(suggestions)} suggestions to {out}")
    return 0


def _cmd_labels_apply_suggestions(args: argparse.Namespace) -> int:
    doc = load_config(args.config)
    sugg = doc.get('suggestions') or []
    if not sugg:
        print('No suggestions found.')
        return 0
    GmailClient = _lazy_gmail_client()
    creds_path, tok_path = resolve_paths_profile(
        arg_credentials=args.credentials,
        arg_token=args.token,
        profile=getattr(args, "profile", None),
    )
    client = GmailClient(
        credentials_path=creds_path,
        token_path=tok_path,
        cache_dir=args.cache,
    )
    client.authenticate()
    created = 0
    for s in sugg:
        dom = s.get('domain')
        label = s.get('label')
        if not dom or not label:
            continue
        crit = {'query': f'from:({dom})'}
        # Map suggested label to provider label IDs via shared helper
        add_ids, _ = _action_to_label_changes(client, {'add': [label]})
        act = {'addLabelIds': add_ids}
        if args.dry_run:
            print(f"Would create: from:({dom}) -> add=[{label}]")
        else:
            client.create_filter(crit, act)
            print(f"Created rule: from:({dom}) -> add=[{label}]")
        created += 1
    # Optional sweep
    if args.sweep_days:
        args2 = argparse.Namespace(
            credentials=args.credentials, token=args.token, cache=args.cache,
            config=args.config, days=int(args.sweep_days), only_inbox=False,
            pages=args.pages, batch_size=args.batch_size, max_msgs=None, dry_run=args.dry_run,
        )
        print(f"\nSweeping back {args.sweep_days} days for suggestions …")
        _cmd_filters_sweep(args2)
    print(f"Suggestions applied: {created}")
    return 0


def _cmd_labels_delete(args: argparse.Namespace) -> int:
    from .utils.cli_helpers import gmail_provider_from_args
    client = gmail_provider_from_args(args)
    client.authenticate()
    name_to_id = client.get_label_id_map()
    name = args.name
    lid = name_to_id.get(name)
    if not lid:
        print(f"Label not found: {name}")
        return 1
    client.delete_label(lid)
    print(f"Deleted label: {name}")
    return 0


def _cmd_labels_sweep_parents(args: argparse.Namespace) -> int:
    from .utils.cli_helpers import gmail_provider_from_args
    from .utils.batch import apply_in_chunks

    client = gmail_provider_from_args(args)
    client.authenticate()
    name_to_id = client.get_label_id_map()
    parents = [n.strip() for n in (args.names or "").split(",") if n.strip()]
    total_added = 0
    for parent in parents:
        # Ensure parent label exists
        parent_id = name_to_id.get(parent) or client.ensure_label(parent)
        # Collect child label IDs under namespace "Parent/"
        child_ids = [lid for name, lid in name_to_id.items() if name.startswith(parent + "/")]
        if not child_ids:
            print(f"No child labels under {parent}/; skipping")
            continue
        # Gather message IDs that have any of the child labels
        ids = client.list_message_ids(label_ids=child_ids, max_pages=int(args.pages), page_size=int(args.batch_size))
        if args.dry_run:
            print(f"[{parent}] Would add to {len(ids)} messages")
        else:
            apply_in_chunks(
                lambda chunk: client.batch_modify_messages(chunk, add_label_ids=[parent_id]),
                ids,
                int(args.batch_size),
            )
            print(f"[{parent}] Added to {len(ids)} messages")
        total_added += len(ids)
    print(f"Sweep-parents complete. Messages touched: {total_added}")
    return 0


# -------------- Filters helpers and commands --------------

from .utils.filters import (
    filters_normalize as _filters_normalize,
    build_criteria_from_match as _build_criteria_from_match,
    build_gmail_query as _build_gmail_query,
    action_to_label_changes as _action_to_label_changes,
)


@_with_gmail_client
def _cmd_filters_list(args: argparse.Namespace) -> int:
    from .utils.cli_helpers import gmail_client_authenticated
    client = getattr(args, "_gmail_client", None) or gmail_client_authenticated(args)
    # Map label IDs to names for friendly output
    id_to_name = {lab.get("id", ""): lab.get("name", "") for lab in client.list_labels()}
    def ids_to_names(ids):
        return [id_to_name.get(x, x) for x in ids or []]
    for f in client.list_filters():
        fid = f.get("id", "")
        c = f.get("criteria", {})
        a = f.get("action", {})
        forward = a.get("forward")
        add = ids_to_names(a.get("addLabelIds"))
        rem = ids_to_names(a.get("removeLabelIds"))
        print(f"{fid}\tfrom={c.get('from','')} subject={c.get('subject','')} query={c.get('query','')} | add={add} rem={rem} fwd={forward}")
    return 0


def _cmd_filters_prune_empty(args: argparse.Namespace) -> int:
    from .filters.commands import run_filters_prune_empty

    return run_filters_prune_empty(args)


def _cmd_filters_export(args: argparse.Namespace) -> int:
    from .filters.commands import run_filters_export

    return run_filters_export(args)


def _cmd_filters_sync(args: argparse.Namespace) -> int:
    from .filters.commands import run_filters_sync

    return run_filters_sync(args)


def _cmd_filters_plan(args: argparse.Namespace) -> int:
    from .filters.commands import run_filters_plan

    return run_filters_plan(args)


def _cmd_filters_delete(args: argparse.Namespace) -> int:
    from .utils.cli_helpers import gmail_provider_from_args
    client = gmail_provider_from_args(args)
    client.authenticate()
    fid = args.id
    client.delete_filter(fid)
    print(f"Deleted filter id={fid}")
    return 0


def _cmd_filters_add_forward_by_label(args: argparse.Namespace) -> int:
    from .filters.commands import run_filters_add_forward_by_label

    return run_filters_add_forward_by_label(args)


def _cmd_filters_add_from_token(args: argparse.Namespace) -> int:
    from .filters.commands import run_filters_add_from_token

    return run_filters_add_from_token(args)


def _cmd_filters_rm_from_token(args: argparse.Namespace) -> int:
    from .filters.commands import run_filters_rm_from_token

    return run_filters_rm_from_token(args)


def _cmd_filters_impact(args: argparse.Namespace) -> int:
    from .filters.commands import run_filters_impact

    return run_filters_impact(args)


def _cmd_filters_sweep(args: argparse.Namespace) -> int:
    from .filters.commands import run_filters_sweep

    return run_filters_sweep(args)


def _cmd_filters_sweep_range(args: argparse.Namespace) -> int:
    from .filters.commands import run_filters_sweep_range

    return run_filters_sweep_range(args)


def _cmd_backup(args: argparse.Namespace) -> int:
    # Create timestamped directory
    ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else Path("backups") / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    GmailClient = _lazy_gmail_client()
    from .utils.cli_helpers import gmail_provider_from_args
    client = gmail_provider_from_args(args)
    client.authenticate()
    # Labels
    labels = client.list_labels()
    labels_doc = {"labels": [
        {k: v for k, v in l.items() if k in ("name", "color", "labelListVisibility", "messageListVisibility")}
        for l in labels if l.get("type") != "system"
    ], "redirects": []}
    from .yamlio import dump_config
    dump_config(str(out_dir / "labels.yaml"), labels_doc)
    # Filters
    id_to_name = {lab.get("id", ""): lab.get("name", "") for lab in labels}
    def ids_to_names(ids):
        return [id_to_name.get(x) for x in ids or [] if id_to_name.get(x)]
    filters = client.list_filters()
    dsl_filters = []
    for f in filters:
        crit = f.get("criteria", {}) or {}
        act = f.get("action", {}) or {}
        entry = {
            "match": {k: v for k, v in crit.items() if k in ("from","to","subject","query","negatedQuery","hasAttachment","size","sizeComparison") and v not in (None, "")},
            "action": {},
        }
        if act.get("forward"):
            entry["action"]["forward"] = act["forward"]
        if act.get("addLabelIds"):
            entry["action"]["add"] = ids_to_names(act.get("addLabelIds"))
        if act.get("removeLabelIds"):
            entry["action"]["remove"] = ids_to_names(act.get("removeLabelIds"))
        dsl_filters.append(entry)
    dump_config(str(out_dir / "filters.yaml"), {"filters": dsl_filters})
    print(f"Backup written to {out_dir}")
    return 0


def _cmd_cache_stats(args: argparse.Namespace) -> int:
    root = Path(args.cache)
    total = 0
    files = 0
    for p in root.rglob("*"):
        if p.is_file():
            files += 1
            try:
                total += p.stat().st_size
            except Exception:
                pass
    print(f"Cache: {root} files={files} size={total} bytes")
    return 0


def _cmd_cache_clear(args: argparse.Namespace) -> int:
    root = Path(args.cache)
    if not root.exists():
        print("Cache does not exist.")
        return 0
    # Dangerous: remove directory
    import shutil
    shutil.rmtree(root)
    print(f"Cleared cache: {root}")
    return 0


def _cmd_cache_prune(args: argparse.Namespace) -> int:
    root = Path(args.cache)
    if not root.exists():
        print("Cache does not exist.")
        return 0
    import time
    cutoff = time.time() - (int(args.days) * 86400)
    removed = 0
    for p in root.rglob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except Exception:
            pass
    print(f"Pruned {removed} files older than {args.days} days from {root}")
    return 0


# ---------- Accounts (1-to-many) operations ----------

def _cmd_accounts_list(args: argparse.Namespace) -> int:
    accts = _load_accounts(args.config)
    for a in accts:
        print(f"{a.get('name','<noname>')}\tprovider={a.get('provider')}\tcred={a.get('credentials','')}\ttoken={a.get('token','')}")
    return 0


def _cmd_accounts_export_labels(args: argparse.Namespace) -> int:
    accts = _load_accounts(args.config)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for a in _iter_accounts(accts, args.accounts):
        client = _build_provider_for_account(a)
        client.authenticate()
        labels = client.list_labels()
        doc = {"labels": [
            {k: v for k, v in l.items() if k in ("name", "color", "labelListVisibility", "messageListVisibility")}
            for l in labels if l.get("type") != "system"
        ], "redirects": []}
        path = out_dir / f"labels_{a.get('name','account')}.yaml"
        from .yamlio import dump_config
        dump_config(str(path), doc)
        print(f"Exported labels for {a.get('name')}: {path}")
    return 0


def _cmd_accounts_sync_labels(args: argparse.Namespace) -> int:
    accts = _load_accounts(args.config)
    for a in _iter_accounts(accts, args.accounts):
        provider = (a.get("provider") or "").lower()
        print(f"[labels sync] account={a.get('name')} provider={provider}")
        client = _build_provider_for_account(a)
        client.authenticate()
        desired_doc = load_config(args.labels)
        desired = desired_doc.get("labels") or []
        if provider == "outlook":
            desired = _normalize_labels_for_outlook(desired)
        existing = {l.get("name", ""): l for l in client.list_labels()}
        for spec in desired:
            name = spec.get("name")
            if not name:
                continue
            if name not in existing:
                if args.dry_run:
                    print(f"  would create label: {name}")
                else:
                    client.create_label(**spec)
                    print(f"  created label: {name}")
            else:
                # Prepare update if any supported field differs
                upd = {"name": name}
                cur = existing[name]
                changed = False
                if provider == "gmail":
                    for k in ("color", "labelListVisibility", "messageListVisibility"):
                        if spec.get(k) and spec.get(k) != cur.get(k):
                            upd[k] = spec[k]
                            changed = True
                elif provider == "outlook":
                    if spec.get("color") and spec.get("color") != cur.get("color"):
                        upd["color"] = spec["color"]
                        changed = True
                if changed:
                    if args.dry_run:
                        print(f"  would update label: {name}")
                    else:
                        client.update_label(cur.get("id", ""), upd)
                        print(f"  updated label: {name}")
    return 0


def _cmd_accounts_export_filters(args: argparse.Namespace) -> int:
    accts = _load_accounts(args.config)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for a in _iter_accounts(accts, args.accounts):
        client = _build_provider_for_account(a)
        client.authenticate()
        # Map label IDs to names
        id_to_name = {lab.get("id", ""): lab.get("name", "") for lab in client.list_labels()}
        def ids_to_names(ids):
            return [id_to_name.get(x) for x in ids or [] if id_to_name.get(x)]
        dsl = []
        for f in client.list_filters():
            crit = f.get("criteria", {}) or {}
            act = f.get("action", {}) or {}
            entry = {
                "match": {k: v for k, v in crit.items() if k in ("from","to","subject","query","negatedQuery","hasAttachment","size","sizeComparison") and v not in (None, "")},
                "action": {},
            }
            if act.get("forward"):
                entry["action"]["forward"] = act["forward"]
            if act.get("addLabelIds"):
                entry["action"]["add"] = ids_to_names(act.get("addLabelIds"))
            if act.get("removeLabelIds"):
                entry["action"]["remove"] = ids_to_names(act.get("removeLabelIds"))
            dsl.append(entry)
        path = out_dir / f"filters_{a.get('name','account')}.yaml"
        from .yamlio import dump_config
        dump_config(str(path), {"filters": dsl})
        print(f"Exported filters for {a.get('name')}: {path}")
    return 0


def _cmd_accounts_sync_filters(args: argparse.Namespace) -> int:
    accts = _load_accounts(args.config)
    for a in _iter_accounts(accts, args.accounts):
        provider = (a.get("provider") or "").lower()
        print(f"[filters sync] account={a.get('name')} provider={provider}")
        if provider == "gmail":
            ns = argparse.Namespace(
                credentials=a.get("credentials"),
                token=a.get("token"),
                cache=a.get("cache"),
                config=args.filters,
                dry_run=args.dry_run,
                delete_missing=False,
                require_forward_verified=args.require_forward_verified,
            )
            _cmd_filters_sync(ns)
            continue

        if provider == "outlook":
            client = _build_client_for_account(a)
            client.authenticate()
            doc = load_config(args.filters)
            desired = _normalize_filters_for_outlook(doc.get("filters") or [])
            # Build canonical keys for comparison
            def canon(f: dict) -> str:
                crit = f.get("criteria") or {}
                act = f.get("action") or {}
                return str({
                    "from": crit.get("from"),
                    "to": crit.get("to"),
                    "subject": crit.get("subject"),
                    "add": tuple(sorted(act.get("addLabelIds", []) or [])),
                    "forward": act.get("forward"),
                })
            existing = {canon(f): f for f in client.list_filters()}
            # label name -> id map for assignCategories
            name_to_id = client.get_label_id_map()
            created = 0
            for spec in desired:
                m = spec.get("match") or {}
                a_act = spec.get("action") or {}
                criteria = {k: v for k, v in m.items() if k in ("from", "to", "subject")}
                action = {}
                if a_act.get("add"):
                    action["addLabelIds"] = [name_to_id.get(x) or name_to_id.get(_norm_label_name_outlook(x)) for x in a_act["add"]]
                    action["addLabelIds"] = [x for x in action["addLabelIds"] if x]
                if a_act.get("forward"):
                    action["forward"] = a_act["forward"]
                key = str({
                    "from": criteria.get("from"),
                    "to": criteria.get("to"),
                    "subject": criteria.get("subject"),
                    "add": tuple(sorted(action.get("addLabelIds", []) or [])),
                    "forward": action.get("forward"),
                })
                if key in existing:
                    continue
                if args.dry_run:
                    print(f"  would create rule: criteria={criteria} action={action}")
                else:
                    try:
                        client.create_filter(criteria, action)
                        print("  created rule")
                    except Exception as e:
                        # Attempt to show Graph error body for easier troubleshooting
                        resp = getattr(e, 'response', None)
                        body = ''
                        try:
                            if resp is not None and hasattr(resp, 'text'):
                                body = resp.text
                        except Exception:
                            body = ''
                        print(f"  error creating rule: {e}{(' | ' + body) if body else ''}")
                created += 1
            print(f"  plan summary: created={created}")
            continue
        print(f"  provider not supported for filters: {provider}")
    return 0

from .utils.shield import mask_value as _mask_value  # credential shielding


def _cmd_config_inspect(args: argparse.Namespace) -> int:
    import configparser
    from pathlib import Path
    ini = Path(os.path.expanduser(args.path))
    if not ini.exists():
        print(f"Config not found: {ini}")
        return 2
    cp = configparser.ConfigParser()
    try:
        cp.read(ini)
    except Exception as e:
        print(f"Failed to read INI: {e}")
        return 3
    sections = cp.sections()
    if args.section:
        sections = [s for s in sections if s == args.section]
        if not sections:
            print(f"Section not found: {args.section}")
            return 4
    elif args.only_mail:
        sections = [s for s in sections if s.startswith("mail_assistant")]

    for s in sections:
        print(f"[{s}]")
        for k, v in cp.items(s):
            safe = _mask_value(k, v)
            print(f"{k} = {safe}")
        print("")
    return 0


def _cmd_config_derive_labels(args: argparse.Namespace) -> int:
    doc = load_config(getattr(args, 'in_path', None))
    labels = doc.get("labels") or []
    if not isinstance(labels, list):
        print("Input missing labels: []")
        return 2
    from .yamlio import dump_config
    # Gmail: pass-through
    from pathlib import Path
    out_g = Path(args.out_gmail)
    out_g.parent.mkdir(parents=True, exist_ok=True)
    dump_config(str(out_g), {"labels": labels})
    # Outlook: normalized names/colors
    from .dsl import normalize_labels_for_outlook
    out_o = Path(args.out_outlook)
    out_o.parent.mkdir(parents=True, exist_ok=True)
    dump_config(str(out_o), {"labels": normalize_labels_for_outlook(labels)})
    print(f"Derived labels -> gmail:{out_g} outlook:{out_o}")
    return 0


def _cmd_config_derive_filters(args: argparse.Namespace) -> int:
    doc = load_config(getattr(args, 'in_path', None))
    filters = doc.get("filters") or []
    if not isinstance(filters, list):
        print("Input missing filters: []")
        return 2
    from .yamlio import dump_config
    from pathlib import Path
    # Gmail: pass-through
    out_g = Path(args.out_gmail)
    out_g.parent.mkdir(parents=True, exist_ok=True)
    dump_config(str(out_g), {"filters": filters})
    # Outlook: normalized subset; optionally encode moveToFolder from first add
    from .dsl import normalize_filters_for_outlook
    out_specs = normalize_filters_for_outlook(filters)
    # If requested, when YAML removes INBOX, prefer Archive as destination on Outlook
    if getattr(args, 'outlook_archive_on_remove_inbox', False):
        for i, spec in enumerate(out_specs):
            a = spec.get("action") or {}
            # Look back into original filters for the matching index; if action.remove contains INBOX, set Archive
            try:
                orig = filters[i]
            except Exception:
                orig = {}
            orig_action = (orig or {}).get("action") or {}
            remove_list = orig_action.get("remove") or []
            if isinstance(remove_list, list) and any(str(x).upper() == 'INBOX' for x in remove_list):
                a["moveToFolder"] = "Archive"
                a.pop("add", None)
                spec["action"] = a
    elif getattr(args, 'outlook_move_to_folders', False):
        for spec in out_specs:
            a = spec.get("action") or {}
            adds = a.get("add") or []
            if adds and not a.get("moveToFolder"):
                # Preserve nested path if present in label
                a["moveToFolder"] = str(adds[0])
                spec["action"] = a
    out_o = Path(args.out_outlook)
    out_o.parent.mkdir(parents=True, exist_ok=True)
    dump_config(str(out_o), {"filters": out_specs})
    print(f"Derived filters -> gmail:{out_g} outlook:{out_o}")
    return 0


def _cmd_config_optimize_filters(args: argparse.Namespace) -> int:
    # Load unified
    doc = load_config(getattr(args, 'in_path', None))
    rules = doc.get("filters") or []
    if not isinstance(rules, list):
        print("Input missing filters: []")
        return 2
    # Group by primary destination label (first of action.add)
    from collections import defaultdict
    groups = defaultdict(list)
    passthrough = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        m = r.get('match') or {}
        a = r.get('action') or {}
        adds = a.get('add') or []
        # Only merge simple 'from'-only criteria with at least one destination label
        has_only_from = bool(m.get('from')) and all(k in (None, '') for k in [m.get('to'), m.get('subject'), m.get('query'), m.get('negatedQuery')])
        if adds and has_only_from:
            dest = str(adds[0])
            groups[dest].append(r)
        else:
            passthrough.append(r)

    merged = []
    preview = []
    threshold = max(2, int(getattr(args, 'merge_threshold', 2)))
    for dest, items in groups.items():
        # Partition items that are eligible (same remove/forward ignored, we keep adds[0] only)
        # Build OR of 'from' terms
        if len(items) < threshold:
            passthrough.extend(items)
            continue
        terms = []
        removes = set()
        forwards = set()
        for it in items:
            m = it.get('match') or {}
            a = it.get('action') or {}
            frm = str(m.get('from') or '').strip()
            if frm:
                terms.append(frm)
            for x in a.get('remove') or []:
                removes.add(x)
            if a.get('forward'):
                forwards.add(str(a.get('forward')))
        # Deduplicate terms by splitting on OR and trimming
        atoms = []
        for t in terms:
            parts = [p.strip() for p in t.split('OR') if p.strip()]
            atoms.extend(parts)
        uniq = sorted({a for a in atoms})
        if not uniq:
            passthrough.extend(items)
            continue
        merged_rule = {
            'name': f'merged_{dest.replace("/","_")}',
            'match': {'from': ' OR '.join(uniq)},
            'action': {'add': [dest]},
        }
        if removes:
            merged_rule['action']['remove'] = sorted(removes)
        # We drop forwards if multiple differ; Outlook often blocks forwarding; keep none.
        merged.append(merged_rule)
        preview.append((dest, len(items), len(uniq)))

    optimized = {'filters': merged + passthrough}
    # Write out
    from pathlib import Path
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    from .yamlio import dump_config
    dump_config(str(outp), optimized)
    if getattr(args, 'preview', False):
        print('Merged groups:')
        for dest, n, u in sorted(preview, key=lambda x: -x[1]):
            print(f'- {dest}: merged {n} rules into 1 (unique from terms={u})')
    print(f"Optimized filters written to {outp}. Original={len(rules)} Optimized={len(optimized['filters'])}")
    return 0


def _cmd_config_audit_filters(args: argparse.Namespace) -> int:
    # Load unified and export
    uni = load_config(getattr(args, 'in_path', None))
    exp = load_config(getattr(args, 'export_path', None))
    unified = uni.get('filters') or []
    exported = exp.get('filters') or []
    # Index unified by destination label and from tokens (split OR)
    dest_to_from_tokens: dict[str, set[str]] = {}
    for f in unified:
        if not isinstance(f, dict):
            continue
        a = f.get('action') or {}
        adds = a.get('add') or []
        if not adds:
            continue
        dest = str(adds[0])
        m = f.get('match') or {}
        frm = str(m.get('from') or '')
        toks = {t.strip().lower() for t in frm.split('OR') if t.strip()}
        if not toks:
            continue
        dest_to_from_tokens.setdefault(dest, set()).update(toks)

    # Consider only simple rules: from-only criteria with add labels (Gmail: addLabels, Unified/Outlook: add)
    simple_total = 0
    covered = 0
    missing_samples: list[tuple[str, str]] = []
    for f in exported:
        if not isinstance(f, dict):
            continue
        c = f.get('criteria') or f.get('match') or {}
        a = f.get('action') or {}
        if any(k in c for k in ('query','negatedQuery','size','sizeComparison')):
            continue
        if c.get('to') or c.get('subject'):
            continue
        frm = str(c.get('from') or '').strip().lower()
        adds = a.get('addLabels') or a.get('add') or []
        if not adds and a.get('moveToFolder'):
            adds = [str(a.get('moveToFolder'))]
        if not frm or not adds:
            continue
        simple_total += 1
        dest = str(adds[0])
        toks = dest_to_from_tokens.get(dest) or set()
        # Mark covered if any unified token is contained in exported from or equal
        cov = any((tok and (tok in frm or frm in tok)) for tok in toks)
        if cov:
            covered += 1
        elif len(missing_samples) < 10:
            missing_samples.append((dest, frm))

    not_cov = simple_total - covered
    pct = (not_cov / simple_total * 100.0) if simple_total else 0.0
    print(f"Simple Gmail rules: {simple_total}")
    print(f"Covered by unified: {covered}")
    print(f"Not unified: {not_cov} ({pct:.1f}%)")
    if getattr(args, 'preview_missing', False) and missing_samples:
        print("Missing examples (dest, from):")
        for dest, frm in missing_samples:
            print(f"- {dest} <- {frm}")
    return 0


def _cmd_workflows_gmail_from_unified(args: argparse.Namespace) -> int:
    """Workflow: derive Gmail filters from unified, plan, and optionally apply.

    Artifacts written under --out-dir:
      - filters.gmail.from_unified.yaml
      - filters.outlook.from_unified.yaml (side-effect; useful for parity)
    """
    out_dir = Path(getattr(args, 'out_dir', 'out'))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_gmail = out_dir / "filters.gmail.from_unified.yaml"
    out_outlook = out_dir / "filters.outlook.from_unified.yaml"

    # 1) Derive provider-specific configs from unified
    ns = argparse.Namespace(
        in_path=args.config,
        out_gmail=str(out_gmail),
        out_outlook=str(out_outlook),
        outlook_move_to_folders=True,
    )
    _cmd_config_derive_filters(ns)

    # 2) Plan Gmail changes
    ns_plan = argparse.Namespace(
        config=str(out_gmail),
        delete_missing=bool(getattr(args, 'delete_missing', False)),
        credentials=None,
        token=None,
        cache=None,
        profile=getattr(args, 'profile', None),
    )
    print("\n[Plan] Gmail filters vs derived from unified:")
    _cmd_filters_plan(ns_plan)

    # 3) Optionally apply
    if getattr(args, 'apply', False):
        ns_sync = argparse.Namespace(
            config=str(out_gmail),
            dry_run=False,
            delete_missing=bool(getattr(args, 'delete_missing', False)),
            require_forward_verified=False,
            credentials=None,
            token=None,
            cache=None,
            profile=getattr(args, 'profile', None),
        )
        print("\n[Apply] Syncing Gmail filters to match derived …")
        _cmd_filters_sync(ns_sync)
        print("\nDone. Consider exporting and comparing for drift:")
        print(f"  python3 -m mail_assistant filters export --out {out_dir}/filters.gmail.export.after.yaml")
        print(f"  Compare to {out_gmail}")
    else:
        print("\nNo changes applied (omit --apply to keep planning only).")
    return 0


def _cmd_env_setup(args: argparse.Namespace) -> int:
    """Create venv, install package, and persist credentials to INI.

    Safe defaults: if --no-venv and --skip-install are set, only INI persistence runs.
    """
    # 1) Venv + install
    venv_dir = Path(getattr(args, 'venv_dir', '.venv'))
    if not getattr(args, 'no_venv', False):
        try:
            if not venv_dir.exists():
                print(f"Creating venv at {venv_dir} …")
                __import__('venv').EnvBuilder(with_pip=True).create(str(venv_dir))
            if not getattr(args, 'skip_install', False):
                py = venv_dir / 'bin' / 'python'
                import subprocess
                print("Upgrading pip …")
                subprocess.run([str(py), '-m', 'pip', 'install', '-U', 'pip'], check=True)
                print("Installing package in editable mode …")
                subprocess.run([str(py), '-m', 'pip', 'install', '-e', '.'], check=True)
        except Exception as e:
            print(f"Venv/setup failed: {e}")
            return 2
        # Ensure wrappers executable
        for fname in ('bin/mail_assistant', 'bin/mail-assistant'):
            try:
                p = Path(fname)
                if p.exists():
                    os.chmod(p, (p.stat().st_mode | 0o111))
            except Exception:
                pass

    # 2) Persist INI settings
    from .config_resolver import persist_profile_settings
    prof = getattr(args, 'profile', None)
    cred_path = getattr(args, 'credentials', None)
    tok_path = getattr(args, 'token', None)

    # Optionally copy example Gmail creds to the default external path
    if getattr(args, 'copy_gmail_example', False) and not cred_path:
        ex = Path('credentials.example.json')
        dest = Path(expand_path(default_gmail_credentials_path()))
        if ex.exists() and not dest.exists():
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(ex.read_text(encoding='utf-8'), encoding='utf-8')
                cred_path = str(dest)
                print(f"Copied {ex} → {dest}")
            except Exception as e:
                print(f"Warning: failed to copy example credentials: {e}")
    # Default token path if user provided credentials but no token
    if cred_path and not tok_path:
        tok_path = default_gmail_token_path()

    # Ensure parent dirs exist for provided paths
    for pth in (cred_path, tok_path, getattr(args, 'outlook_token', None)):
        if pth:
            try:
                Path(os.path.expanduser(pth)).parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    if any([cred_path, tok_path, getattr(args, 'outlook_client_id', None), getattr(args, 'tenant', None), getattr(args, 'outlook_token', None)]):
        persist_profile_settings(
            profile=prof,
            credentials=cred_path,
            token=tok_path,
            outlook_client_id=getattr(args, 'outlook_client_id', None),
            tenant=getattr(args, 'tenant', None),
            outlook_token=getattr(args, 'outlook_token', None),
        )
        print("Persisted settings to ~/.config/credentials.ini")
    else:
        print("No profile settings provided; skipped INI write.")

    print("Environment setup complete.")
    return 0


def _cmd_workflows_from_unified(args: argparse.Namespace) -> int:
    """Workflow: derive provider configs from unified and plan/apply per provider.

    Providers handled: Gmail, Outlook. Detection is based on presence of
    local credentials/token (Gmail) and client_id/token (Outlook via env/ini/accounts).
    """
    out_dir = Path(getattr(args, 'out_dir', 'out'))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_gmail = out_dir / "filters.gmail.from_unified.yaml"
    out_outlook = out_dir / "filters.outlook.from_unified.yaml"

    # 0) Derive both provider configs from unified
    ns = argparse.Namespace(
        in_path=args.config,
        out_gmail=str(out_gmail),
        out_outlook=str(out_outlook),
        outlook_move_to_folders=bool(getattr(args, 'outlook_move_to_folders', True)),
    )
    _cmd_config_derive_filters(ns)

    # 1) Decide providers
    requested = None
    if getattr(args, 'providers', None):
        requested = {p.strip().lower() for p in str(args.providers).split(',') if p.strip()}

    run_gmail = run_outlook = False
    if requested is None or 'gmail' in requested:
        # Detect Gmail config from profile/ini or default local files
        try:
            from .config_resolver import resolve_paths_profile
            cpath, tpath = resolve_paths_profile(arg_credentials=None, arg_token=None, profile=getattr(args, 'profile', None))
            cpath = os.path.expanduser(cpath or '')
            tpath = os.path.expanduser(tpath or '')
            if os.path.exists(cpath) or os.path.exists(tpath):
                run_gmail = True
        except Exception:
            run_gmail = False
        if requested and 'gmail' in requested:
            # Respect explicit request even if detection fails; print a note
            run_gmail = True

    if requested is None or 'outlook' in requested:
        # Detect Outlook via resolver
        try:
            # Reuse outlook arg resolver for discovery
            oargs = argparse.Namespace(
                client_id=None,
                tenant=None,
                token=None,
                accounts_config=getattr(args, 'accounts_config', None),
                account=getattr(args, 'account', None),
                profile=getattr(args, 'profile', None),
            )
            cid, _ten, _tok, _cache = _resolve_outlook_args(oargs)
            if cid:
                run_outlook = True
        except Exception:
            run_outlook = False
        if requested and 'outlook' in requested:
            run_outlook = True

    # 2) Gmail plan/apply
    if run_gmail:
        print("\n[Gmail] Plan:")
        ns_plan = argparse.Namespace(
            config=str(out_gmail),
            delete_missing=bool(getattr(args, 'delete_missing', False)),
            credentials=None,
            token=None,
            cache=None,
            profile=getattr(args, 'profile', None),
        )
        _cmd_filters_plan(ns_plan)
        if getattr(args, 'apply', False):
            print("\n[Gmail] Apply:")
            ns_sync = argparse.Namespace(
                config=str(out_gmail),
                dry_run=False,
                delete_missing=bool(getattr(args, 'delete_missing', False)),
                require_forward_verified=False,
                credentials=None,
                token=None,
                cache=None,
                profile=getattr(args, 'profile', None),
            )
            _cmd_filters_sync(ns_sync)
    else:
        if requested is None or 'gmail' in (requested or set(['gmail'])):
            print("\n[Gmail] Skipping (no credentials/token detected). Use --profile or env setup.")

    # 3) Outlook plan/apply
    if run_outlook:
        print("\n[Outlook] Plan:")
        ns_pl = argparse.Namespace(
            config=str(out_outlook),
            client_id=None,
            tenant=None,
            token=None,
            accounts_config=getattr(args, 'accounts_config', None),
            account=getattr(args, 'account', None),
            profile=getattr(args, 'profile', None),
            use_cache=False,
            cache_ttl=600,
        )
        _cmd_outlook_rules_plan(ns_pl)
        if getattr(args, 'apply', False):
            print("\n[Outlook] Apply:")
            ns_sync = argparse.Namespace(
                config=str(out_outlook),
                client_id=None,
                tenant=None,
                token=None,
                accounts_config=getattr(args, 'accounts_config', None),
                account=getattr(args, 'account', None),
                profile=getattr(args, 'profile', None),
                dry_run=False,
                delete_missing=bool(getattr(args, 'delete_missing', False)),
                move_to_folders=bool(getattr(args, 'outlook_move_to_folders', True)),
            )
            _cmd_outlook_rules_sync(ns_sync)
    else:
        if requested is None or 'outlook' in (requested or set(['outlook'])):
            print("\n[Outlook] Skipping (no client_id/token detected). Use env setup or accounts.yaml.")

    if not (run_gmail or run_outlook):
        print("No configured providers detected; nothing to do.")
        return 2
    return 0


def _cmd_accounts_plan_labels(args: argparse.Namespace) -> int:
    accts = _load_accounts(args.config)
    desired_doc = load_config(args.labels)
    base = desired_doc.get("labels") or []
    for a in _iter_accounts(accts, args.accounts):
        provider = (a.get("provider") or "").lower()
        client = _build_provider_for_account(a)
        client.authenticate()
        existing = {l.get("name", ""): l for l in client.list_labels(use_cache=True)}
        target = base
        if provider == "outlook":
            target = _normalize_labels_for_outlook(base)
        to_create = []
        to_update = []
        for spec in target:
            name = spec.get("name")
            if not name:
                continue
            if name not in existing:
                to_create.append(name)
            else:
                cur = existing[name]
                if provider == "gmail":
                    for k in ("color", "labelListVisibility", "messageListVisibility"):
                        if spec.get(k) and spec.get(k) != cur.get(k):
                            to_update.append(name); break
                elif provider == "outlook":
                    if spec.get("color") and spec.get("color") != cur.get("color"):
                        to_update.append(name)
        print(f"[plan-labels] {a.get('name')} provider={provider} create={len(to_create)} update={len(to_update)}")
    return 0


def _cmd_accounts_plan_filters(args: argparse.Namespace) -> int:
    accts = _load_accounts(args.config)
    desired_doc = load_config(args.filters)
    base = desired_doc.get("filters") or []
    for a in _iter_accounts(accts, args.accounts):
        provider = (a.get("provider") or "").lower()
        client = _build_provider_for_account(a)
        client.authenticate()
        existing = client.list_filters(use_cache=True)
        if provider == "gmail":
            # Canonicalize
            def canon(f: dict) -> str:
                crit = f.get("criteria") or {}
                act = f.get("action") or {}
                return str({
                    "from": crit.get("from"),
                    "to": crit.get("to"),
                    "subject": crit.get("subject"),
                    "query": crit.get("query"),
                    "add": tuple(sorted((act.get("addLabelIds") or []))),
                    "forward": act.get("forward"),
                })
            ex_keys = {canon(f) for f in existing}
            desired_keys = set()
            for f in base:
                m = f.get("match") or {}
                a_act = f.get("action") or {}
                desired_keys.add(str({
                    "from": m.get("from"),
                    "to": m.get("to"),
                    "subject": m.get("subject"),
                    "query": m.get("query"),
                    "add": tuple(sorted((a_act.get("add") or []))),
                    "forward": a_act.get("forward"),
                }))
            create = len([k for k in desired_keys if k not in ex_keys])
            print(f"[plan-filters] {a.get('name')} provider=gmail create={create}")
        elif provider == "outlook":
            desired = _normalize_filters_for_outlook(base)
            def canon_o(f: dict) -> str:
                crit = f.get("criteria") or {}
                act = f.get("action") or {}
                return str({
                    "from": crit.get("from"),
                    "to": crit.get("to"),
                    "subject": crit.get("subject"),
                    "add": tuple(sorted((act.get("addLabelIds") or []))),
                    "forward": act.get("forward"),
                })
            ex_keys = {canon_o(f) for f in existing}
            desired_keys = set()
            for f in desired:
                m = f.get("match") or {}
                a_act = f.get("action") or {}
                desired_keys.add(str({
                    "from": m.get("from"),
                    "to": m.get("to"),
                    "subject": m.get("subject"),
                    "add": tuple(sorted((a_act.get("add") or []))),
                    "forward": a_act.get("forward"),
                }))
            create = len([k for k in desired_keys if k not in ex_keys])
            print(f"[plan-filters] {a.get('name')} provider=outlook create={create}")
        else:
            print(f"[plan-filters] {a.get('name')} provider={provider} not supported")
    return 0


def _cmd_accounts_export_signatures(args: argparse.Namespace) -> int:
    accts = _load_accounts(args.config)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for a in _iter_accounts(accts, args.accounts):
        name = a.get("name", "account")
        provider = (a.get("provider") or "").lower()
        path = out_dir / f"signatures_{name}.yaml"
        assets = out_dir / f"{name}_assets"
        assets.mkdir(parents=True, exist_ok=True)
        doc = {"signatures": {"gmail": [], "ios": {}, "outlook": []}}
        if provider == "gmail":
            client = _build_provider_for_account(a)
            client.authenticate()
            sigs = client.list_signatures()
            doc["signatures"]["gmail"] = [
                {
                    "sendAs": s.get("sendAsEmail"),
                    "isPrimary": s.get("isPrimary", False),
                    "signature_html": s.get("signature", ""),
                }
                for s in sigs
            ]
            prim = next((s for s in doc["signatures"]["gmail"] if s.get("isPrimary")), None)
            if prim and prim.get("signature_html"):
                doc["signatures"]["default_html"] = prim["signature_html"]
                (assets / "ios_signature.html").write_text(prim["signature_html"], encoding="utf-8")
        elif provider == "outlook":
            # Not available via Graph; write guidance file
            (assets / "OUTLOOK_README.txt").write_text(
                "Outlook signatures are not exposed via Microsoft Graph v1.0.\n"
                "Use ios_signature.html exported from a Gmail account, or paste HTML manually.",
                encoding="utf-8",
            )
        from .yamlio import dump_config
        dump_config(str(path), doc)
        print(f"Exported signatures for {name}: {path}")
    return 0


def _cmd_accounts_sync_signatures(args: argparse.Namespace) -> int:
    accts = _load_accounts(args.config)
    for a in _iter_accounts(accts, args.accounts):
        provider = (a.get("provider") or "").lower()
        print(f"[signatures sync] account={a.get('name')} provider={provider}")
        if provider == "gmail":
            ns = argparse.Namespace(
                credentials=a.get("credentials"),
                token=a.get("token"),
                config=args.config,
                send_as=args.send_as,
                dry_run=args.dry_run,
                account_display_name=a.get("display_name"),
            )
            run_signatures_sync(ns)
        elif provider == "outlook":
            # Not supported via API; drop guidance file only
            assets = Path("signatures_assets")
            assets.mkdir(parents=True, exist_ok=True)
            (assets / "OUTLOOK_README.txt").write_text(
                "Outlook signatures are not exposed via Microsoft Graph v1.0.\n"
                "Use ios_signature.html or paste HTML manually.",
                encoding="utf-8",
            )
            print("  Outlook: wrote guidance to signatures_assets/OUTLOOK_README.txt")
        else:
            print(f"  Unsupported provider: {provider}")
    return 0


# -------------- Messages: search, summarize, reply --------------

def _select_message_id(args: argparse.Namespace, client) -> tuple[Optional[str], Optional[str]]:
    """Return (message_id, thread_id) resolved from --id or --query/--latest."""
    mid = getattr(args, "id", None)
    if mid:
        try:
            meta = client.get_message(mid, fmt="metadata")
            return meta.get("id"), meta.get("threadId")
        except Exception:
            return mid, None
    q = (getattr(args, "query", None) or "").strip()
    if q:
        crit = {"query": q}
        q_built = _build_gmail_query(crit, days=getattr(args, "days", None), only_inbox=getattr(args, "only_inbox", False))
        ids = client.list_message_ids(query=q_built, max_pages=1, page_size=1)
        if ids:
            try:
                meta = client.get_message(ids[0], fmt="metadata")
                return meta.get("id"), meta.get("threadId")
            except Exception:
                return ids[0], None
    return None, None


def _cmd_messages_search(args: argparse.Namespace) -> int:
    from .utils.cli_helpers import gmail_provider_from_args
    from .messages import candidates_from_metadata
    import json as _json

    client = gmail_provider_from_args(args)
    client.authenticate()
    crit = {"query": getattr(args, "query", "") or ""}
    q = _build_gmail_query(crit, days=getattr(args, "days", None), only_inbox=getattr(args, "only_inbox", False))
    max_results = int(getattr(args, "max_results", 5) or 5)
    ids = client.list_message_ids(query=q, max_pages=1, page_size=max_results)
    msgs = client.get_messages_metadata(ids, use_cache=True)
    cands = candidates_from_metadata(msgs)
    if getattr(args, "json", False):
        print(_json.dumps([c.__dict__ for c in cands], ensure_ascii=False, indent=2))
    else:
        for c in cands:
            print(f"{c.id}\t{c.subject}\t{c.from_header}\t{c.snippet}")
    return 0


def _cmd_messages_summarize(args: argparse.Namespace) -> int:
    from .utils.cli_helpers import gmail_provider_from_args
    from .llm_adapter import summarize_text

    client = gmail_provider_from_args(args)
    client.authenticate()
    mid, _thread = _select_message_id(args, client)
    if not mid:
        print("No message found. Provide --id or a --query with --latest.")
        return 1
    text = client.get_message_text(mid)
    summary = summarize_text(text, max_words=int(getattr(args, "max_words", 120) or 120))
    summary_out = f"Summary: {summary}" if summary and not summary.lower().startswith("summary:") else summary
    outp = getattr(args, "out", None)
    if outp:
        p = Path(outp)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(summary_out, encoding="utf-8")
        print(f"Summary written to {p}")
    else:
        print(summary_out)
    return 0


def _cmd_messages_reply(args: argparse.Namespace) -> int:
    from .utils.cli_helpers import gmail_provider_from_args
    from .messages import _compose_reply, encode_email_message
    from .llm_adapter import summarize_text
    from .yamlio import load_config
    from email.utils import formatdate

    client = gmail_provider_from_args(args)
    client.authenticate()
    mid, thread_id = _select_message_id(args, client)
    if not mid:
        print("No message found. Provide --id or a --query with --latest.")
        return 1

    # Fetch headers for reply context
    msg_full = client.get_message(mid, fmt="full")
    headers = {h.get("name", "").lower(): h.get("value", "") for h in ((msg_full.get("payload") or {}).get("headers") or [])}
    orig_subj = headers.get("subject", "")
    msg_id = headers.get("message-id")
    refs = headers.get("references")
    reply_to = headers.get("reply-to") or headers.get("from") or ""
    _, to_email = __import__("email.utils").utils.parseaddr(reply_to)
    if not to_email:
        print("Could not determine recipient from original message headers")
        return 1

    profile = None
    try:
        profile = client.get_profile()
    except Exception:
        profile = {"emailAddress": ""}
    from_email = profile.get("emailAddress") or "me"

    # Build reply body
    points_text = getattr(args, "points", None) or ""
    plan_path = getattr(args, "points_file", None)
    if plan_path:
        doc = load_config(plan_path)
        goals = doc.get("goals") or doc.get("points") or []
        if isinstance(goals, list):
            points_text = points_text or "\n".join(f"- {g}" for g in goals if g)
        if not getattr(args, "signoff", None) and doc.get("signoff"):
            args.signoff = str(doc.get("signoff"))

    body_lines = []
    if points_text:
        pts = [ln.strip() for ln in str(points_text).splitlines() if ln.strip()]
        if len(pts) == 1 and not pts[0].startswith("-"):
            body_lines.append(pts[0])
        else:
            body_lines.append("Here are the points:")
            body_lines.extend([f"- {p.lstrip('-').strip()}" for p in pts])

    if getattr(args, "include_summary", False):
        orig_text = client.get_message_text(mid)
        summ = summarize_text(orig_text, max_words=80)
        body_lines.insert(0, f"Summary: {summ}")

    signoff = getattr(args, "signoff", None) or "Thanks,"
    body_lines.append("")
    body_lines.append(signoff)

    # Compose message
    subject = getattr(args, "subject", None) or orig_subj
    include_quote = bool(getattr(args, "include_quote", False))
    original_text = client.get_message_text(mid) if include_quote else None
    msg = _compose_reply(
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        body_text="\n".join(body_lines).strip(),
        in_reply_to=msg_id,
        references=(f"{refs} {msg_id}".strip() if msg_id else refs),
        cc=[str(x) for x in getattr(args, "cc", []) if x],
        bcc=[str(x) for x in getattr(args, "bcc", []) if x],
        include_quote=include_quote,
        original_text=original_text,
    )
    # Date for better previews
    msg["Date"] = formatdate(localtime=True)

    raw = encode_email_message(msg)
    # Planning path
    if getattr(args, "plan", False):
        when = None
        if getattr(args, "send_at", None):
            when = str(getattr(args, "send_at"))
        elif getattr(args, "send_in", None):
            when = str(getattr(args, "send_in"))
        print("Plan: reply")
        print(f"  to: {to_email}")
        if args.cc:
            print(f"  cc: {', '.join(args.cc)}")
        if args.bcc:
            print(f"  bcc: {', '.join(args.bcc)}")
        print(f"  subject: {'Re: ' + orig_subj if not getattr(args, 'subject', None) else args.subject}")
        if when:
            print(f"  when: {when}")
        print("  action: send (with --apply) or create draft (--create-draft)")
        return 0
    # Scheduling support
    send_at = getattr(args, "send_at", None)
    send_in = getattr(args, "send_in", None)
    if send_at or send_in:
        from .scheduler import parse_send_at, parse_send_in, enqueue, ScheduledItem
        import base64
        due = None
        if send_at:
            due = parse_send_at(str(send_at))
        if due is None and send_in:
            delta = parse_send_in(str(send_in))
            if delta:
                due = int(__import__("time").time()) + int(delta)
        if due is None:
            print("Invalid --send-at/--send-in; expected 'YYYY-MM-DD HH:MM' or like '2h30m'")
            return 1
        prof = getattr(args, "profile", None) or "default"
        item = ScheduledItem(
            provider="gmail",
            profile=str(prof),
            due_at=int(due),
            raw_b64=base64.b64encode(raw).decode("utf-8"),
            thread_id=thread_id,
            to=to_email,
            subject=subject or "",
        )
        enqueue(item)
        from datetime import datetime
        print(f"Queued reply to {to_email} at {datetime.fromtimestamp(due).strftime('%Y-%m-%d %H:%M')}")
        # Also write preview if requested
        draft_out = getattr(args, "draft_out", None)
        if draft_out:
            p = Path(draft_out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
            print(f"Draft written to {p}")
        return 0

    if getattr(args, "apply", False):
        client.send_message_raw(raw, thread_id=thread_id)
        print(f"Sent reply to {to_email} (thread {thread_id or 'new'})")
        return 0

    if getattr(args, "create_draft", False):
        d = client.create_draft_raw(raw, thread_id=thread_id)
        did = (d or {}).get('id') or '(draft id unavailable)'
        print(f"Created Gmail draft id={did}")
        return 0

    draft_out = getattr(args, "draft_out", None)
    if draft_out:
        p = Path(draft_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        print(f"Draft written to {p}")
    else:
        # Preview to stdout
        text = raw.decode("utf-8", errors="replace")
        head = "\n".join(text.splitlines()[:20])
        print(head)
        print("... (preview; use --draft-out to write .eml or --apply to send)")
    return 0


def _cmd_messages_apply_scheduled(args: argparse.Namespace) -> int:
    from .scheduler import pop_due
    from .utils.cli_helpers import gmail_provider_from_args
    import base64
    sent = 0
    due = pop_due(profile=getattr(args, "profile", None), limit=int(getattr(args, "max", 10) or 10))
    if not due:
        print("No scheduled messages due.")
        return 0
    # Group by profile for provider reuse
    by_profile = {}
    for it in due:
        by_profile.setdefault(it.get("profile") or "default", []).append(it)
    for prof, items in by_profile.items():
        ns = argparse.Namespace(profile=prof, credentials=None, token=None, cache=None)
        client = gmail_provider_from_args(ns)
        client.authenticate()
        for it in items:
            raw = base64.b64decode(it.get("raw_b64") or b"")
            thread_id = it.get("thread_id")
            client.send_message_raw(raw, thread_id=thread_id)
            sent += 1
            to = it.get("to") or "recipient"
            subj = it.get("subject") or ""
            print(f"Sent scheduled message to {to} subject='{subj}' profile={prof}")
    print(f"Scheduled send complete. Sent: {sent}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    # Install conservative secret shielding for stdout/stderr (env-toggled)
    try:
        from .utils.secrets import install_output_masking_from_env as _install_mask
        _install_mask()
    except Exception:
        # Best-effort: never fail CLI due to masking
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    agentic_result = assistant.maybe_emit_agentic(
        args,
        emit_func=lambda fmt, compact: _lazy_emit_agentic()(fmt, compact),
    )
    if agentic_result is not None:
        return agentic_result
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return int(func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
