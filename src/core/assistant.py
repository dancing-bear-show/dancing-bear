"""Shared assistant utilities (agentic flags/output)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class BaseAssistant:
    """Lightweight helper to add agentic flags and emit capsules."""

    app_id: str
    fallback_banner: str

    def add_agentic_flags(self, parser) -> Any:
        # Guard against duplicate registration (idempotent)
        existing = {opt for act in parser._actions for opt in act.option_strings}
        if "--agentic" not in existing:
            parser.add_argument(
                "--agentic",
                action="store_true",
                help="Emit compact repo context for LLM agents and exit",
            )
        if "--agentic-format" not in existing:
            parser.add_argument(
                "--agentic-format",
                choices=["text", "yaml", "json"],
                default="text",
                help="Output format for --agentic capsule: text/yaml (hand-authored) or json (auto-schema)",
            )
        if "--agentic-compact" not in existing:
            parser.add_argument(
                "--agentic-compact",
                action="store_true",
                help="Emit a more compact agentic capsule when supported",
            )
        if "--agentic-domain" not in existing:
            parser.add_argument(
                "--agentic-domain",
                metavar="PREFIX",
                help="Filter auto-schema to subcommands matching this prefix (json format only)",
            )
        return parser

    def maybe_emit_agentic(
        self,
        args: Any,
        emit_func: Callable[..., int],
        fmt_param: str = "agentic_format",
        compact_param: str = "agentic_compact",
        parser: Any = None,
    ) -> Optional[int]:
        if not getattr(args, "agentic", False):
            return None
        fmt = getattr(args, fmt_param, "text")
        compact = bool(getattr(args, compact_param, False))

        # Auto-schema mode: --agentic-format json uses parser introspection
        if fmt == "json" and parser is not None:
            from .agentic_schema import build_schema_json
            import json as _json
            domain = getattr(args, "agentic_domain", None)
            schema = build_schema_json(parser, compact=compact, domain=domain)
            print(_json.dumps(schema, indent=2, default=str))
            return 0

        try:
            return emit_func(fmt, compact)
        except TypeError:
            return emit_func()
        except Exception:  # nosec B110 - fallback banner is safe, capsule emission is best-effort
            print(self.fallback_banner)
            return 0
