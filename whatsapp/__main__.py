"""WhatsApp CLI.

Read-only helpers to search the local macOS WhatsApp database
(ChatStorage.sqlite). All operations are offline with plan-first flags.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from typing import Optional

from core.assistant import BaseAssistant
from core.cli_framework import CLIApp

from .meta import APP_ID, PURPOSE
from .pipeline import SearchProcessor, SearchProducer, SearchRequest, SearchRequestConsumer
from .search import default_db_path


assistant = BaseAssistant(
    APP_ID,
    f"agentic: {APP_ID}\npurpose: {PURPOSE}",
)

app = CLIApp(
    "whatsapp",
    "WhatsApp Assistant CLI (local-only)",
    add_common_args=False,  # We use our own args pattern
)


@lru_cache(maxsize=1)
def _lazy_agentic():
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


# Note: @argument decorators must come BEFORE @command (decorators apply bottom-up)
@app.command("search", help="Search local WhatsApp ChatStorage.sqlite for text matches")
@app.argument("--db", help="Path to ChatStorage.sqlite (defaults to macOS group container)")
@app.argument("--contains", action="append", default=[], help="Text to search for (repeatable; case-insensitive)")
@app.argument("--any", dest="match_any", action="store_true", help="Match ANY of the --contains terms (default)")
@app.argument("--all", dest="match_all", action="store_true", help="Match ALL of the --contains terms")
@app.argument("--contact", help="Filter by contact display name (substring match, case-insensitive)")
@app.argument("--from-me", dest="from_me", action="store_true", help="Only messages sent by me")
@app.argument("--from-them", dest="from_them", action="store_true", help="Only messages received (not from me)")
@app.argument("--since-days", type=int, help="Restrict to messages in the last N days")
@app.argument("--limit", type=int, default=50, help="Max rows to return (default 50)")
@app.argument("--json", action="store_true", help="Output JSON instead of text table")
def cmd_search(args) -> int:
    """Execute the search command."""
    # Handle mutual exclusivity of --from-me and --from-them
    if getattr(args, "from_me", False) and getattr(args, "from_them", False):
        print("Error: --from-me and --from-them are mutually exclusive", file=sys.stderr)
        return 1

    # Determine from_me filter
    from_me_filter: Optional[bool] = None
    if getattr(args, "from_me", False):
        from_me_filter = True
    elif getattr(args, "from_them", False):
        from_me_filter = False

    request = SearchRequest(
        db_path=getattr(args, "db", None),
        contains=getattr(args, "contains", None) or [],
        match_all=bool(getattr(args, "match_all", False) and not getattr(args, "match_any", False)),
        contact=getattr(args, "contact", None),
        from_me=from_me_filter,
        since_days=getattr(args, "since_days", None),
        limit=max(1, int(getattr(args, "limit", 50) or 50)),
        emit_json=getattr(args, "json", False),
    )

    envelope = SearchProcessor().process(SearchRequestConsumer(request).consume())
    SearchProducer().produce(envelope)

    if envelope.ok():
        return 0
    # Handle errors from envelope
    diag = envelope.diagnostics or {}
    error_msg = diag.get("error", "Unknown error")
    print(error_msg, file=sys.stderr)
    if diag.get("hint") == "db_not_found":
        print(
            "Hint: use --db to specify the path. Default macOS path is:",
            default_db_path(),
            file=sys.stderr,
        )
    return int(diag.get("code", 1))


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for the WhatsApp CLI."""
    # Install conservative secret shielding for stdout/stderr (env-toggled)
    try:
        from mail.utils.secrets import install_output_masking_from_env as _install_mask

        _install_mask()
    except Exception:  # nosec B110 - best-effort masking, non-critical  # pragma: no cover
        pass  # optional module may not exist

    # Build parser and add agentic flags
    parser = app.build_parser()
    assistant.add_agentic_flags(parser)

    args = parser.parse_args(argv)

    # Handle agentic output if requested
    agentic_result = assistant.maybe_emit_agentic(
        args, emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact)
    )
    if agentic_result is not None:
        return agentic_result

    # Get the command function
    cmd_func = getattr(args, "_cmd_func", None)
    if cmd_func is None:
        parser.print_help()
        return 0

    return int(cmd_func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
