"""Core queue operations: enqueue, claim, finish, retry, requeue, purge.

Provides the Job dataclass, path helpers, and all state-transition functions
for the file-based job queue under QUEUE_ROOT.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.date_utils import iso_now, parse_iso_utc_strict
from core.fileutil import atomic_write_json, safe_load_json
from worker._helpers import (
    FIELD_UPDATED_AT,
    ISO_DATETIME_FORMAT,
    get_worker_state_dir,
)

_log = logging.getLogger(__name__)

try:
    QUEUE_ROOT = get_worker_state_dir("queue")
except Exception:  # pragma: no cover - defensive fallback  # nosec B110 - best-effort path resolution
    QUEUE_ROOT = Path("_data/queue")

QUEUE_FOLDERS: tuple[str, ...] = ("pending", "processing", "done", "error")


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
    """Enqueue a job by writing it to pending/ with atomic rename.

    Raises:
        ValueError: if not_before is set but is not a parseable ISO timestamp.
            Rejecting at entry keeps an unschedulable job off disk, rather
            than surfacing the problem later as a skipped job in list_pending.
    """
    paths = _ensure_dirs(root)
    if not job.not_before:
        # default: immediately eligible
        job.not_before = iso_now()
    else:
        parse_iso_utc_strict(job.not_before)  # raises ValueError on bad input
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
        data = safe_load_json(p, default={})
        nb = str(data.get("not_before") or "")
        if not nb:
            items.append((p, data))
            continue
        try:
            eligible = parse_iso_utc_strict(nb) <= now
        except ValueError as exc:
            # An unparseable schedule means "we do not know when this is due",
            # so treat it as not-yet-due and leave it in pending/. Previously
            # this fell through to eligible=True, which silently ran a
            # deliberately deferred job immediately behind a debug log.
            _log.warning(
                "Skipping job %s: unparseable not_before %r (%s)", p.name, nb, exc
            )
            continue
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
            data = safe_load_json(new_path, default={})
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
    data = safe_load_json(job_path, default={})
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
    _remove_job_file(job_path)
    return new_path


def retry(
    job_path: Path,
    *,
    delay_sec: int = 60,
    root: Path = QUEUE_ROOT,
    reason: str | None = None,
) -> Path:
    """Bump attempts, set not_before to now+delay, and move back to pending/."""
    data = safe_load_json(job_path, default={})
    data["attempts"] = int(data.get("attempts", 0)) + 1
    nb = datetime.now(UTC) + timedelta(seconds=int(delay_sec))
    data["not_before"] = nb.strftime(ISO_DATETIME_FORMAT)
    data[FIELD_UPDATED_AT] = iso_now()
    if reason:
        data["last_error"] = str(reason)
    paths = _ensure_dirs(root)
    new_path = _job_path(paths["pending"], job_path.stem)
    atomic_write_json(new_path, data)
    _remove_job_file(job_path)
    return new_path


def list_processing(root: Path = QUEUE_ROOT) -> list[tuple[Path, dict[str, object]]]:
    """Return list of (path, data) for jobs currently in processing/."""
    paths = _ensure_dirs(root)
    items: list[tuple[Path, dict[str, object]]] = []
    for p in _list_job_paths(paths["processing"]):
        items.append((p, safe_load_json(p, default={})))
    return items


def list_error(root: Path = QUEUE_ROOT) -> list[tuple[Path, dict[str, object]]]:
    """Return list of (path, data) for jobs currently in error/."""
    paths = _ensure_dirs(root)
    items: list[tuple[Path, dict[str, object]]] = []
    for p in _list_job_paths(paths["error"]):
        items.append((p, safe_load_json(p, default={})))
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
    """Unlink the old job file after its replacement is written, logging on failure.

    Shared by finish(), retry(), and requeue_error(), which all write the new
    job file first and then remove the old one. The message stays generic
    because the path itself identifies which queue directory the job came
    from -- naming one specific transition here would be wrong for the others.
    """
    import logging as _logging

    try:
        job_path.unlink(missing_ok=True)
    except Exception as exc:
        _logging.getLogger(__name__).debug(
            "Failed to remove job file %s: %s", job_path, exc
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
    data = safe_load_json(job_path, default={})
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


def find_job_path_by_id(job_id: str, root: Path = QUEUE_ROOT) -> Path | None:
    """Return the path for a job id across folders or None."""
    paths = _ensure_dirs(root)
    for folder in QUEUE_FOLDERS:
        p = _job_path(paths[folder], job_id)
        if p.exists():
            return p
    return None


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


@dataclass(frozen=True)
class ReapJobContext:
    """Bundle of state for moving a single stale processing job back to pending."""

    p: Path
    paths: dict[str, Path]
    data: dict[str, object]
    age: int
    job_timeout: int
    job_id: str


def _reap_move_to_pending(ctx: ReapJobContext, log: object) -> bool:
    """Rename a stale processing job to pending/ and update its metadata."""
    import logging as _logging

    _log: _logging.Logger = log  # type: ignore[assignment]
    new_path = _job_path(ctx.paths["pending"], ctx.job_id)
    try:
        _rename(ctx.p, new_path)
    except FileNotFoundError:
        _log.debug("Stale job %s already gone before reap rename; skipping", ctx.job_id)
        return False
    except Exception as exc:
        _log.debug("Failed to reap stale job %s: %s", ctx.job_id, exc)
        return False
    try:
        ctx.data["status"] = "pending"
        ctx.data[FIELD_UPDATED_AT] = iso_now()
        ctx.data["last_error"] = f"reaped after {ctx.age}s (timeout {ctx.job_timeout}s)"
        atomic_write_json(new_path, ctx.data)
    except Exception as exc:
        _log.debug("Failed to update metadata for reaped job %s: %s", ctx.job_id, exc)
        # job is in pending/ regardless; count it as reaped
    return True


def _reap_effective_timeout(data: dict, job_timeout: int) -> int:
    """Resolve the per-job timeout override, falling back to the default."""
    try:
        per_job = int(data.get("timeout_sec") or 0)
        return per_job if per_job > 0 else job_timeout
    except (TypeError, ValueError):
        return job_timeout


def _reap_one_job(p: Path, job_timeout: int, paths: dict, now: datetime, log: object) -> str | None:
    """Reap one processing job if stale. Returns its job_id if reaped, else None."""
    data = safe_load_json(p, default={})
    started = _reap_resolve_start_time(data, p)
    if not started:
        return None

    age = int((now - started).total_seconds())
    effective_timeout = _reap_effective_timeout(data, job_timeout)
    if effective_timeout <= 0 or age < effective_timeout:
        return None

    job_id = p.stem
    log.warning(
        "Reaping stale processing job %s (age %ds >= timeout %ds); moving back to pending/",
        job_id,
        age,
        effective_timeout,
    )
    reap_ctx = ReapJobContext(
        p=p,
        paths=paths,
        data=data,
        age=age,
        job_timeout=effective_timeout,
        job_id=job_id,
    )
    return job_id if _reap_move_to_pending(reap_ctx, log) else None


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
        job_id = _reap_one_job(p, job_timeout, paths, now, _log)
        if job_id:
            reaped.append(job_id)

    return reaped


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
