"""Queue metrics and insights: counts, status, and pending/processing analytics.

Imports core types and helpers from queue_ops to avoid circular dependencies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from worker.queue_ops import (
    QUEUE_ROOT,
    _ensure_dirs,
    _get_file_mtime,
    _list_job_paths,
    _parse_timestamp_safe,
    list_processing,
)
from core.fileutil import safe_load_json


def counts(root: Path = QUEUE_ROOT) -> dict[str, int]:
    paths = _ensure_dirs(root)
    return {k: len(_list_job_paths(v)) for k, v in paths.items()}


def _update_wait_metrics(
    nb: datetime | None,
    enq: datetime | None,
    now: datetime,
    oldest_wait: int,
    next_in: int | None,
) -> tuple[int, int | None]:
    """Update oldest_wait and next_in based on job timestamps."""
    eligible = nb or enq
    if eligible and eligible <= now:
        wait = int((now - eligible).total_seconds())
        if wait > oldest_wait:
            oldest_wait = wait
    elif nb and nb > now:
        delta = int((nb - now).total_seconds())
        if next_in is None or delta < next_in:
            next_in = delta
    return oldest_wait, next_in


def _compute_pending_insights(
    pending_folder: Path,
    now: datetime,
) -> tuple[int, int | None, dict[str, int]]:
    """Compute pending queue insights: oldest wait, next scheduled, by-priority counts.

    Returns:
        Tuple of (oldest_wait_sec, next_scheduled_in_sec, by_priority_dict)
    """
    oldest_wait = 0
    next_in: int | None = None
    by_pri: dict[str, int] = {}

    for p in _list_job_paths(pending_folder):
        d = safe_load_json(p, default={})
        pri = str(int(d.get("priority", 5)))
        by_pri[pri] = by_pri.get(pri, 0) + 1

        nb_s = str(d.get("not_before") or "")
        enq_s = str(d.get("enqueued_at") or "")
        nb = _parse_timestamp_safe(nb_s, p, "not_before")
        enq = _parse_timestamp_safe(enq_s, p, "enqueued_at")

        oldest_wait, next_in = _update_wait_metrics(nb, enq, now, oldest_wait, next_in)

    return oldest_wait, next_in, by_pri


def _compute_processing_oldest_age(
    processing_items: list[tuple[Path, dict[str, object]]],
    now: datetime,
) -> int:
    """Compute the age in seconds of the oldest processing job."""
    proc_oldest = 0
    for p, d in processing_items:
        started_s = str(d.get("processing_started_at") or d.get("updated_at") or "")
        started = _parse_timestamp_safe(started_s, p, "processing_started_at")
        if not started:
            started = _get_file_mtime(p)
        if started:
            age = int((now - started).total_seconds())
            if age > proc_oldest:
                proc_oldest = age
    return proc_oldest


def status(root: Path = QUEUE_ROOT) -> dict[str, object]:
    """Compute a queue status summary for visibility/monitoring.

    Returns keys:
    - counts: dict per-folder counts
    - pending_by_priority: map priority->count
    - oldest_pending_wait_sec: max seconds since job became eligible
    - next_scheduled_in_sec: seconds until next not_before (if any future)
    - processing_oldest_age_sec: oldest processing age in seconds
    - recent_error_ids: up to 5 most recent error job ids
    - root: queue root path
    """
    paths = _ensure_dirs(root)
    now = datetime.now(UTC)
    c = counts(root)

    # Pending insights
    oldest_wait, next_in, by_pri = _compute_pending_insights(paths["pending"], now)

    # Processing insights
    proc_oldest = _compute_processing_oldest_age(list_processing(root), now)

    # Recent errors (by mtime desc)
    errs = sorted(
        _list_job_paths(paths["error"]),
        key=lambda x: x.stat().st_mtime if x.exists() else 0,
        reverse=True,
    )[:5]

    return {
        "counts": c,
        "pending_by_priority": dict(sorted(by_pri.items(), key=lambda kv: int(kv[0]))),
        "oldest_pending_wait_sec": int(oldest_wait),
        "next_scheduled_in_sec": (int(next_in) if next_in is not None else None),
        "processing_oldest_age_sec": int(proc_oldest),
        "recent_error_ids": [e.stem for e in errs],
        "root": str(root),
    }
