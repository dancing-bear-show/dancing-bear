"""Time utilities — re-exports from core.date_utils plus telemetry-specific helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from core.date_utils import now_utc, parse_iso_utc, parse_window

__all__ = [
    "format_latency",
    "nano_to_datetime",
    "now_utc",
    "parse_iso_utc",
    "parse_window",
]


def nano_to_datetime(unix_nano: int) -> datetime:
    """Convert Unix nanoseconds to a UTC datetime with microsecond precision."""
    seconds, nanoseconds = divmod(unix_nano, 1_000_000_000)
    microseconds = nanoseconds // 1_000
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=microseconds)


def format_latency(ms: float) -> str:
    """Format a latency value in milliseconds as a compact human string."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    minutes = int(ms // 60_000)
    seconds = int((ms % 60_000) / 1000)
    if seconds == 0:
        return f"{minutes}m"
    return f"{minutes}m {seconds}s"
