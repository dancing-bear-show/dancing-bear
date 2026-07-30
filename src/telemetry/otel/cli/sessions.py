"""sessions subcommand — list sessions with token usage and performance."""

from __future__ import annotations

import argparse
from pathlib import Path

from telemetry.otel.analytics.cost import get_all_costs
from telemetry.otel.cli._format_helpers import (
    format_validation_error,
)
from telemetry.otel.cost_models import SessionCost
from telemetry.otel.reader import OTLPDataDir
from telemetry.otel.utils import parse_time_window

# Re-exports from sibling modules
from telemetry.otel.cli.sessions_output import (  # noqa: F401
    _format_model_mix,
    _output_json,
    _output_table,
    _print_error_codes_standalone,
    _print_perf_details,
    _print_perf_summary,
    _print_session,
    _print_session_header,
    _session_to_json,
)
from telemetry.otel.cli.sessions_timeline import (  # noqa: F401
    _event_to_timeline_entry,
    _extract_api_request_detail,
    _extract_event_detail,
    _extract_tool_result_detail,
    _format_api_request_detail,
    _format_timeline_entry,
    _output_timeline,
    _sum_token_attrs,
)


def _has_errors(session: SessionCost) -> bool:
    """Check if session has any errors or tool failures."""
    if not session.perf:
        return False
    return session.perf.error_count > 0 or session.perf.tool_failures > 0


def _filter_sessions(
    sessions: list[SessionCost],
    errors_only: bool,
    limit: int,
    session_id: str | None = None,
) -> list[SessionCost]:
    """Apply common filters to sessions list."""
    if session_id:
        sessions = [s for s in sessions if s.session_id == session_id]

    if errors_only:
        sessions = [s for s in sessions if _has_errors(s)]

    if limit > 0:
        sessions = sessions[:limit]

    return sessions


def main(argv: list[str] | None = None) -> int:
    """List sessions with token usage, cost, and performance metrics."""
    parser = argparse.ArgumentParser(
        prog="telemetry sessions",
        description="List sessions with token usage, cost, performance, and errors",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Time range (e.g., '1h', '24h', '7d')",
    )
    parser.add_argument(
        "--sort",
        choices=["cost", "time", "tokens", "errors", "health"],
        default="time",
        help="Sort by cost, time, tokens, errors, or health (default: time)",
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
    parser.add_argument(
        "--perf",
        action="store_true",
        help="Show performance details (latency, model mix, tools)",
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help="Show only sessions with API errors or tool failures",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Show only top N sessions (0 = all)",
    )
    parser.add_argument(
        "--error-codes",
        action="store_true",
        help="Show HTTP error status code breakdown per session",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Show health grade and score per session",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        help="Filter to a specific session ID",
    )
    parser.add_argument(
        "--timeline",
        action="store_true",
        help="Show chronological event timeline (requires --session-id)",
    )

    args = parser.parse_args(argv)

    if args.timeline and not args.session_id:
        return format_validation_error("--timeline", "requires --session-id")

    if args.data_dir:
        data_dir = OTLPDataDir(path=Path(args.data_dir))
    else:
        data_dir = OTLPDataDir.from_env()

    try:
        since = parse_time_window(args.since)
    except ValueError as e:
        return format_validation_error("--since", f"invalid value: {e}")

    if args.timeline:
        _output_timeline(data_dir, args.session_id, since)
        return 0

    metrics = get_all_costs(data_dir=data_dir, since=since)

    if args.format == "json":
        _output_json(
            metrics, args.sort, args.errors_only, args.limit,
            args.error_codes, args.health, args.session_id,
        )
    else:
        _output_table(
            metrics, args.sort, args.perf, args.errors_only, args.limit,
            args.error_codes, args.health, args.session_id,
        )

    return 0
