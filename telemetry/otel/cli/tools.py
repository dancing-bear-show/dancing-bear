"""tools subcommand — tool error analysis."""

from __future__ import annotations

import argparse

from core.cli_output import emit_rows
from telemetry.otel.analytics.tools import get_tool_summaries
from telemetry.otel.cli._format_helpers import (
    add_data_dir_argument,
    add_format_argument,
    add_since_argument,
    resolve_data_dir,
    resolve_since,
)
from telemetry.otel.cost_models import ToolErrorSummary


def main(argv: list[str] | None = None) -> int:
    """Analyze tool usage and error rates."""
    parser = argparse.ArgumentParser(
        prog="telemetry tools",
        description="Analyze tool usage and error rates",
    )
    add_since_argument(parser)
    parser.add_argument(
        "--sort",
        choices=["failure-rate", "calls", "failures", "name"],
        default="failure-rate",
        help="Sort by (default: failure-rate)",
    )
    add_format_argument(parser, formats=["table", "json"], default="table")
    add_data_dir_argument(parser)

    args = parser.parse_args(argv)
    data_dir = resolve_data_dir(args)
    since, err = resolve_since(args)
    if err is not None:
        return err

    summaries = get_tool_summaries(data_dir=data_dir, since=since)
    summaries = _sort_summaries(summaries, args.sort)

    headers = ["tool_name", "total_calls", "failures", "failure_rate", "avg_duration_ms", "sessions_affected"]
    rows = [
        {
            "tool_name": s.tool_name,
            "total_calls": s.total_calls,
            "failures": s.failures,
            "failure_rate": round(s.failure_rate, 4),
            "avg_duration_ms": round(s.avg_duration_ms, 1),
            "sessions_affected": s.sessions_affected,
        }
        for s in summaries
    ]
    return emit_rows(rows, args.format, headers=headers, empty_msg="No tool usage data found.")


def _sort_summaries(
    summaries: list[ToolErrorSummary], sort_key: str
) -> list[ToolErrorSummary]:
    """Sort tool summaries by the specified key."""
    if sort_key == "calls":
        return sorted(summaries, key=lambda s: s.total_calls, reverse=True)
    if sort_key == "failures":
        return sorted(summaries, key=lambda s: s.failures, reverse=True)
    if sort_key == "name":
        return sorted(summaries, key=lambda s: s.tool_name)
    return sorted(
        summaries,
        key=lambda s: (s.failure_rate, s.total_calls),
        reverse=True,
    )
