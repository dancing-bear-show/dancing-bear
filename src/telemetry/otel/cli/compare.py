"""compare subcommand — side-by-side session comparison."""

from __future__ import annotations

import argparse
from pathlib import Path

from core.cli_output import OutputWriter, emit_one
from telemetry.otel.analytics.compare import compare_sessions
from telemetry.otel.cli._format_helpers import format_duration, format_timestamp
from telemetry.otel.cost_models import SessionComparison
from telemetry.otel.reader import OTLPDataDir


def main(argv: list[str] | None = None) -> int:
    """Compare two sessions side-by-side."""
    parser = argparse.ArgumentParser(
        prog="telemetry compare",
        description="Compare two sessions side-by-side",
    )
    parser.add_argument(
        "session_a",
        type=str,
        help="First session ID",
    )
    parser.add_argument(
        "session_b",
        type=str,
        help="Second session ID",
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

    if args.data_dir:
        data_dir = OTLPDataDir(path=Path(args.data_dir))
    else:
        data_dir = OTLPDataDir.from_env()

    writer = OutputWriter()
    try:
        comparison = compare_sessions(
            args.session_a, args.session_b, data_dir=data_dir
        )
    except ValueError as e:
        writer.print_error(str(e))
        return 1

    if args.format == "json":
        _output_json(comparison)
    else:
        _output_table(comparison, writer)

    return 0


def _format_delta(value: float | int, prefix: str = "", suffix: str = "") -> str:
    """Format a delta value with +/- prefix."""
    sign = "+" if value > 0 else ""
    if isinstance(value, float):
        return f"{sign}{value:.4f}{suffix}"
    return f"{sign}{prefix}{value:,}{suffix}"


def _output_table(comp: SessionComparison, writer: OutputWriter | None = None) -> None:
    """Render comparison as a formatted table."""
    w = writer or OutputWriter()
    a = comp.session_a
    b = comp.session_b

    def _sid(sid: str) -> str:
        if len(sid) > 20:
            return sid[:8] + "..." + sid[-8:]
        return sid

    w.print("Session Comparison")
    w.print("=" * 72)
    w.print(f"  {'Metric':<24} {'Session A':<20} {'Session B':<20} {'Delta':<12}")
    w.print(f"  {'-' * 24} {'-' * 20} {'-' * 20} {'-' * 12}")

    w.print(f"  {'ID':<24} {_sid(a.session_id):<20} {_sid(b.session_id):<20}")

    w.print(
        f"  {'First seen':<24} "
        f"{format_timestamp(a.first_seen):<20} "
        f"{format_timestamp(b.first_seen):<20}"
    )
    w.print(
        f"  {'Last seen':<24} "
        f"{format_timestamp(a.last_seen):<20} "
        f"{format_timestamp(b.last_seen):<20}"
    )

    dur_a = format_duration(a.duration_minutes)
    dur_b = format_duration(b.duration_minutes)
    dur_delta = ""
    if comp.duration_delta is not None:
        mins = comp.duration_delta.total_seconds() / 60
        dur_delta = _format_delta(int(mins), suffix="m")
    w.print(f"  {'Duration':<24} {dur_a:<20} {dur_b:<20} {dur_delta:<12}")

    cost_delta = _format_delta(comp.cost_delta, prefix="$")
    w.print(
        f"  {'Cost':<24} "
        f"${a.cost:<19.4f} "
        f"${b.cost:<19.4f} "
        f"{cost_delta:<12}"
    )

    tok_delta = _format_delta(comp.token_delta)
    w.print(
        f"  {'Billable tokens':<24} "
        f"{a.billable_tokens:<20,} "
        f"{b.billable_tokens:<20,} "
        f"{tok_delta:<12}"
    )

    calls_delta = _format_delta(b.api_calls - a.api_calls)
    w.print(
        f"  {'API calls':<24} "
        f"{a.api_calls:<20,} "
        f"{b.api_calls:<20,} "
        f"{calls_delta:<12}"
    )

    err_delta = _format_delta(comp.error_delta)
    errors_a = a.perf.error_count if a.perf else 0
    errors_b = b.perf.error_count if b.perf else 0
    w.print(
        f"  {'Errors':<24} "
        f"{errors_a:<20} "
        f"{errors_b:<20} "
        f"{err_delta:<12}"
    )

    w.print("=" * 72)


def _output_json(comp: SessionComparison) -> None:
    """Render comparison as JSON."""
    a = comp.session_a
    b = comp.session_b

    output = {
        "session_a": {
            "session_id": a.session_id,
            "cost": round(a.cost, 4),
            "billable_tokens": a.billable_tokens,
            "api_calls": a.api_calls,
            "duration_minutes": (
                round(a.duration_minutes, 1)
                if a.duration_minutes is not None
                else None
            ),
            "errors": a.perf.error_count if a.perf else 0,
        },
        "session_b": {
            "session_id": b.session_id,
            "cost": round(b.cost, 4),
            "billable_tokens": b.billable_tokens,
            "api_calls": b.api_calls,
            "duration_minutes": (
                round(b.duration_minutes, 1)
                if b.duration_minutes is not None
                else None
            ),
            "errors": b.perf.error_count if b.perf else 0,
        },
        "deltas": {
            "cost": round(comp.cost_delta, 4),
            "billable_tokens": comp.token_delta,
            "duration_minutes": (
                round(comp.duration_delta.total_seconds() / 60, 1)
                if comp.duration_delta is not None
                else None
            ),
            "errors": comp.error_delta,
        },
    }
    emit_one(output, "json")
