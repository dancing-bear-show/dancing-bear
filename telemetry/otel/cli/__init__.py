"""OTEL telemetry CLI dispatcher.

Aggregates OTEL telemetry subcommands under a single entry point.
"""

from __future__ import annotations

import importlib
import sys

_SUBCOMMANDS: dict[str, str] = {
    "health": "telemetry.otel.cli.health",
    "size": "telemetry.otel.cli.size",
    "inspect": "telemetry.otel.cli.inspect",
    "query": "telemetry.otel.cli.query",
    "stats": "telemetry.otel.cli.stats",
    "cost": "telemetry.otel.cli.cost",
    "sessions": "telemetry.otel.cli.sessions",
    "prune": "telemetry.otel.cli.prune",
    "clear": "telemetry.otel.cli.clear",
    "events-search": "telemetry.otel.cli.events_search",
    "compare": "telemetry.otel.cli.compare",
    "tools": "telemetry.otel.cli.tools",
    "prompts": "telemetry.otel.cli.prompts",
    "anomalies": "telemetry.otel.cli.anomalies",
    "clusters": "telemetry.otel.cli.clusters",
    "otel-summary": "telemetry.otel.cli.otel_summary",
    "workflow-cost": "telemetry.otel.cli.workflow_cost",
}

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
    col_width = max(len(k) for k in _SUBCOMMANDS) + 2
    descriptions = {
        "health": "Check OTEL telemetry system health",
        "size": "Show telemetry storage usage",
        "inspect": "Inspect raw telemetry records",
        "query": "Query metrics by pattern",
        "stats": "Show telemetry statistics",
        "cost": "Analyze telemetry costs",
        "sessions": "List sessions with usage and performance",
        "prune": "Prune old telemetry data",
        "clear": "Clear telemetry data files",
        "events-search": "Search events by pattern",
        "compare": "Compare two sessions side-by-side",
        "tools": "Analyze tool usage and error rates",
        "prompts": "Per-prompt token spend and tool usage",
        "anomalies": "Detect anomalous sessions (z-score)",
        "clusters": "Cluster sessions by cost/tokens",
        "otel-summary": "Aggregated OTEL statistics dashboard",
        "workflow-cost": "Per-stage cost breakdown for workflow runs",
    }
    for name in sorted(_SUBCOMMANDS):
        desc = descriptions.get(name, "")
        print(f"  {name:<{col_width}}{desc}")
    print()
    print("Aliases: metrics=query, events=inspect, du=size, rm=prune, delete=clear")
    print()
    print("Use 'telemetry otel <subcommand> --help' for subcommand options.")
