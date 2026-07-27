"""OTel integration helpers for the telemetry CLI."""

from __future__ import annotations

import sys
from datetime import datetime

_OTEL_EVENTS_MAX_AGE_SECS = 600
_OTEL_SUMMARY_CMD = "otel-summary"


def _otel_available() -> bool:
    """Return True when the OTel events file exists, is non-empty, and was modified within the last _OTEL_EVENTS_MAX_AGE_SECS seconds."""
    try:
        import time
        from telemetry.otel.reader import EVENTS_FILE, OTLPDataDir
        data_dir = OTLPDataDir.from_env()
        events_path = data_dir.path / EVENTS_FILE
        if not data_dir.path.exists():
            return False
        try:
            import stat as _stat
            st = events_path.stat()
            if not _stat.S_ISREG(st.st_mode) or st.st_size == 0:
                return False
        except (FileNotFoundError, NotADirectoryError):
            return False
        return (time.time() - st.st_mtime) <= _OTEL_EVENTS_MAX_AGE_SECS
    except Exception:  # nosec B110 - any import or runtime error means OTel is unavailable
        return False


def _otel_summary_rc(argv: list[str]) -> int:
    """Invoke the OTel summary CLI and return its exit code as an int.

    Translates FileNotFoundError → 1, ValueError → 3, and any other
    unexpected exception → 2 with a printed error message.
    """
    from telemetry.otel.cli.otel_summary import main as _otel_main
    try:
        return _otel_main(argv)
    except FileNotFoundError:
        return 1
    except ValueError:
        return 3
    except Exception as exc:  # nosec B110 - convert all errors to integer exit codes for CLI callers
        print(f"otel-summary error: {exc}", file=sys.stderr)
        return 2


def _since_to_otel_window(since: str) -> str:
    """Map a --since value (e.g. '2d', '48h') to the smallest OTel window that covers it.

    OTel supports: 1h, 24h, 7d, 30d. Values beyond 30d map to 30d.
    """
    from telemetry.timeutil import parse_window
    try:
        delta = parse_window(since)
    except ValueError:
        return "24h"
    secs = delta.total_seconds()
    if secs <= 3600:
        return "1h"
    if secs <= 86400:
        return "24h"
    if secs <= 604_800:
        return "7d"
    return "30d"


def _parse_since_cli(since: str) -> datetime:
    """Parse --since window string, raising ValueError on bad input."""
    from telemetry.timeutil import now_utc, parse_window

    try:
        return now_utc() - parse_window(since)
    except ValueError as e:
        raise ValueError(str(e)) from e


def _normalize_since_for_otel(since: str | None) -> str | None:
    """Make a bare-integer --since agree with the transcript path's default unit.

    get_daily_cost_from_metric() parses ``since`` via parse_time_window(),
    which treats a suffix-less integer as minutes. The transcript path
    (_parse_since_cli -> parse_window) treats the same bare integer as
    hours. Under --source auto, routing between the two paths is
    transparent to the user, so "--since 30" must mean the same window
    regardless of which path handles it. Suffixed values (7d, 24h, ...)
    already agree between both parsers and pass through unchanged.
    """
    stripped = (since or "").strip()
    try:
        float(stripped)
    except ValueError:
        return since
    return f"{stripped}h"
