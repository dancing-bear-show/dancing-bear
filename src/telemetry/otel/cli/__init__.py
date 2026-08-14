"""OTEL telemetry CLI dispatcher.

Aggregates OTEL telemetry subcommands under a single entry point.
"""

from __future__ import annotations

import importlib
import sys

# Single registry: subcommand -> (module path, help description). Keeping the
# module and its description in one entry means a new subcommand cannot be
# registered without also giving it help text -- the previous parallel dicts
# let one drift from the other, silently printing a blank description.
_REGISTRY: dict[str, tuple[str, str]] = {
    "health": ("telemetry.otel.cli.health", "Check OTEL telemetry system health"),
    "size": ("telemetry.otel.cli.size", "Show telemetry storage usage"),
    "inspect": ("telemetry.otel.cli.inspect", "Inspect raw telemetry records"),
    "query": ("telemetry.otel.cli.query", "Query metrics by pattern"),
    "stats": ("telemetry.otel.cli.stats", "Show telemetry statistics"),
    "cost": ("telemetry.otel.cli.cost", "Analyze telemetry costs"),
    "sessions": ("telemetry.otel.cli.sessions", "List sessions with usage and performance"),
    "prune": ("telemetry.otel.cli.prune", "Prune old telemetry data"),
    "clear": ("telemetry.otel.cli.clear", "Clear telemetry data files"),
    "events-search": ("telemetry.otel.cli.events_search", "Search events by pattern"),
    "compare": ("telemetry.otel.cli.compare", "Compare two sessions side-by-side"),
    "tools": ("telemetry.otel.cli.tools", "Analyze tool usage and error rates"),
    "prompts": ("telemetry.otel.cli.prompts", "Per-prompt token spend and tool usage"),
    "anomalies": ("telemetry.otel.cli.anomalies", "Detect anomalous sessions (z-score)"),
    "clusters": ("telemetry.otel.cli.clusters", "Cluster sessions by cost/tokens"),
    "otel-summary": ("telemetry.otel.cli.otel_summary", "Aggregated OTEL statistics dashboard"),
    "workflow-cost": ("telemetry.otel.cli.workflow_cost", "Per-stage cost breakdown for workflow runs"),
}

# Derived module lookup, kept as the dispatch surface.
_SUBCOMMANDS: dict[str, str] = {name: module for name, (module, _) in _REGISTRY.items()}

_ALIASES: dict[str, str] = {
    "metrics": "query",
    "events": "inspect",
    "du": "size",
    "rm": "prune",
    "delete": "clear",
}

_SKIP_INFRA_ARGS = frozenset({
    "--help", "-h", "help", "health",
    "--agentic", "--agentic-format", "--agentic-compact",
})


def _should_skip_infrastructure_check(argv: list[str]) -> bool:
    """Return True if the command should skip the infrastructure health check."""
    return any(
        arg in _SKIP_INFRA_ARGS or arg.startswith("--agentic")
        for arg in argv
    )


def _split_argv(argv: list[str]) -> tuple[str | None, list[str], bool]:
    """Split argv into (subcommand, remaining_args, show_help).

    Extracts the first non-flag positional as the subcommand without
    consuming flags that belong to the subcommand.
    """
    subcmd: str | None = None
    remaining: list[str] = []
    show_help = False
    for arg in argv:
        if arg in ("--help", "-h") and subcmd is None:
            show_help = True
        elif not arg.startswith("-") and subcmd is None:
            subcmd = arg
        else:
            remaining.append(arg)
    return subcmd, remaining, show_help


def _check_infrastructure() -> int | None:
    """Run the infrastructure check. Returns an exit code on failure, None on success."""
    from telemetry.otel.health import require_otel_infrastructure
    require_otel_infrastructure()
    return None


def main(argv: list[str] | None = None) -> int:
    """Dispatch OTEL telemetry subcommands."""
    if argv is None:
        argv = sys.argv[1:]

    subcmd, remaining, show_help = _split_argv(argv)

    if show_help and subcmd is None:
        _print_help()
        return 0

    if subcmd is None:
        _print_help()
        return 0

    # Resolve alias
    subcmd = _ALIASES.get(subcmd, subcmd)

    if subcmd not in _SUBCOMMANDS:
        print(f"telemetry otel: unknown subcommand {subcmd!r}", file=sys.stderr)
        print(f"Available: {', '.join(sorted(_SUBCOMMANDS))}", file=sys.stderr)
        return 2

    if not _should_skip_infrastructure_check(argv):
        try:
            _check_infrastructure()
        except SystemExit as exc:  # nosec B110 - NOSONAR - translate infra check SystemExit to int return code
            return int(exc.code) if exc.code is not None else 1

    module = importlib.import_module(_SUBCOMMANDS[subcmd])
    return module.main(remaining)


def _print_help() -> None:
    """Print the top-level help message."""
    print("usage: telemetry otel <subcommand> [options]")
    print()
    print("Query and manage local OTEL telemetry data (~/.config/otel/)")
    print()
    print("Subcommands:")
    col_width = max(len(k) for k in _REGISTRY) + 2
    for name, (_, desc) in sorted(_REGISTRY.items()):
        print(f"  {name:<{col_width}}{desc}")
    print()
    print("Aliases: metrics=query, events=inspect, du=size, rm=prune, delete=clear")
    print()
    print("Use 'telemetry otel <subcommand> --help' for subcommand options.")
