"""Time utilities for the workflow engine."""

from __future__ import annotations

from datetime import datetime, timezone


def iso_now() -> str:
    """Return the current UTC time as an ISO 8601 string (e.g. '2024-01-15T10:30:00Z')."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc_strict(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp string to a timezone-aware datetime.

    Accepts the 'Z' suffix form: '2024-01-15T10:30:00Z'.
    """
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
