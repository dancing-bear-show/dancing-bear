"""WhatsApp CLI.

Read-only helpers to search the local macOS WhatsApp database
(ChatStorage.sqlite). All operations are offline with plan-first flags.
"""

from __future__ import annotations

import argparse
import sys
from functools import lru_cache
from typing import Optional

from core.assistant import BaseAssistant

from . import search as _wa
from .meta import APP_ID, PURPOSE


assistant = BaseAssistant(
    APP_ID,
    f"agentic: {APP_ID}\npurpose: {PURPOSE}",
)


@lru_cache(maxsize=1)
def _lazy_agentic():
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WhatsApp Assistant CLI (local-only)")
    assistant.add_agentic_flags(parser)
    sub = parser.add_subparsers(dest="command")

    p_search = sub.add_parser("search", help="Search local WhatsApp ChatStorage.sqlite for text matches")
    p_search.add_argument("--db", help="Path to ChatStorage.sqlite (defaults to macOS group container)")
    p_search.add_argument("--contains", action="append", default=[], help="Text to search for (repeatable; case-insensitive)")
    p_search.add_argument("--any", dest="match_any", action="store_true", help="Match ANY of the --contains terms (default)")
    p_search.add_argument("--all", dest="match_all", action="store_true", help="Match ALL of the --contains terms")
    p_search.add_argument("--contact", help="Filter by contact display name (substring match, case-insensitive)")
    g = p_search.add_mutually_exclusive_group()
    g.add_argument("--from-me", dest="from_me", action="store_true", help="Only messages sent by me")
    g.add_argument("--from-them", dest="from_them", action="store_true", help="Only messages received (not from me)")
    p_search.add_argument("--since-days", type=int, help="Restrict to messages in the last N days")
    p_search.add_argument("--limit", type=int, default=50, help="Max rows to return (default 50)")
    p_search.add_argument("--json", action="store_true", help="Output JSON instead of text table")
    p_search.set_defaults(func=cmd_search)

    return parser


def cmd_search(args: argparse.Namespace) -> int:
    try:
        return _wa.run_search_cli(args)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        print(
            "Hint: use --db to specify the path. Default macOS path is:",
            _wa.default_db_path(),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:  # pragma: no cover - defensive
        print(f"WhatsApp search error: {exc}", file=sys.stderr)
        return 1


def main(argv: Optional[list[str]] = None) -> int:
    # Install conservative secret shielding for stdout/stderr (env-toggled)
    try:
        from mail_assistant.utils.secrets import install_output_masking_from_env as _install_mask  # reuse module

        _install_mask()
    except Exception:  # pragma: no cover - best effort
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    agentic_result = assistant.maybe_emit_agentic(
        args, emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact)
    )
    if agentic_result is not None:
        return agentic_result
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
