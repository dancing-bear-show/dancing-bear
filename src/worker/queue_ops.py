"""Core queue operations: enqueue, claim, finish, retry, requeue, purge.

Provides the Job dataclass, path helpers, and all state-transition functions
for the file-based job queue under QUEUE_ROOT.
"""

from __future__ import annotations

import json
import logging
import os
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
_JOB_SUFFIX = ".json"


def _q(root: Path | None) -> Path:
    """Return *root* if given, otherwise the current module-level QUEUE_ROOT.

    Using this helper instead of ``root: Path = QUEUE_ROOT`` as a default
    argument makes the resolution happen at *call* time, not import time.
    Tests can therefore reassign ``queue_ops.QUEUE_ROOT`` after import and
    have the change picked up without patching every default argument
    individually.
    """
    return root if root is not None else QUEUE_ROOT


def _ensure_dirs(root: Path | None = None) -> dict[str, Path]:
    r = _q(root)
    paths = {
        "pending": r / "pending",
        "processing": r / "processing",
        "done": r / "done",
        "error": r / "error",
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
    return folder / f"{job_id}{_JOB_SUFFIX}"


def enqueue(job: Job, *, root: Path | None = None) -> Path:
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
    return [p for p in folder.iterdir() if p.is_file() and p.suffix == _JOB_SUFFIX]


def list_pending(root: Path | None = None) -> list[tuple[Path, dict[str, object]]]:
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
        raw_pri = d.get("priority")
        pri = int(raw_pri) if isinstance(raw_pri, (int, float, str)) else 5
        enq = str(d.get("enqueued_at") or "9999-12-31T23:59:59Z")
        return (pri, enq)

    items.sort(key=_key)
    return items


def _rename(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)


def start_processing(job_path: Path, root: Path | None = None) -> Path | None:
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
    root: Path | None = None,
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
    root: Path | None = None,
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


_REQUEUE_STAGING_SUFFIX = ".requeue"
SHUTDOWN_REQUEUE_REASON = "requeued-on-shutdown"


def _normalize_requeued(data: dict[str, object], reason: str) -> None:
    """Set the metadata every requeued pending/ record carries.

    Eligible immediately, ``reason`` as ``last_error``, attempts untouched.
    Shared by every path that publishes a staged record, so they cannot drift.
    """
    now = iso_now()
    data["status"] = "pending"
    data["not_before"] = now
    data[FIELD_UPDATED_AT] = now
    data["last_error"] = str(reason)


def _rewrite_staged(staged: Path, reason: str, *, only_if_unnormalized: bool) -> None:
    """Normalise a staged record's metadata in place, before it is published.

    ``only_if_unnormalized`` leaves a record that already says
    ``status: pending`` untouched: its requeue finished the rewrite before
    it was interrupted. An unreadable record is published as-is rather than
    replaced with near-empty metadata; stale metadata beats a lost job.
    """
    data = safe_load_json(staged, default=None)
    if not isinstance(data, dict):
        _log.debug("Staged job %s is not a JSON object; publishing unchanged", staged)
        return
    if only_if_unnormalized and data.get("status") == "pending":
        return
    _normalize_requeued(data, reason)
    atomic_write_json(staged, data)


def _publish_no_clobber(staged: Path, dest: Path) -> bool:
    """Move ``staged`` to ``dest`` unless ``dest`` already holds another file.

    A hard link publishes atomically and fails if ``dest`` exists, so a
    pending/ job with the same id is never overwritten. If ``dest`` is
    already a link to ``staged`` (an earlier publish stopped before its
    unlink), only the staging name is removed. Returns False, leaving
    ``staged`` in place for a later recovery, when ``dest`` is a different
    file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(staged, dest)
    except FileExistsError:
        if not dest.samefile(staged):
            _log.warning("Not publishing %s: %s already exists", staged.name, dest)
            return False
    except OSError:
        # No hard links on this filesystem: check-then-replace is the best available.
        if dest.exists():
            _log.warning("Not publishing %s: %s already exists", staged.name, dest)
            return False
        staged.replace(dest)
        return True
    staged.unlink(missing_ok=True)
    return True


def _stage_and_requeue(src: Path, pending_dir: Path, reason: str) -> Path | None:
    """Claim ``src`` from processing/ by renaming it, normalise it, then publish it.

    The staging name matches no queue listing, so the claim is atomic and no
    other worker can pick up the pending/ copy before its metadata is
    written. Returns the pending/ path, or None when ``src`` was already gone
    (nothing is written) or the publish was refused (the staged file stays
    for ``recover_staged_requeues``).
    """
    staged = src.with_name(src.name + _REQUEUE_STAGING_SUFFIX)
    try:
        src.rename(staged)
    except FileNotFoundError:
        return None
    try:
        _rewrite_staged(staged, reason, only_if_unnormalized=False)
    except Exception as exc:  # still move the job: stale metadata beats a stranded file
        _log.debug("Failed to update metadata for requeued job %s: %s", src.stem, exc)
    new_path = _job_path(pending_dir, src.stem)
    return new_path if _publish_no_clobber(staged, new_path) else None


def requeue_processing(job_id: str, *, reason: str, root: Path | None = None) -> Path | None:
    """Move processing/<job_id> back to pending/ without consuming an attempt.

    The job becomes eligible immediately and records ``reason`` as
    ``last_error``. Returns the pending/ path, or None when the job is no
    longer in processing/ (it finished or was moved elsewhere first), in
    which case nothing is written, or when pending/ already holds a job with
    that id (the staged copy is kept for ``recover_staged_requeues``).

    Unlike ``retry``, a job that vanished before the claim is never
    recreated from empty metadata, and no other worker can claim the
    pending/ copy before its metadata is written; see ``_stage_and_requeue``.
    """
    paths = _ensure_dirs(root)
    return _stage_and_requeue(_job_path(paths["processing"], job_id), paths["pending"], reason)


def recover_staged_requeues(root: Path | None = None) -> list[str]:
    """Complete any interrupted staged requeue in processing/.

    A crash between staging a job and publishing it leaves a
    ``*.json.requeue`` file that ``_list_job_paths`` never matches (it
    filters to ``suffix == ".json"``). On startup this function publishes
    each one to pending/ and returns the recovered job ids.

    A crash can also land before the staged metadata was rewritten, leaving
    ``status: processing``. Such a record is normalised exactly as
    ``requeue_processing`` would have, with ``SHUTDOWN_REQUEUE_REASON`` as
    ``last_error``; one already rewritten is published unchanged. An
    existing pending/ job with the same id is never overwritten, and a
    second call is a no-op.
    """
    paths = _ensure_dirs(root)
    recovered: list[str] = []
    for staged in list(paths["processing"].iterdir()):
        if not staged.name.endswith(_JOB_SUFFIX + _REQUEUE_STAGING_SUFFIX):
            continue
        job_id = staged.name[: -len(_JOB_SUFFIX + _REQUEUE_STAGING_SUFFIX)]
        try:
            _rewrite_staged(staged, SHUTDOWN_REQUEUE_REASON, only_if_unnormalized=True)
            if _publish_no_clobber(staged, _job_path(paths["pending"], job_id)):
                recovered.append(job_id)
                _log.info("recovered staged requeue for job %s", job_id)
        except Exception as exc:  # nosec B110 - best-effort recovery; log and continue
            _log.debug("Failed to recover staged requeue %s: %s", staged, exc)
    return recovered


def list_processing(root: Path | None = None) -> list[tuple[Path, dict[str, object]]]:
    """Return list of (path, data) for jobs currently in processing/."""
    paths = _ensure_dirs(root)
    items: list[tuple[Path, dict[str, object]]] = []
    for p in _list_job_paths(paths["processing"]):
        items.append((p, safe_load_json(p, default={})))
    return items


def list_error(root: Path | None = None) -> list[tuple[Path, dict[str, object]]]:
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
    root: Path | None = None,
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


def find_job_path_by_id(job_id: str, root: Path | None = None) -> Path | None:
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
    age: int
    job_timeout: int
    job_id: str


def _reap_move_to_pending(ctx: ReapJobContext, log: logging.Logger) -> bool:
    """Requeue a stale processing job, writing its metadata before it is published."""
    reason = f"reaped after {ctx.age}s (timeout {ctx.job_timeout}s)"
    try:
        new_path = _stage_and_requeue(ctx.p, ctx.paths["pending"], reason)
    except Exception as exc:
        log.debug("Failed to reap stale job %s: %s", ctx.job_id, exc)
        return False
    if new_path is None:
        log.debug("Stale job %s not requeued (gone, or pending/ copy exists)", ctx.job_id)
        return False
    return True


def _reap_effective_timeout(data: dict, job_timeout: int) -> int:
    """Resolve the per-job timeout override, falling back to the default."""
    try:
        per_job = int(data.get("timeout_sec") or 0)
        return per_job if per_job > 0 else job_timeout
    except (TypeError, ValueError):
        return job_timeout


def _reap_one_job(p: Path, job_timeout: int, paths: dict, now: datetime, log: logging.Logger) -> str | None:
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
        age=age,
        job_timeout=effective_timeout,
        job_id=job_id,
    )
    return job_id if _reap_move_to_pending(reap_ctx, log) else None


def reap_stale_processing_jobs(
    job_timeout: int,
    *,
    root: Path | None = None,
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
    older_than_sec: int, *, root: Path | None = None, folders: list[str] | None = None
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
