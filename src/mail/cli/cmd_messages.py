"""Messages command group registration for Mail Assistant CLI."""
from __future__ import annotations

from typing import Any

from core.cli_framework import CLIApp
from core.cli_help_text import HELP_DAYS_BACK

# One argparse argument: the flag names, plus the kwargs forwarded to
# add_argument(). Values are heterogeneous (str, bool, int), hence Any.
ArgSpec = tuple[tuple[str, ...], dict[str, Any]]

# Repeated help-text strings extracted as module-level constants
HELP_CREDENTIALS = "Path to OAuth credentials.json"
HELP_TOKEN = "Path to token.json"  # nosec B105 - argparse help text, not a credential

_AUTH_ARGS: tuple[ArgSpec, ...] = (
    (("--credentials",), {"help": HELP_CREDENTIALS}),
    (("--token",), {"help": HELP_TOKEN}),
)


def register_messages_commands(app: CLIApp) -> object:
    """Register all messages subcommands on app and return the messages group."""
    from ..messages_cli.commands import (
        run_messages_search,
        run_messages_summarize,
        run_messages_get,
    )
    from ..messages_cli.commands_threads import (
        run_messages_threads_get,
    )
    from ..messages_cli.commands_reply import (
        run_messages_reply,
        run_messages_apply_scheduled,
    )
    from ..messages_cli.commands_attachments import (
        run_messages_list_attachments,
        run_messages_download_attachment,
    )

    # (subcommand, help, handler, extra args appended after the shared auth pair)
    specs: list[tuple[str, str, Any, list[ArgSpec]]] = [
        ("search", "Search for messages and list candidates", run_messages_search, [
            (("--query",), {"default": "", "help": "Search query (Gmail syntax or Outlook $search)"}),
            (("--days",), {"type": int, "help": "Restrict to last N days"}),
            (("--only-inbox",), {"action": "store_true", "help": "Restrict to inbox"}),
            (("--max-results",), {"type": int, "default": 5, "help": "Max results"}),
            (("--from",), {"dest": "from_", "help": "Sender filter (Gmail only)"}),
            (("--to",), {"help": "Recipient filter (Gmail only)"}),
            (("--subject-contains",), {"dest": "subject_contains", "help": "Subject substring (Gmail only)"}),
            (("--not-query",), {"dest": "not_query", "help": "Exclude messages matching query (Gmail only)"}),
            (("--has-attachment",), {"action": "store_true", "help": "Only messages with attachments (Gmail only)"}),
            (("--unread",), {"action": "store_true", "help": "Only unread messages (Gmail only)"}),
            (("--json",), {"action": "store_true", "help": "Output JSON"}),
        ]),
        ("summarize", "Summarize a message's content", run_messages_summarize, [
            (("--id",), {"help": "Message ID to summarize"}),
            (("--query",), {"help": "Fallback query if id not given"}),
            (("--days",), {"type": int, "help": HELP_DAYS_BACK}),
            (("--only-inbox",), {"action": "store_true"}),
            (("--latest",), {"action": "store_true", "help": "Pick latest matching message"}),
            (("--out",), {"help": "Write summary to file"}),
            (("--max-words",), {"type": int, "default": 120, "help": "Max words in summary"}),
        ]),
        ("get", "Fetch and print a message body", run_messages_get, [
            (("--id",), {"help": "Message ID"}),
            (("--ids",), {"help": "Comma-separated message IDs (e.g. A,B,C)"}),
            (("--query",), {"help": "Fallback query if id not given"}),
            (("--days",), {"type": int, "help": "Restrict query to last N days"}),
            (("--only-inbox",), {"action": "store_true", "help": "Restrict query to inbox"}),
            (("--format",), {"choices": ["text", "json"], "default": "text", "help": "Output format (default: text)"}),
        ]),
        ("threads-get", "Fetch all messages in a conversation", run_messages_threads_get, [
            (("--thread-id",), {"help": "Thread ID"}),
            (("--id",), {"help": "Message ID to resolve the thread from"}),
            (("--query",), {"help": "Fallback query if thread-id/id not given"}),
            (("--days",), {"type": int, "help": "Restrict query to last N days"}),
            (("--only-inbox",), {"action": "store_true", "help": "Restrict query to inbox"}),
            (("--include-body",), {"action": "store_true", "help": "Include each message body"}),
            (("--json",), {"action": "store_true", "help": "Output JSON"}),
        ]),
        ("reply", "Draft or send a reply for a message", run_messages_reply, [
            (("--id",), {"help": "Message ID to reply to"}),
            (("--query",), {"help": "Fallback query if id not given"}),
            (("--days",), {"type": int, "help": HELP_DAYS_BACK}),
            (("--only-inbox",), {"action": "store_true"}),
            (("--latest",), {"action": "store_true", "help": "Pick latest matching message"}),
            (("--points",), {"help": "Inline bullet points to address"}),
            (("--points-file",), {"help": "YAML file with reply plan"}),
            (("--tone",), {"default": "friendly", "help": "Reply tone"}),
            (("--signoff",), {"default": "Thanks,", "help": "Sign-off text"}),
            (("--include-summary",), {"action": "store_true", "help": "Include auto-summary"}),
            (("--include-quote",), {"action": "store_true", "help": "Quote original message"}),
            (("--cc",), {"action": "append", "default": [], "help": "CC recipients"}),
            (("--bcc",), {"action": "append", "default": [], "help": "BCC recipients"}),
            (("--subject",), {"help": "Override subject"}),
            (("--draft-out",), {"help": "Write .eml preview path (dry-run)"}),
            (("--apply",), {"action": "store_true", "help": "Send the reply"}),
            (("--send-at",), {"help": "Schedule send at 'YYYY-MM-DD HH:MM'"}),
            (("--send-in",), {"help": "Schedule send in relative time like '2h30m'"}),
            (("--plan",), {"action": "store_true", "help": "Plan-only: print intent and exit"}),
            (("--create-draft",), {"action": "store_true", "help": "Create Gmail Draft (no send)"}),
        ]),
        ("apply-scheduled", "Send scheduled messages that are due", run_messages_apply_scheduled, [
            (("--max",), {"type": int, "default": 10, "help": "Max messages to send"}),
            (("--profile",), {"help": "Only send for specific profile"}),
        ]),
        ("list-attachments", "List attachments in a Gmail message", run_messages_list_attachments, [
            (("--id",), {"required": True, "help": "Message ID"}),
            (("--json",), {"action": "store_true", "help": "Output JSON"}),
        ]),
        ("download-attachment", "Download an attachment from a Gmail message", run_messages_download_attachment, [
            (("--id",), {"required": True, "help": "Message ID"}),
            (("--attachment-id",), {"dest": "attachment_id", "help": "Attachment ID (omit if exactly one attachment)"}),
            (("--filename",), {"help": "Select attachment by filename instead of --attachment-id"}),
            (("--out",), {"help": "Output file path; if a directory, writes <original_filename> inside it"}),
            (("--out-dir",), {"dest": "out_dir", "default": ".", "help": "Output directory (default: .)"}),
        ]),
    ]

    messages_group = app.group("messages", help="Search, get, summarize (Gmail+Outlook); reply (Gmail)")
    for name, help_text, handler, extra in specs:
        # apply-scheduled does not take auth args; all others do
        if name == "apply-scheduled":
            messages_group.register(name, help_text, handler, extra)
        else:
            messages_group.register(name, help_text, handler, list(_AUTH_ARGS) + extra)
    return messages_group
