"""Internal helpers for the worker module.

Self-contained replacements for sreutils.constants, sreutils.core.fileutil,
sreutils.core.timeutil, sreutils.core.perf_logging, and sreutils.core.paths.
No external dependencies beyond stdlib.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ISO_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DATE_FORMAT_YMD = "%Y%m%d"
FIELD_UPDATED_AT = "updated_at"

# ---------------------------------------------------------------------------
# File utilities
# ---------------------------------------------------------------------------


def atomic_write_json(
    path: str | Path,
    data: dict[str, Any] | list[Any],
    *,
    indent: int = 2,
) -> None:
    """Atomically write JSON data to a file using temp file + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent), encoding="utf-8")
    tmp.replace(path)


def safe_load_json(
    path: str | Path,
    default: dict[str, Any] | None = None,
) -> Any:
    """Safely load JSON from a file, returning default on any error."""
    if default is None:
        default = {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # nosec B110 - intentional fallback to empty dict
        return dict(default)


# ---------------------------------------------------------------------------
# Time utilities
# ---------------------------------------------------------------------------

_ISO8601_Z_SUFFIX = "Z"
_ISO8601_UTC_SUFFIX = "+00:00"


def now_utc() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)


def iso_now() -> str:
    """Return current UTC time as an ISO 8601 string (YYYY-MM-DDTHH:MM:SSZ)."""
    return datetime.now(UTC).strftime(ISO_DATETIME_FORMAT)


def parse_iso_utc(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware UTC datetime, or None on failure."""
    if not value:
        return None
    try:
        s = str(value).strip()
        if not s:
            return None
        return datetime.fromisoformat(
            s.replace(_ISO8601_Z_SUFFIX, _ISO8601_UTC_SUFFIX)
        ).astimezone(UTC)
    except Exception:  # nosec B110 - intentional: return None on bad input
        return None


def parse_iso_utc_strict(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string, raising ValueError on failure."""
    dt = parse_iso_utc(ts)
    if dt is None:
        raise ValueError(f"invalid ISO timestamp: {ts}")
    return dt


def parse_window(win: str, default_unit: str = "hours") -> timedelta:
    """Parse a window string (e.g., '24h', '7d', '15m') to a timedelta."""
    if default_unit not in ("hours", "minutes"):
        raise ValueError(f"default_unit must be 'hours' or 'minutes', got {default_unit!r}")
    s = (win or "").strip().lower()
    error_msg = "Invalid window. Use Nd, Nw, Nh, Nm, or Ns (e.g., 30d, 2w, 24h, 15m, 30s)"
    try:
        if s.endswith("d"):
            return timedelta(days=float(s[:-1]))
        if s.endswith("w"):
            return timedelta(weeks=float(s[:-1]))
        if s.endswith("h"):
            return timedelta(hours=float(s[:-1]))
        if s.endswith("m"):
            return timedelta(minutes=float(s[:-1]))
        if s.endswith("s"):
            return timedelta(seconds=float(s[:-1]))
        value = float(s)
        if default_unit == "minutes":
            return timedelta(minutes=value)
        return timedelta(hours=value)
    except (ValueError, TypeError):
        raise ValueError(error_msg)


# ---------------------------------------------------------------------------
# Path utilities
# ---------------------------------------------------------------------------


def get_repo_root() -> Path:
    """Return the repo root (two levels above this file: worker/_helpers.py -> repo/)."""
    return Path(__file__).resolve().parents[1]


def get_worker_state_dir(subdir: str = "queue") -> Path:
    """Return the worker state directory under ~/Library/Application Support/dancing-bear."""
    app_support = Path.home() / "Library" / "Application Support" / "dancing-bear"
    return app_support / subdir


# ---------------------------------------------------------------------------
# Performance logging
# ---------------------------------------------------------------------------


def log_perf_jsonl(
    operation: str,
    duration_ms: int,
    *,
    args: list[str] | None = None,
    exit_code: int = 0,
) -> None:
    """Write a performance log entry to a JSONL file (best-effort, never raises)."""
    try:
        now = datetime.now(UTC)
        ts = now.strftime(ISO_DATETIME_FORMAT)
        ymd = now.strftime(DATE_FORMAT_YMD)

        try:
            log_dir = _get_log_dir()
        except Exception:  # nosec B110 - fallback log dir
            log_dir = Path.cwd() / "_data" / "logs"

        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"perf-{operation}-{ymd}.jsonl"

        record = {
            "ts": ts,
            "prog": operation,
            "args": args or [],
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "cwd": str(Path.cwd()),
            "pid": os.getpid(),
        }

        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:  # nosec B110 - perf logging is best-effort
        pass


def _get_log_dir() -> Path:
    """Return the log directory for perf logs."""
    env_dir = os.environ.get("SRE_LOG_DIR") or os.environ.get("DANCING_BEAR_LOG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / "Library" / "Application Support" / "dancing-bear" / "logs"
