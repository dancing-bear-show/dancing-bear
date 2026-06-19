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
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from worker._helpers import (
    FIELD_UPDATED_AT,
    ISO_DATETIME_FORMAT,
    atomic_write_json,
    get_worker_state_dir,
    iso_now,
    parse_iso_utc_strict,
    safe_load_json,
)

try:
    QUEUE_ROOT = get_worker_state_dir("queue")
except Exception:  # pragma: no cover - defensive fallback  # nosec B110 - best-effort path resolution
    QUEUE_ROOT = Path("_data/queue")


def _ensure_dirs(root: Path = QUEUE_ROOT) -> dict[str, Path]:
    paths = {
        "pending": root / "pending",
        "processing": root / "processing",
        "done": root / "done",
        "error": root / "error",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


@dataclass
class Job:
    id: str
    type: str
    payload: dict[str, object]
    priority: int = 5
    not_before: str = ""
    attempts: int = 0
    max_attempts: int = 3
    timeout_sec: int = 0   # 0 = use daemon-level job_timeout; >0 = per-job override
    enqueued_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        if not d.get("enqueued_at"):
            d["enqueued_at"] = iso_now()
        d[FIELD_UPDATED_AT] = iso_now()
        return d


def _job_path(folder: Path, job_id: str) -> Path:
    return folder / f"{job_id}.json"


def enqueue(job: Job, *, root: Path = QUEUE_ROOT) -> Path:
    """Enqueue a job by writing it to pending/ with atomic rename."""
    paths = _ensure_dirs(root)
    if not job.not_before:
        # default: immediately eligible
        job.not_before = iso_now()
    data = job.to_dict()
    path = _job_path(paths["pending"], job.id)
    atomic_write_json(path, data)
    return path


def _list_job_paths(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return [p for p in folder.iterdir() if p.is_file() and p.suffix == ".json"]


def list_pending(root: Path = QUEUE_ROOT) -> list[tuple[Path, dict[str, object]]]:
    paths = _ensure_dirs(root)
    items: list[tuple[Path, dict[str, object]]] = []
    now = datetime.now(UTC)
    for p in _list_job_paths(paths["pending"]):
        data = safe_load_json(p)
        nb = str(data.get("not_before") or "")
        try:
            eligible = (parse_iso_utc_strict(nb) <= now) if nb else True
        except Exception as exc:
            import logging as _logging

            _logging.getLogger(__name__).debug(
                "Invalid not_before '%s' in %s: %s", nb, p, exc
            )
            eligible = True
        if eligible:
            items.append((p, data))

    # Sort by priority, then enqueued_at
    def _key(item: tuple[Path, dict[str, object]]):
        d = item[1]
        pri = int(d.get("priority", 5))
        enq = str(d.get("enqueued_at") or "9999-12-31T23:59:59Z")
        return (pri, enq)

    items.sort(key=_key)
    return items


def _rename(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)


def start_processing(job_path: Path, root: Path = QUEUE_ROOT) -> Path | None:
    """Move a job from pending/ to processing/ and return new path, or None.

    Returns None when another worker has already claimed the job between
    listing and claim, which can occur under high concurrency.
    """
    paths = _ensure_dirs(root)
    job_id = job_path.stem
    new_path = _job_path(paths["processing"], job_id)
    # First, claim the job by renaming; then update metadata on the processing copy
    try:
        _rename(job_path, new_path)
        try:
            data = safe_load_json(new_path)
            data["status"] = "processing"
            data["processing_started_at"] = iso_now()
            data[FIELD_UPDATED_AT] = iso_now()
            atomic_write_json(new_path, data)
        except Exception as exc:
            import logging as _logging

            _logging.getLogger(__name__).debug(
                "Failed to update processing job %s: %s", new_path, exc
            )
        return new_path
    except FileNotFoundError:
        # Claimed elsewhere; ignore
        return None


def finish(
    job_path: Path,
    success: bool,
    *,
    root: Path = QUEUE_ROOT,
    error_msg: str | None = None,
    result: object | None = None,
) -> Path:
    """Write updated metadata to done/ or error/, then unlink the processing/ file."""
    data = safe_load_json(job_path)
    data[FIELD_UPDATED_AT] = iso_now()
    if success:
        data["status"] = "done"
        if result is not None:
            try:
                # Ensure JSON-serializable; fallback to string
                json.dumps(result)
                data["result"] = result
            except Exception:  # nosec B110 - intentional: fallback to string
                data["result"] = str(result)
    else:
        data["status"] = "error"
        if error_msg:
            data["error"] = str(error_msg)
    target_folder = "done" if success else "error"
    paths = _ensure_dirs(root)
    new_path = _job_path(paths[target_folder], job_path.stem)
    atomic_write_json(new_path, data)
    try:
        job_path.unlink(missing_ok=True)  # type: ignore[arg-type]
    except Exception as exc:
        import logging as _logging

        _logging.getLogger(__name__).debug(
            "Failed to remove processing job file %s: %s", job_path, exc
        )
    return new_path


def retry(
    job_path: Path,
    *,
    delay_sec: int = 60,
    root: Path = QUEUE_ROOT,
    reason: str | None = None,
) -> Path:
    """Bump attempts, set not_before to now+delay, and move back to pending/."""
    data = safe_load_json(job_path)
    data["attempts"] = int(data.get("attempts", 0)) + 1
    nb = datetime.now(UTC) + timedelta(seconds=int(delay_sec))
    data["not_before"] = nb.strftime(ISO_DATETIME_FORMAT)
    data[FIELD_UPDATED_AT] = iso_now()
    if reason:
        data["last_error"] = str(reason)
    paths = _ensure_dirs(root)
    new_path = _job_path(paths["pending"], job_path.stem)
    atomic_write_json(new_path, data)
    try:
        job_path.unlink(missing_ok=True)  # type: ignore[arg-type]
    except Exception as exc:
        import logging as _logging

        _logging.getLogger(__name__).debug(
            "Failed to remove job file %s: %s", job_path, exc
        )
    return new_path


def counts(root: Path = QUEUE_ROOT) -> dict[str, int]:
    paths = _ensure_dirs(root)
    return {k: len(_list_job_paths(v)) for k, v in paths.items()}


def _parse_timestamp_safe(ts_str: str, path: Path, field_name: str) -> datetime | None:
    """Parse an ISO timestamp string safely, returning None on failure."""
    if not ts_str:
        return None
    try:
        return parse_iso_utc_strict(ts_str)
    except Exception as exc:
        import logging as _logging

        _logging.getLogger(__name__).debug(
            "Invalid %s '%s' for %s: %s", field_name, ts_str, path, exc
        )
        return None


def _get_file_mtime(path: Path) -> datetime | None:
    """Get file modification time as datetime, or None on failure."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except Exception as exc:
        import logging as _logging

        _logging.getLogger(__name__).debug("Failed to stat %s: %s", path, exc)
        return None


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
        d = safe_load_json(p)
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


def list_processing(root: Path = QUEUE_ROOT) -> list[tuple[Path, dict[str, object]]]:
    """Return list of (path, data) for jobs currently in processing/."""
    paths = _ensure_dirs(root)
    items: list[tuple[Path, dict[str, object]]] = []
    for p in _list_job_paths(paths["processing"]):
        items.append((p, safe_load_json(p)))
    return items


def list_error(root: Path = QUEUE_ROOT) -> list[tuple[Path, dict[str, object]]]:
    """Return list of (path, data) for jobs currently in error/."""
    paths = _ensure_dirs(root)
    items: list[tuple[Path, dict[str, object]]] = []
    for p in _list_job_paths(paths["error"]):
        items.append((p, safe_load_json(p)))
    return items


def _apply_max_attempts(data: dict, new_max_attempts: int) -> None:
    """Set max_attempts on data, logging if the value cannot be coerced."""
    import logging as _logging

    try:
        data["max_attempts"] = int(new_max_attempts)
    except Exception as exc:
        _logging.getLogger(__name__).debug(
            "Invalid new_max_attempts=%s: %s", new_max_attempts, exc
        )


def _strip_error_field(data: dict, job_path: Path) -> None:
    """Move data['error'] to data['last_error'] and remove the original key."""
    import logging as _logging

    data["last_error"] = str(data.get("error"))
    try:
        del data["error"]
    except Exception as exc:
        _logging.getLogger(__name__).debug(
            "Failed to strip error field for %s: %s", job_path, exc
        )


def _remove_job_file(job_path: Path) -> None:
    """Unlink the old job file, logging on failure."""
    import logging as _logging

    try:
        job_path.unlink(missing_ok=True)  # type: ignore[arg-type]
    except Exception as exc:
        _logging.getLogger(__name__).debug(
            "Failed to remove error job %s: %s", job_path, exc
        )


def requeue_error(
    job_path: Path,
    *,
    delay_sec: int = 0,
    root: Path = QUEUE_ROOT,
    reset_attempts: bool = False,
    new_max_attempts: int | None = None,
) -> Path:
    """Move an error job back to pending/ with updated metadata.

    - delay_sec: set not_before to now+delay
    - reset_attempts: set attempts to 0 (so retries are allowed)
    - new_max_attempts: optionally override max_attempts
    """
    data = safe_load_json(job_path)
    data["attempts"] = 0 if reset_attempts else int(data.get("attempts", 0))
    if new_max_attempts is not None:
        _apply_max_attempts(data, new_max_attempts)
    nb = datetime.now(UTC) + timedelta(seconds=int(delay_sec))
    data["not_before"] = nb.strftime(ISO_DATETIME_FORMAT)
    data[FIELD_UPDATED_AT] = iso_now()
    data["status"] = "pending"
    if data.get("error"):
        _strip_error_field(data, job_path)
    paths = _ensure_dirs(root)
    new_path = _job_path(paths["pending"], job_path.stem)
    atomic_write_json(new_path, data)
    _remove_job_file(job_path)
    return new_path


def requeue_all_errors(
    *,
    root: Path = QUEUE_ROOT,
    delay_sec: int = 0,
    reset_attempts: bool = False,
    new_max_attempts: int | None = None,
    limit: int | None = None,
) -> list[Path]:
    """Requeue up to ``limit`` error jobs back to pending/.

    Returns a list of new pending job paths.
    """
    items = list_error(root=root)
    if limit is not None:
        items = items[: int(limit)]
    out: list[Path] = []
    for p, _ in items:
        out.append(
            requeue_error(
                p,
                delay_sec=delay_sec,
                root=root,
                reset_attempts=reset_attempts,
                new_max_attempts=new_max_attempts,
            )
        )
    return out


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


def _reap_resolve_start_time(data: dict[str, object], p: Path) -> datetime | None:
    """Resolve the effective start time for a processing job."""
    raw_started = data.get("processing_started_at")
    field_name = "processing_started_at"
    if not raw_started:
        raw_started = data.get("updated_at")
        field_name = "updated_at"
    started = _parse_timestamp_safe(str(raw_started or ""), p, field_name)
    if not started:
        started = _get_file_mtime(p)
    return started


def _reap_move_to_pending(
    p: Path,
    paths: dict[str, Path],
    data: dict[str, object],
    age: int,
    job_timeout: int,
    job_id: str,
    log: object,
) -> bool:
    """Rename a stale processing job to pending/ and update its metadata."""
    import logging as _logging

    _log: _logging.Logger = log  # type: ignore[assignment]
    new_path = _job_path(paths["pending"], job_id)
    try:
        _rename(p, new_path)
    except FileNotFoundError:
        _log.debug("Stale job %s already gone before reap rename; skipping", job_id)
        return False
    except Exception as exc:
        _log.debug("Failed to reap stale job %s: %s", job_id, exc)
        return False
    try:
        data["status"] = "pending"
        data[FIELD_UPDATED_AT] = iso_now()
        data["last_error"] = f"reaped after {age}s (timeout {job_timeout}s)"
        atomic_write_json(new_path, data)
    except Exception as exc:
        _log.debug("Failed to update metadata for reaped job %s: %s", job_id, exc)
        # job is in pending/ regardless; count it as reaped
    return True


def reap_stale_processing_jobs(
    job_timeout: int,
    *,
    root: Path = QUEUE_ROOT,
) -> list[str]:
    """Move processing jobs older than their effective timeout back to pending/."""
    import logging as _logging

    _log = _logging.getLogger(__name__)

    paths = _ensure_dirs(root)
    now = datetime.now(UTC)
    reaped: list[str] = []

    for p in _list_job_paths(paths["processing"]):
        data = safe_load_json(p)
        started = _reap_resolve_start_time(data, p)
        if not started:
            continue

        age = int((now - started).total_seconds())
        try:
            _per_job = int(data.get("timeout_sec") or 0)
            effective_timeout = _per_job if _per_job > 0 else job_timeout
        except (TypeError, ValueError):
            effective_timeout = job_timeout
        if effective_timeout <= 0 or age < effective_timeout:
            continue

        job_id = p.stem
        _log.warning(
            "Reaping stale processing job %s (age %ds >= timeout %ds); moving back to pending/",
            job_id,
            age,
            effective_timeout,
        )
        if _reap_move_to_pending(p, paths, data, age, effective_timeout, job_id, _log):
            reaped.append(job_id)

    return reaped


def find_job_path_by_id(job_id: str, root: Path = QUEUE_ROOT) -> Path | None:
    """Return the path for a job id across folders or None."""
    paths = _ensure_dirs(root)
    for folder in ("pending", "processing", "done", "error"):
        p = _job_path(paths[folder], job_id)
        if p.exists():
            return p
    return None


def _purge_file(p: Path, now: datetime, older_than_sec: int) -> bool:
    """Attempt to purge a single job file if older than threshold."""
    try:
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
        age = int((now - mtime).total_seconds())
        if age < older_than_sec:
            return False
        p.unlink(missing_ok=True)
        return True
    except Exception as exc:
        import logging as _logging

        _logging.getLogger(__name__).debug("Failed purge for %s: %s", p, exc)
        return False


def purge(
    older_than_sec: int, *, root: Path = QUEUE_ROOT, folders: list[str] | None = None
) -> dict[str, int]:
    """Delete jobs in given folders older than threshold; returns counts per folder."""
    paths = _ensure_dirs(root)
    now = datetime.now(UTC)
    targets = folders or ["done", "error"]
    out: dict[str, int] = dict.fromkeys(targets, 0)
    for name in targets:
        folder = paths.get(name)
        if not folder:
            continue
        for p in _list_job_paths(folder):
            if _purge_file(p, now, older_than_sec):
                out[name] += 1
    return out
