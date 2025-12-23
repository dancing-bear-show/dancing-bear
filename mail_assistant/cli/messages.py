from __future__ import annotations


def register(subparsers, add_gmail_args, *, f_search, f_summarize, f_reply, f_apply_scheduled):
    """Register messages subcommands."""
    p_msgs = subparsers.add_parser("messages", help="Search, summarize, and reply to messages (Gmail)")
    add_gmail_args(p_msgs)
    sub_msgs = p_msgs.add_subparsers(dest="messages_cmd")

    # messages search
    p_msgs_search = sub_msgs.add_parser("search", help="Search for messages and list candidates")
    p_msgs_search.add_argument("--query", type=str, default="", help="Gmail search query (e.g., from:foo@example.com)")
    p_msgs_search.add_argument("--days", type=int, help="Restrict to last N days")
    p_msgs_search.add_argument("--only-inbox", action="store_true", help="Restrict search to inbox")
    p_msgs_search.add_argument("--max-results", type=int, default=5)
    p_msgs_search.add_argument("--json", action="store_true", help="Output JSON instead of table")
    p_msgs_search.set_defaults(func=f_search)

    # messages summarize
    p_msgs_sum = sub_msgs.add_parser("summarize", help="Summarize a message's content")
    p_msgs_sum.add_argument("--id", type=str, help="Message ID to summarize")
    p_msgs_sum.add_argument("--query", type=str, help="Fallback query to pick latest message if id not given")
    p_msgs_sum.add_argument("--days", type=int, help="Restrict query to last N days")
    p_msgs_sum.add_argument("--only-inbox", action="store_true")
    p_msgs_sum.add_argument("--latest", action="store_true", help="Pick latest matching message when using --query")
    p_msgs_sum.add_argument("--out", type=str, help="Write summary to this file (else stdout)")
    p_msgs_sum.add_argument("--max-words", type=int, default=120)
    p_msgs_sum.set_defaults(func=f_summarize)

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
    p_msgs_reply.set_defaults(func=f_reply)

    # messages apply-scheduled
    p_msgs_apply = sub_msgs.add_parser("apply-scheduled", help="Send any scheduled messages that are due now")
    p_msgs_apply.add_argument("--max", type=int, default=10, help="Max messages to send in one run")
    p_msgs_apply.add_argument("--profile", type=str, help="Only send for a specific profile")
    p_msgs_apply.set_defaults(func=f_apply_scheduled)
