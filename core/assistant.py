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
        parser.add_argument(
            "--agentic",
            action="store_true",
            help="Emit compact repo context for LLM agents and exit",
        )
        parser.add_argument(
            "--agentic-format",
            choices=["text", "yaml"],
            default="text",
            help="Preferred output format for --agentic capsule (default text)",
        )
        parser.add_argument(
            "--agentic-compact",
            action="store_true",
            help="Emit a more compact agentic capsule when supported",
        )
        return parser

    def maybe_emit_agentic(
        self,
        args: Any,
        emit_func: Callable[..., int],
        fmt_param: str = "agentic_format",
        compact_param: str = "agentic_compact",
    ) -> Optional[int]:
        if not getattr(args, "agentic", False):
            return None
        fmt = getattr(args, fmt_param, "text")
        compact = bool(getattr(args, compact_param, False))
        try:
            return emit_func(fmt, compact)
        except TypeError:
            return emit_func()
        except Exception:
            print(self.fallback_banner)
            return 0
