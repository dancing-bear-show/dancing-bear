"""Internal helpers for the worker module.

Self-contained implementations of constants, path resolution helpers,
and performance logging. No external dependencies beyond stdlib.

File I/O (atomic_write_json, safe_load_json) and date/time utilities
(now_utc, iso_now, parse_iso_utc, parse_iso_utc_strict, parse_window)
are provided by core.fileutil and core.date_utils respectively.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ISO_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DATE_FORMAT_YMD = "%Y%m%d"
FIELD_UPDATED_AT = "updated_at"


# ---------------------------------------------------------------------------
# Path utilities
# ---------------------------------------------------------------------------


def get_repo_root() -> Path:
    """Return the dancing-bear repo root (three levels above src/worker/_helpers.py).

    parents[1] is <repo>/src, not <repo>. Landing one level short makes every
    `get_repo_root() / "bin"` lookup point at a nonexistent <repo>/src/bin,
    which silently rejects valid bin/* commands as disallowed.
    """
    return Path(__file__).resolve().parents[2]


WORKER_STATE_DIR_ENV = "DANCING_BEAR_WORKER_STATE_DIR"


def get_worker_state_dir(subdir: str = "queue") -> Path:
    """Return a worker state directory (queue, logs, ...).

    Defaults to ~/Library/Application Support/dancing-bear/<subdir>. Setting
    DANCING_BEAR_WORKER_STATE_DIR replaces that base, which gives a process a
    fully private queue: nothing else enqueues into it, and the launchd daemon,
    started without the variable, never sees it. This is the seam for running
    real jobs without touching the user's shared queue. Redirecting HOME would
    do the same but also redirects git's configuration, which is why a
    dedicated variable exists. A relative value is resolved against the
    current directory.

    Read at call time; note queue_ops computes QUEUE_ROOT once at import, so
    the variable must be in the environment when the process starts.
    """
    override = os.environ.get(WORKER_STATE_DIR_ENV, "").strip()
    base = (
        Path(override).expanduser().resolve()
        if override
        else Path.home() / "Library" / "Application Support" / "dancing-bear"
    )
    return base / subdir


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
    # Through get_worker_state_dir, so DANCING_BEAR_WORKER_STATE_DIR moves the
    # logs along with the queue instead of leaving them in the shared location.
    return get_worker_state_dir("logs")
