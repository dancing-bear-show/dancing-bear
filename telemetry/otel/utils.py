"""Shared utilities for the telemetry.otel module."""

from __future__ import annotations

from datetime import datetime

from telemetry.timeutil import now_utc, parse_window


def parse_time_window(since_arg: str | None) -> datetime | None:
    """Parse time window from a --since argument.

    Args:
        since_arg: Time specification like '1h', '24h', '7d', or None.
                   Plain numbers are treated as minutes.

    Returns:
        Cutoff datetime (everything after this time is included), or None
        for all time.

    Raises:
        ValueError: If since_arg format is invalid or is negative.
    """
    if not since_arg:
        return None

    try:
        delta = parse_window(since_arg, default_unit="minutes")
        if delta.total_seconds() < 0:
            raise ValueError("Duration cannot be negative")
        return now_utc() - delta
    except ValueError as e:
        raise ValueError(
            f"Invalid --since format: {since_arg!r}. Use '1h', '24h', '7d', or minutes"
        ) from e
