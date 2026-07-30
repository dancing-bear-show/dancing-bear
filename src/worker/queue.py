"""Lightweight file-based job queue for background work.

Jobs are JSON files under a queue directory with subfolders:
- pending/: awaiting processing
- processing/: currently being processed (best-effort marker)
- done/: successfully processed (kept for audit)
- error/: failed after max_attempts

Job schema (dict):
- id: str (job id)
- type: str (handler key)
- payload: dict
- priority: int (lower = earlier); default 5
- not_before: ISO timestamp (UTC) — do not process before this
- attempts: int
- max_attempts: int (default 3)
- enqueued_at, updated_at: ISO timestamps

Atomicity is achieved via write-to-temp + rename. Processing moves a job
from pending/ to processing/ via rename; completion moves to done/ or error/.

This module is a thin re-export shim. Implementation lives in:
- worker.queue_ops  — core queue operations
- worker.queue_metrics — metrics and status insights
"""

from __future__ import annotations

from worker.queue_ops import (  # noqa: F401
    QUEUE_ROOT,
    Job,
    _apply_max_attempts,
    _ensure_dirs,
    _get_file_mtime,
    _job_path,
    _list_job_paths,
    _parse_timestamp_safe,
    _purge_file,
    _reap_move_to_pending,
    _reap_resolve_start_time,
    _remove_job_file,
    _rename,
    _strip_error_field,
    enqueue,
    find_job_path_by_id,
    finish,
    list_error,
    list_pending,
    list_processing,
    purge,
    reap_stale_processing_jobs,
    requeue_error,
    retry,
    start_processing,
)
from worker.queue_metrics import (  # noqa: F401
    _compute_pending_insights,
    _compute_processing_oldest_age,
    _update_wait_metrics,
    counts,
    status,
)
