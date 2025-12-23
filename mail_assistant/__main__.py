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
from .labels.commands import (
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
from .filters.commands import (
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
from .accounts.commands import (
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
from .messages_cli.commands import (
    run_messages_search,
    run_messages_summarize,
    run_messages_reply,
    run_messages_apply_scheduled,
)
from .config_cli.commands import (
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
    p_auth.set_defaults(func=run_auth)

    # labels group (registered via helper)
    from .cli.labels import register as _register_labels

    _register_labels(
        sub,
        f_list=run_labels_list,
        f_sync=run_labels_sync,
        f_export=run_labels_export,
        f_plan=run_labels_plan,
        f_doctor=run_labels_doctor,
        f_prune_empty=run_labels_prune_empty,
        f_learn=run_labels_learn,
        f_apply_suggestions=run_labels_apply_suggestions,
        f_delete=run_labels_delete,
        f_sweep_parents=run_labels_sweep_parents,
    )

    # filters group (registered via helper)
    from .cli.filters import register as _register_filters

    _register_filters(
        sub,
        f_list=run_filters_list,
        f_export=run_filters_export,
        f_sync=run_filters_sync,
        f_plan=run_filters_plan,
        f_impact=run_filters_impact,
        f_sweep=run_filters_sweep,
        f_sweep_range=run_filters_sweep_range,
        f_delete=run_filters_delete,
        f_prune_empty=run_filters_prune_empty,
        f_add_forward_by_label=run_filters_add_forward_by_label,
        f_add_from_token=run_filters_add_from_token,
        f_rm_from_token=run_filters_rm_from_token,
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
    p_msgs_search.set_defaults(func=run_messages_search)

    # messages summarize
    p_msgs_sum = sub_msgs.add_parser("summarize", help="Summarize a message's content")
    p_msgs_sum.add_argument("--id", type=str, help="Message ID to summarize")
    p_msgs_sum.add_argument("--query", type=str, help="Fallback query to pick latest message if id not given")
    p_msgs_sum.add_argument("--days", type=int, help="Restrict query to last N days")
    p_msgs_sum.add_argument("--only-inbox", action="store_true")
    p_msgs_sum.add_argument("--latest", action="store_true", help="Pick latest matching message when using --query")
    p_msgs_sum.add_argument("--out", type=str, help="Write summary to this file (else stdout)")
    p_msgs_sum.add_argument("--max-words", type=int, default=120)
    p_msgs_sum.set_defaults(func=run_messages_summarize)

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
    p_msgs_reply.set_defaults(func=run_messages_reply)

    # messages apply-scheduled
    p_msgs_apply = sub_msgs.add_parser("apply-scheduled", help="Send any scheduled messages that are due now")
    p_msgs_apply.add_argument("--max", type=int, default=10, help="Max messages to send in one run")
    p_msgs_apply.add_argument("--profile", type=str, help="Only send for a specific profile")
    p_msgs_apply.set_defaults(func=run_messages_apply_scheduled)

    # backup group
    p_backup = sub.add_parser("backup", help="Backup Gmail labels and filters to a timestamped folder")
    _add_gmail_args(p_backup)
    p_backup.add_argument("--out-dir", help="Output directory (default backups/<timestamp>)")
    p_backup.set_defaults(func=run_backup)

    # cache group (MailCache operations)
    p_cache = sub.add_parser("cache", help="Manage local message cache")
    p_cache.add_argument("--cache", required=True, help="Cache directory root")
    sub_cache = p_cache.add_subparsers(dest="cache_cmd")
    p_cache_stats = sub_cache.add_parser("stats", help="Show cache stats")
    p_cache_stats.set_defaults(func=run_cache_stats)
    p_cache_clear = sub_cache.add_parser("clear", help="Delete entire cache")
    p_cache_clear.set_defaults(func=run_cache_clear)
    p_cache_prune = sub_cache.add_parser("prune", help="Prune files older than N days")
    p_cache_prune.add_argument("--days", type=int, required=True)
    p_cache_prune.set_defaults(func=run_cache_prune)

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
    p_cfg_inspect.set_defaults(func=run_config_inspect)

    p_cfg_derive = sub_cfg.add_parser("derive", help="Derive provider-specific configs from a unified YAML")
    sub_cfg_derive = p_cfg_derive.add_subparsers(dest="derive_cmd")
    p_cfg_derive_labels = sub_cfg_derive.add_parser("labels", help="Derive Gmail and Outlook labels YAML from unified labels.yaml")
    p_cfg_derive_labels.add_argument("--in", dest="in_path", required=True, help="Unified labels YAML (labels: [])")
    p_cfg_derive_labels.add_argument("--out-gmail", required=True, help="Output Gmail labels YAML")
    p_cfg_derive_labels.add_argument("--out-outlook", required=True, help="Output Outlook categories YAML")
    p_cfg_derive_labels.set_defaults(func=run_config_derive_labels)

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
    p_cfg_derive_filters.set_defaults(func=run_config_derive_filters)

    # config optimize
    p_cfg_opt = sub_cfg.add_parser("optimize", help="Optimize unified configs by merging similar rules")
    sub_cfg_opt = p_cfg_opt.add_subparsers(dest="optimize_cmd")
    p_cfg_opt_filters = sub_cfg_opt.add_parser("filters", help="Merge rules with same destination label and simple from criteria")
    p_cfg_opt_filters.add_argument("--in", dest="in_path", required=True, help="Unified filters YAML (filters: [])")
    p_cfg_opt_filters.add_argument("--out", required=True, help="Output optimized unified filters YAML")
    p_cfg_opt_filters.add_argument("--merge-threshold", type=int, default=2, help="Minimum number of rules to merge (default 2)")
    p_cfg_opt_filters.add_argument("--preview", action="store_true", help="Print a summary of merges")
    p_cfg_opt_filters.set_defaults(func=run_config_optimize_filters)

    # config audit
    p_cfg_audit = sub_cfg.add_parser("audit", help="Audit unified coverage vs provider exports")
    sub_cfg_audit = p_cfg_audit.add_subparsers(dest="audit_cmd")
    p_cfg_audit_filters = sub_cfg_audit.add_parser("filters", help="Report percentage of simple Gmail rules not present in unified config")
    p_cfg_audit_filters.add_argument("--in", dest="in_path", required=True, help="Unified filters YAML (filters: [])")
    p_cfg_audit_filters.add_argument("--export", dest="export_path", required=True, help="Gmail exported filters YAML (from 'filters export')")
    p_cfg_audit_filters.add_argument("--preview-missing", action="store_true", help="List a few missing simple rules")
    p_cfg_audit_filters.set_defaults(func=run_config_audit_filters)

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
    p_wf_g.set_defaults(func=run_workflows_gmail_from_unified)

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
    p_wf_all.set_defaults(func=run_workflows_from_unified)

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
    p_env_setup.set_defaults(func=run_env_setup)

    # accounts group (1-to-many operations across providers)
    p_accts = sub.add_parser("accounts", help="Operate across multiple email accounts/providers")
    sub_accts = p_accts.add_subparsers(dest="accounts_cmd")

    for help_name, func, extra_args in [
        ("list", run_accounts_list, []),
        ("export-labels", run_accounts_export_labels, [("--out-dir", {"required": True})]),
        ("sync-labels", run_accounts_sync_labels, [("--labels", {"required": True})]),
        ("export-filters", run_accounts_export_filters, [("--out-dir", {"required": True})]),
        ("sync-filters", run_accounts_sync_filters, [("--filters", {"required": True}), ("--require-forward-verified", {"action": "store_true"})]),
        ("plan-labels", run_accounts_plan_labels, [("--labels", {"required": True})]),
        ("plan-filters", run_accounts_plan_filters, [("--filters", {"required": True})]),
        ("export-signatures", run_accounts_export_signatures, [("--out-dir", {"required": True})]),
        ("sync-signatures", run_accounts_sync_signatures, [("--send-as", {})]),
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

def main(argv: Optional[list[str]] = None) -> int:
    # Install conservative secret shielding for stdout/stderr (env-toggled)
    try:
        from .utils.secrets import install_output_masking_from_env as _install_mask
        _install_mask()
    except Exception:
        pass  # nosec B110 - best-effort masking, never fail CLI
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
