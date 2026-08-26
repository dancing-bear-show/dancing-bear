"""Cache command group registration for Mail Assistant CLI."""
from __future__ import annotations

from typing import Any

from core.cli_framework import CLIApp

# One argparse argument: the flag names, plus the kwargs forwarded to
# add_argument(). Values are heterogeneous (str, bool, int), hence Any.
ArgSpec = tuple[tuple[str, ...], dict[str, Any]]

_CACHE_ARG: ArgSpec = (("--cache",), {"required": True, "help": "Cache directory root"})


def register_cache_commands(app: CLIApp) -> object:
    """Register all cache subcommands on app and return the cache group."""
    from ..config_cli.commands import (
        run_cache_stats,
        run_cache_clear,
        run_cache_prune,
    )

    # (subcommand, help, handler, args)
    specs: list[tuple[str, str, Any, list[ArgSpec]]] = [
        ("stats", "Show cache stats", run_cache_stats, [
            _CACHE_ARG,
        ]),
        ("clear", "Delete entire cache", run_cache_clear, [
            _CACHE_ARG,
        ]),
        ("prune", "Prune files older than N days", run_cache_prune, [
            _CACHE_ARG,
            (("--days",), {"type": int, "required": True, "help": "Days threshold"}),
        ]),
    ]

    cache_group = app.group("cache", help="Manage local message cache")
    for name, help_text, handler, args in specs:
        cache_group.register(name, help_text, handler, args)
    return cache_group
