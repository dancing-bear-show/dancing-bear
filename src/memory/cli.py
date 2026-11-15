"""Memory CLI: inspection, validation, and transport for Claude auto-memory stores.

Stores live at ``~/.claude/projects/<slug>/memory/*.md`` with a ``MEMORY.md``
index. Every subcommand reads them offline; the mutating ones (``validate
--fix``, ``consolidate``, ``import``, ``graduate``, ``backup``) each offer
``--dry-run`` or a read-only mode first.
"""

from __future__ import annotations

from functools import lru_cache
from types import ModuleType

from core.assistant import BaseAssistant
from core.cli_framework import CLIApp

from .commands import (
    backup,
    consolidate,
    export_cmd,
    graduate,
    import_cmd,
    list_cmd,
    search,
    show,
    stores,
    validate,
)
from .meta import META

assistant = BaseAssistant(META.app_id, META.agentic_fallback)

app = CLIApp(
    "memory",
    "Claude auto-memory inspection, validation, and transport",
    add_common_args=False,  # subcommands own --format/--dry-run
)


@lru_cache(maxsize=1)
def _lazy_agentic():
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


_SUBCOMMANDS: tuple[tuple[str, str, ModuleType], ...] = (
    ("list", "List memories in one or more stores", list_cmd),
    ("show", "Show one memory with links resolved", show),
    ("search", "Full-text search across stores", search),
    ("validate", "Run the offline check catalog (exit 0 clean, 1 warn, 2 error)", validate),
    ("stores", "List discovered stores with inferred roles", stores),
    ("consolidate", "Plan/apply zero-loss multi-store consolidation", consolidate),
    ("export", "Export a redaction-scanned memory bundle", export_cmd),
    ("import", "Import a memory bundle into the current store", import_cmd),
    ("backup", "Commit stores into a local-only git repo", backup),
    ("graduate", "Move a memory into the canonical store", graduate),
)

for _name, _help, _module in _SUBCOMMANDS:
    app.add_arguments(_module.ARGUMENTS)
    app.command(_name, help=_help)(_module.run)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the memory CLI."""
    return app.run_with_assistant(
        assistant,
        emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact),
        argv=argv,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
