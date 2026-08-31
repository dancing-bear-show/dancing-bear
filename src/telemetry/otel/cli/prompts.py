"""prompts subcommand — per-prompt token spend, cost, and tool usage."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.cli_output import emit_rows
from telemetry.otel.analytics.prompts import get_prompt_metrics
from telemetry.otel.cost_models import PromptMetrics
from telemetry.otel.reader import OTLPDataDir


def main(argv: list[str] | None = None) -> int:
    """Show per-prompt metrics correlated by prompt.id."""
    parser = argparse.ArgumentParser(
        prog="telemetry prompts",
        description="Per-prompt token spend, cost, and tool usage",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        help="Filter to a specific session",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Time window (e.g., 7d, 24h)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max prompts to display (default: 20)",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        help="Override default data directory",
    )

    args = parser.parse_args(argv)

    data_dir: OTLPDataDir | None = None
    if args.data_dir:
        data_dir = OTLPDataDir(path=Path(args.data_dir))

    try:
        metrics = get_prompt_metrics(
            data_dir=data_dir,
            since=args.since,
            session_id=args.session_id,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not metrics:
        print("No prompt metrics found")
        return 0

    if args.limit > 0:
        metrics = metrics[: args.limit]

    if args.format == "json":
        _output_json(metrics)
    else:
        _output_table(metrics)

    return 0


def _output_table(metrics: list[PromptMetrics]) -> None:
    """Render prompt metrics as a formatted table."""
    print("Per-Prompt Metrics")
    print("=" * 100)
    print(
        f"  {'Prompt ID':<14} {'Session':<12} {'API':<5} "
        f"{'Input':<10} {'Output':<10} {'Cost':<10} "
        f"{'Tools':<6} {'Fail':<5} {'Duration':<10}"
    )
    print(
        f"  {'-' * 14} {'-' * 12} {'-' * 5} "
        f"{'-' * 10} {'-' * 10} {'-' * 10} "
        f"{'-' * 6} {'-' * 5} {'-' * 10}"
    )

    total_cost = 0.0
    total_input = 0
    total_output = 0
    total_api = 0
    total_tools = 0

    for pm in metrics:
        pid = _truncate(pm.prompt_id, 14)
        sid = _truncate(pm.session_id, 12)
        dur = _format_duration_ms(pm.duration_ms)

        print(
            f"  {pid:<14} {sid:<12} {pm.api_calls:<5} "
            f"{pm.input_tokens:<10,} {pm.output_tokens:<10,} "
            f"${pm.cost:<9.4f} "
            f"{pm.tool_calls:<6} {pm.tool_failures:<5} {dur:<10}"
        )

        total_cost += pm.cost
        total_input += pm.input_tokens
        total_output += pm.output_tokens
        total_api += pm.api_calls
        total_tools += pm.tool_calls

    print(
        f"  {'-' * 14} {'-' * 12} {'-' * 5} "
        f"{'-' * 10} {'-' * 10} {'-' * 10} "
        f"{'-' * 6} {'-' * 5} {'-' * 10}"
    )
    print(
        f"  {'Total':<14} {'':<12} {total_api:<5} "
        f"{total_input:<10,} {total_output:<10,} "
        f"${total_cost:<9.4f} "
        f"{total_tools:<6}"
    )
    print(f"\n  Showing {len(metrics)} prompt(s)")


def _output_json(metrics: list[PromptMetrics]) -> None:
    """Render prompt metrics as JSON."""
    output: list[dict[str, object]] = [
        {
            "prompt_id": pm.prompt_id,
            "session_id": pm.session_id,
            "timestamp": pm.timestamp,
            "prompt_length": pm.prompt_length,
            "api_calls": pm.api_calls,
            "input_tokens": pm.input_tokens,
            "output_tokens": pm.output_tokens,
            "cost": round(pm.cost, 6),
            "tool_calls": pm.tool_calls,
            "tool_failures": pm.tool_failures,
            "duration_ms": pm.duration_ms,
        }
        for pm in metrics
    ]
    emit_rows(output, "json")


def _truncate(s: str, max_len: int) -> str:
    """Truncate a string with ellipsis if too long."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _format_duration_ms(ms: float) -> str:
    """Format milliseconds to a human-readable duration."""
    if ms <= 0:
        return "-"
    if ms < 1000:
        return f"{int(ms)}ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    return f"{minutes:.1f}m"
