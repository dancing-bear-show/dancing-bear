"""Shared formatting helpers for telemetry CLI subcommands."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, UTC
from pathlib import Path

from telemetry.otel.analytics.health_score import calculate_health_score
from telemetry.otel.reader import OTLPDataDir
from telemetry.otel.utils import parse_time_window


def get_work_dir() -> Path:
    """Return the workflow output directory (repo root / out)."""
    return Path(__file__).resolve().parents[4] / "out"


def format_validation_error(flag: str, msg: str) -> int:
    """Print a validation error to stderr and return exit code 2."""
    print(f"Error: {flag}: {msg}", file=sys.stderr, flush=True)
    return 2


def add_format_argument(
    parser: argparse.ArgumentParser,
    formats: list[str] | None = None,
    default: str = "table",
) -> None:
    """Add a --format argument to a parser."""
    choices = formats or ["table", "json"]
    parser.add_argument(
        "--format",
        choices=choices,
        default=default,
        help=f"Output format (default: {default})",
    )


def truncate_sid(sid: str, max_len: int = 20) -> str:
    """Truncate long session IDs for table display."""
    if len(sid) > max_len:
        return sid[:8] + "..." + sid[-8:]
    return sid


def add_data_dir_argument(parser: argparse.ArgumentParser) -> None:
    """Add the common --data-dir argument."""
    parser.add_argument(
        "--data-dir",
        type=str,
        help="Override default data directory",
    )


def add_since_argument(parser: argparse.ArgumentParser) -> None:
    """Add the common --since time-range argument."""
    parser.add_argument(
        "--since",
        type=str,
        help="Time range (e.g., '1h', '24h', '7d')",
    )


def resolve_data_dir(
    args: argparse.Namespace, *, allow_none: bool = False
) -> OTLPDataDir | None:
    """Build OTLPDataDir from parsed args.

    When *allow_none* is True, returns None if --data-dir was not given
    (used by anomalies/clusters which pass None to their analytics functions).
    Otherwise falls back to ``OTLPDataDir.from_env()``.
    """
    if args.data_dir:
        return OTLPDataDir(path=Path(args.data_dir))
    if allow_none:
        return None
    return OTLPDataDir.from_env()


def resolve_since(args: argparse.Namespace) -> tuple[datetime | None, int | None]:
    """Parse --since from args.

    Returns ``(parsed_datetime, None)`` on success, or
    ``(None, exit_code)`` on validation failure.
    """
    try:
        return parse_time_window(args.since), None
    except ValueError as e:
        rc = format_validation_error("--since", str(e))
        return None, rc


def format_timestamp(dt: datetime | None) -> str:
    """Format a datetime for display."""
    if dt is None:
        return "unknown"
    return dt.strftime("%Y-%m-%d %H:%M")


def format_duration(minutes: float | None) -> str:
    """Format duration in minutes to human-readable string."""
    if minutes is None:
        return ""
    if minutes < 1:
        return "<1m"
    if minutes < 60:
        return f"{int(minutes)}m"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h{mins}m"


def sort_sessions(sessions: list, sort_key: str) -> list:
    """Sort sessions by the specified key.

    Supports: cost, tokens, errors, health, time (default).
    """
    if sort_key == "cost":
        return sorted(sessions, key=lambda s: s.cost, reverse=True)
    if sort_key == "tokens":
        return sorted(sessions, key=lambda s: s.billable_tokens, reverse=True)
    if sort_key == "errors":
        return sorted(
            sessions,
            key=lambda s: (
                (s.perf.error_count + s.perf.tool_failures) if s.perf else 0
            ),
            reverse=True,
        )
    if sort_key == "health":
        return sorted(
            sessions,
            key=lambda s: calculate_health_score(s).score,
        )
    # Default: time (most recent last_seen first)
    epoch = datetime.min.replace(tzinfo=UTC)
    return sorted(
        sessions,
        key=lambda s: s.last_seen or s.first_seen or epoch,
        reverse=True,
    )
