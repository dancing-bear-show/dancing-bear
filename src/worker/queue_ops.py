"""Core queue operations: enqueue, claim, finish, retry, requeue, purge.

Provides the Job dataclass, path helpers, and all state-transition functions
for the file-based job queue under QUEUE_ROOT.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from glob import escape as glob_escape
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

# Sentinel distinguishing "caller has no token concept, skip the check"
# (the parameter's default) from "caller expects the record to carry no
# token" (an explicit None passed as the expected value). Both states use
# `None` as data -- a missing claim token IS `None` -- so a bare `None`
# default cannot tell them apart; the check in _stage_and_requeue keys off
# identity against this sentinel instead.
_NO_TOKEN_CHECK = object()

try:
    QUEUE_ROOT = get_worker_state_dir("queue")
except Exception:  # pragma: no cover - defensive fallback  # nosec B110 - best-effort path resolution
    QUEUE_ROOT = Path("_data/queue")

QUEUE_FOLDERS: tuple[str, ...] = ("pending", "processing", "done", "error")
_JOB_SUFFIX = ".json"
# Written by start_processing; identifies one claim of a job so a worker whose
# job was requeued (and possibly re-claimed elsewhere) cannot complete it.
CLAIM_TOKEN_FIELD = "claim_token"  # nosec B105 - JSON field name, not a secret
_TRANSITION_LOCK_NAME = ".transitions.lock"
# Record statuses that name their own destination folder (see _write_finished).
_TERMINAL_FOLDERS: tuple[str, ...] = ("done", "error")


def _q(root: Path | None) -> Path:
    """Return *root* if given, otherwise the current module-level QUEUE_ROOT.

    Resolving here at call time, rather than writing QUEUE_ROOT as the parameter
    default, matters: a default is bound at import, so a caller that omits ``root`` would
    reach the user's real queue even after a test reassigned QUEUE_ROOT, and the
    live daemon would then run the test's jobs.
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
        if not isinstance(data, dict):
            # A JSON array or scalar is not a job; skipping it keeps one bad
            # file from aborting the listing of every other pending job.
            _log.warning("Skipping job %s: record is not a JSON object", p.name)
            continue
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
        try:
            pri = int(raw_pri) if isinstance(raw_pri, (int, float, str)) else 5
        except (ValueError, OverflowError):
            # A non-numeric priority string sorts as the default instead of
            # raising out of sort() and hiding every other pending job.
            pri = 5
        enq = str(d.get("enqueued_at") or "9999-12-31T23:59:59Z")
        return (pri, enq)

    items.sort(key=_key)
    return items


def _rename(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)


def start_processing(job_path: Path, root: Path | None = None) -> tuple[Path, str] | None:
    """Move a job from pending/ to processing/ and return (new_path, claim_token), or None.

    Returns None when another worker has already claimed the job between
    listing and claim, which can occur under high concurrency.

    Both the rename and the metadata write happen under ``_transition_lock``.
    Without the lock, a stale reaper could observe ``processing/<id>.json``
    after the rename but before the claim-token and ``processing_started_at``
    fields are written, decide the job is stale (no start time), stage it back
    to pending/, and allow a second worker to pick it up while this worker is
    still running it.

    The claim token written inside the lock is returned as the second element of
    the tuple so callers never need a second file-read to learn their own token.
    A separate ``claim_token()`` call after this one has a TOCTOU window: the
    lock is released before the read, and in that gap another worker's reaper
    can reclaim the stem and write a new token — the re-read then returns the
    replacement token and the caller proceeds to process a job it does not own.
    Returning the token here, while the lock is still held, closes that window.

    When the metadata write fails, the returned token is an empty string rather
    than None (None would widen the return to three states and lose the path).
    Callers that need a non-empty token to establish ownership must check for
    an empty string and requeue; see ``_start_batch`` and ``process_one``.

    Also returns None, leaving ``job_path`` in pending/, when processing/
    already holds a record with the same id. ``enqueue`` accepts an explicit
    id and never looks at processing/, so a pending copy of a running job is
    possible; renaming over it would replace the active claim's record, token
    and payload before any ownership check could protect them. Every writer
    of processing/ holds the transition lock, so the existence check below
    stays valid until the rename. The duplicate becomes claimable once the
    active claim leaves processing/.
    """
    paths = _ensure_dirs(root)
    job_id = job_path.stem
    new_path = _job_path(paths["processing"], job_id)
    token: str = ""
    try:
        with _transition_lock(root):
            if new_path.exists():
                _log.warning(
                    "Not claiming job %s: processing/ already holds a claim for this id; "
                    "leaving the duplicate in pending/",
                    job_id,
                )
                return None
            # Claim the job atomically: rename then write metadata before the
            # lock is released, so a reaper cannot observe the processing/
            # record in a partially-initialised state.
            _rename(job_path, new_path)
            try:
                data = safe_load_json(new_path, default={})
                data["status"] = "processing"
                token = uuid.uuid4().hex
                data[CLAIM_TOKEN_FIELD] = token
                data["processing_started_at"] = iso_now()
                data[FIELD_UPDATED_AT] = iso_now()
                atomic_write_json(new_path, data)
            except Exception as exc:
                import logging as _logging

                _logging.getLogger(__name__).debug(
                    "Failed to update processing job %s: %s", new_path, exc
                )
                token = ""  # nosec B105 - empty string signals metadata-write failure, not a credential
        return new_path, token
    except FileNotFoundError:
        # Claimed elsewhere; ignore
        return None


def claim_token(proc_path: Path) -> str | None:
    """Return the claim token ``start_processing`` wrote to ``proc_path``, or None."""
    data = safe_load_json(proc_path, default=None)
    token = data.get(CLAIM_TOKEN_FIELD) if isinstance(data, dict) else None
    return str(token) if token else None


class _TransitionLockTimeout(Exception):
    """Raised when ``_transition_lock`` cannot acquire the lock within its timeout.

    Follows the ``_NoClobberRaceLost`` naming convention established in this
    module. Callers that need a best-effort-only attempt (e.g.
    ``drain_live_threads`` after the shutdown deadline has passed) catch this
    and continue rather than blocking indefinitely.
    """


@contextmanager
def _transition_lock(root: Path | None, timeout: float | None = None) -> Iterator[None]:
    """Serialise processing/ transitions across threads and processes.

    Held by every transition that removes a processing/ record (finish,
    retry, requeue, reap) and by staged-requeue recovery, so recovery never
    publishes a staged file another transition is still writing, and an
    ownership check stays valid until its transition completes. Each entry
    opens its own descriptor, so threads of one process exclude each other
    too. No-op where ``fcntl`` is unavailable.

    When ``timeout`` is given (not None), the call raises ``_TransitionLockTimeout``
    rather than blocking indefinitely if the lock cannot be acquired within
    that many seconds. Omitting it (the default) preserves the original
    blocking behaviour for all existing callers; only ``drain_live_threads``
    passes a timeout, to avoid exceeding the shutdown grace period.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-POSIX platform
        yield
        return
    lock_path = _q(root) / _TRANSITION_LOCK_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as fh:
        if timeout is None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        else:
            # Non-blocking loop with short sleeps until the timeout elapses.
            deadline = time.monotonic() + timeout
            _POLL_INTERVAL = 0.05  # seconds between acquisition attempts
            acquired = False
            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(_POLL_INTERVAL, remaining))
            if not acquired:
                raise _TransitionLockTimeout(
                    f"could not acquire transition lock within {timeout:.1f}s"
                )
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _owned_record(job_path: Path, token: str | None) -> dict[str, object] | None:
    """Return ``job_path``'s record if the caller still owns it, else None.

    Call with ``_transition_lock`` held. A missing or unreadable record means
    another transition (a shutdown drain, a reap) took the job; a token that
    differs means the job was requeued and claimed again by someone else.
    Either way the caller has lost ownership and must write nothing.
    """
    data = safe_load_json(job_path, default=None)
    if not isinstance(data, dict) or not data:
        _log.warning("Ownership lost for job %s: %s is gone or unreadable", job_path.stem, job_path)
        return None
    if token is not None and data.get(CLAIM_TOKEN_FIELD) != token:
        _log.warning("Ownership lost for job %s: claimed again by another worker", job_path.stem)
        return None
    return data


def finish(
    job_path: Path,
    success: bool,
    *,
    root: Path | None = None,
    error_msg: str | None = None,
    result: object | None = None,
    claim_token: str | None = None,
) -> Path | None:
    """Rewrite the processing/ record as done or error, then move it there.

    Returns None and writes nothing when the caller no longer owns the job:
    ``job_path`` is gone or unreadable, or ``claim_token`` is given and does
    not match the record's (see ``_owned_record``).
    """
    with _transition_lock(root):
        data = _owned_record(job_path, claim_token)
        if data is None:
            return None
        return _write_finished(job_path, data, success, root=root, error_msg=error_msg, result=result)


def _write_finished(
    job_path: Path,
    data: dict[str, object],
    success: bool,
    *,
    root: Path | None,
    error_msg: str | None,
    result: object | None,
) -> Path:
    """Rewrite ``job_path`` as a done/ or error/ record, then move it there.

    The record is rewritten in place and then renamed, so the claim ends in
    one step: the terminal record appears exactly when the processing/ one
    disappears. Publishing the terminal record first and unlinking second left
    both behind when the unlink failed, with the processing/ copy still
    carrying this claim's token -- dead-thread cleanup then requeued a job
    that had already finished. If the rename fails, the processing/ record
    already carries the terminal status and no token: no owner's token
    matches it, and ``_stage_and_requeue`` completes the move rather than
    requeueing it.
    """
    data.pop(CLAIM_TOKEN_FIELD, None)
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
    atomic_write_json(job_path, data)
    _rename(job_path, new_path)
    return new_path


def retry(
    job_path: Path,
    *,
    delay_sec: int = 60,
    root: Path | None = None,
    reason: str | None = None,
    claim_token: str | None = None,
    count_attempt: bool = True,
) -> Path | None:
    """Bump attempts, set not_before to now+delay, and move back to pending/.

    ``count_attempt=False`` leaves ``attempts`` unchanged (a handler deferral).
    It is applied here, inside the transition, because a correction written
    after the publish could land on a newer generation of the same stem: once
    the lock is released another worker can claim, run and retry the pending/
    copy, and a late rewrite would reset that generation's counter.

    The record goes through the same stage -> rewrite -> no-clobber publish
    path as a shutdown requeue, so an existing pending/ job is never
    overwritten. Returns the pending/ path, or None when the caller no longer
    owns the job (nothing is written; see ``finish``) or the publish was
    refused (the staged copy is kept for ``recover_staged_requeues``).
    """
    paths = _ensure_dirs(root)
    with _transition_lock(root):
        data = _owned_record(job_path, claim_token)
        if data is None:
            return None
        staged = _stage(job_path)
        if staged is None:
            return None
        if count_attempt:
            raw_attempts = data.get("attempts")
            attempts = int(raw_attempts) if isinstance(raw_attempts, (int, float, str)) else 0
            data["attempts"] = attempts + 1
        nb = datetime.now(UTC) + timedelta(seconds=int(delay_sec))
        data["status"] = "pending"
        data["not_before"] = nb.strftime(ISO_DATETIME_FORMAT)
        data[FIELD_UPDATED_AT] = iso_now()
        data.pop(CLAIM_TOKEN_FIELD, None)
        if reason:
            data["last_error"] = str(reason)
        atomic_write_json(staged, data)
        new_path = _job_path(paths["pending"], job_path.stem)
        return new_path if _publish_no_clobber(staged, new_path) else None


_REQUEUE_STAGING_SUFFIX = ".requeue"
# Written by the shutdown drain before each requeue attempt and removed once
# the attempt returns; one that survives marks a drain that timed out, failed,
# or was killed mid-call, with the processing/ record possibly untouched.
# The full marker filename is "<job_id>.json.shutdown-timeout.<token>", with
# an empty trailing segment when the original claim had no token to record.
# recover_shutdown_timeout_markers() reads it at startup, passes the encoded
# token through as requeue_processing's claim_token, and force-requeues the
# corresponding processing/ record regardless of job_timeout -- but only if
# that atomic ownership check still finds the original claim in place.
_SHUTDOWN_TIMEOUT_MARKER_SUFFIX = ".shutdown-timeout"
SHUTDOWN_REQUEUE_REASON = "requeued-on-shutdown"


# A marker name is "<job_id>.json.shutdown-timeout.<token>", where <token> is
# empty or a claim token as start_processing writes it (uuid4().hex). Anything
# else merely contains the marker text -- a staged requeue or record of a job
# whose id embeds it -- and must not be parsed, let alone unlinked, as a marker.
_SHUTDOWN_MARKER_RE = re.compile(
    rf"(?P<job_id>.+){re.escape(_JOB_SUFFIX + _SHUTDOWN_TIMEOUT_MARKER_SUFFIX)}"
    r"\.(?P<token>[0-9a-f]{32})?"
)


def _shutdown_marker_path(job_id: str, claim_token: str | None, root: Path | None) -> Path:
    """Return the marker path for ``job_id``/``claim_token`` (see _SHUTDOWN_MARKER_RE).

    Raises ValueError for a token recovery could not parse back: such a
    marker would be ignored at startup, so writing it would only look like
    recovery intent.
    """
    token_part = claim_token if claim_token is not None else ""
    name = f"{job_id}{_JOB_SUFFIX}{_SHUTDOWN_TIMEOUT_MARKER_SUFFIX}.{token_part}"
    if not _SHUTDOWN_MARKER_RE.fullmatch(name):
        raise ValueError(f"not a valid shutdown-timeout marker name: {name!r}")
    return _ensure_dirs(root)["processing"] / name


def write_shutdown_timeout_marker(
    job_id: str, claim_token: str | None, root: Path | None = None
) -> None:
    """Write a zero-byte sentinel beside processing/<job_id>.json.

    Written by the shutdown drain before each requeue attempt, so a drain
    that times out, fails, or is killed while the call is stalled still
    leaves durable recovery intent.  recover_shutdown_timeout_markers() reads it at
    startup and force-requeues the corresponding record regardless of
    job_timeout.  Writing requires no lock: the file sits beside the job
    record and does not modify it.

    ``claim_token`` is encoded into the marker's filename (a bare hex uuid,
    filename-safe with no separators of its own) so recovery can pass it as
    ``requeue_processing``'s ``claim_token`` and get the same atomic
    ownership check every other requeue path uses. A token that is neither
    empty nor 32 hex digits raises ValueError: recovery would not parse the
    marker back. Without the token, recovery
    would requeue by job id alone: if another worker's own reaper reclaims
    this stem with a new token before the next startup runs, an
    unauthenticated recovery would steal that worker's live claim instead of
    the original stranded one. Pass ``None`` when the drain attempt itself
    had no token to record (mirrors ``requeue_processing``'s own
    "explicit None still verifies tokenless" semantics).
    """
    _shutdown_marker_path(job_id, claim_token, root).touch()


def remove_shutdown_timeout_marker(
    job_id: str, claim_token: str | None, root: Path | None = None
) -> None:
    """Remove the shutdown-timeout marker ``write_shutdown_timeout_marker`` wrote.

    Called once the drain's requeue_processing call returns normally: the
    marker's recovery intent is no longer needed, and leaving it in place
    would make recover_shutdown_timeout_markers() attempt a spurious requeue
    of a processing/ record that is already gone at the next startup. A
    missing marker (it was never written, or already cleaned up) is a no-op,
    not an error -- this is always called defensively.
    """
    _shutdown_marker_path(job_id, claim_token, root).unlink(missing_ok=True)


def _discard_shutdown_marker(marker: Path) -> None:
    """Unlink ``marker``; log a failure instead of raising.

    Used inside ``recover_shutdown_timeout_markers``' loop, where one
    undeletable marker must not abandon recovery of the rest. A marker left
    behind is harmless: the next recovery re-verifies it by claim token, and
    once its record is gone it is removed as stale.
    """
    try:
        marker.unlink(missing_ok=True)
    except OSError as exc:
        _log.warning(
            "Could not remove shutdown-timeout marker %s: %s; "
            "left for the next recovery",
            marker.name,
            exc,
        )


def recover_shutdown_timeout_markers(root: Path | None = None) -> list[str]:
    """Requeue any processing/ jobs that have a shutdown-timeout marker.

    Called at startup alongside recover_staged_requeues.  For each
    ``*.json.shutdown-timeout.<token>`` sentinel in processing/:

    - If the corresponding ``*.json`` record still exists, call
      requeue_processing with the token encoded in the marker's filename as
      ``claim_token`` (an empty token segment means the original drain
      attempt itself had no token, and is passed through as ``None`` so the
      same atomic tokenless-verification path applies). This is the same
      ownership check every other requeue call makes: if another worker's
      own reaper has since reclaimed this stem with a different token, the
      requeue is refused rather than stealing that worker's live claim, and
      the marker is removed as stale (the original job this marker was for
      is gone regardless of what currently occupies the stem).
    - Once the processing/ record is gone (finished or already requeued), the
      marker is removed so it does not trigger a spurious double-requeue.

    A filesystem error on one marker (probing its record, requeueing it, or
    unlinking the marker) is logged and that marker is left for the next
    recovery; it never aborts recovery of the others. ``run_daemon`` and
    ``run_once`` also isolate each startup recovery via ``_recover_at_start``.

    Returns the job ids that were requeued (not just recovered).
    """
    paths = _ensure_dirs(root)
    requeued: list[str] = []
    for marker in list(paths["processing"].iterdir()):
        parsed = _SHUTDOWN_MARKER_RE.fullmatch(marker.name)
        if parsed is None:
            continue
        job_id = parsed["job_id"]
        expected_token = parsed["token"]
        proc_path = _job_path(paths["processing"], job_id)
        try:
            if not proc_path.exists():
                # Job already finished or requeued on its own; clean up stale marker.
                _discard_shutdown_marker(marker)
                continue
            result = requeue_processing(
                job_id, reason=SHUTDOWN_REQUEUE_REASON, root=root, claim_token=expected_token
            )
        except Exception as exc:
            _log.warning(
                "Could not recover shutdown-timeout job %s: %s; "
                "marker left in place for next startup attempt",
                job_id,
                exc,
            )
            continue
        if result is not None:
            requeued.append(job_id)
            _log.info("recovered shutdown-timeout job %s", job_id)
        else:
            # Either the job already left processing/, or (with a token
            # recorded) a different worker's claim now occupies the stem --
            # requeue_processing refuses to touch it in that case rather than
            # stealing that worker's live claim. Either way the marker refers
            # to a job that is no longer this marker's to recover.
            _log.debug(
                "Shutdown-timeout marker for %s not requeued (gone, already "
                "pending, or claim since reclaimed by another worker)",
                job_id,
            )
        # Remove the marker regardless: either the job was requeued, or it is
        # gone/reclaimed and a stale marker on the next startup would be a
        # no-op (or worse, another refused steal attempt) anyway.
        _discard_shutdown_marker(marker)
    return requeued


def _normalize_requeued(data: dict[str, object], reason: str) -> None:
    """Set the metadata every requeued pending/ record carries.

    Eligible immediately, ``reason`` as ``last_error``, attempts untouched,
    and no claim token: the next claim writes its own.
    Shared by every path that publishes a staged record, so they cannot drift.
    """
    now = iso_now()
    data["status"] = "pending"
    data["not_before"] = now
    data[FIELD_UPDATED_AT] = now
    data["last_error"] = str(reason)
    data.pop(CLAIM_TOKEN_FIELD, None)


def _rewrite_staged(staged: Path, reason: str, *, only_if_unnormalized: bool) -> None:
    """Normalise a staged record's metadata in place, before it is published.

    ``only_if_unnormalized`` leaves a record that already says
    ``status: pending`` untouched: its requeue (or retry) finished the
    rewrite before it was interrupted. An unreadable record is published
    as-is rather than replaced with near-empty metadata; stale metadata
    beats a lost job.
    """
    data = safe_load_json(staged, default=None)
    if not isinstance(data, dict):
        _log.debug("Staged job %s is not a JSON object; publishing unchanged", staged)
        return
    if only_if_unnormalized and data.get("status") == "pending":
        return
    _normalize_requeued(data, reason)
    atomic_write_json(staged, data)


class _NoClobberRaceLost(Exception):
    """Raised when the no-hardlink fallback in ``_copy_exclusive`` cannot rule
    out a rival's record being overwritten.

    Without hard links there is no single syscall that both (a) fails instead
    of replacing an existing ``dest`` and (b) never makes an in-progress write
    visible as an empty file — the two properties this function's docstring
    promises trade off against each other once hard links are unavailable.
    Rather than silently pick one, the no-hardlink path performs the
    existence check, replace, and a post-replace content re-read, and raises
    this when the post-replace read does not match what was just written —
    the only case that distinguishes "we published cleanly" from "a rival
    landed a write in the gap between the check and the replace". The caller
    (``_publish_no_clobber``) treats this the same as ``staged`` vanishing:
    the record is left alone rather than assumed published.
    """


def _copy_exclusive(staged: Path, dest: Path) -> None:
    """Create ``dest`` with ``staged``'s bytes; FileExistsError if it exists.

    Writes bytes to a hidden temp file in the same directory, fsyncs them, then
    publishes the temp file to ``dest`` atomically so that ``list_pending()``
    and ``start_processing()`` can never observe a partially written record:
    the destination is either absent or fully written.

    No-clobber is preserved: ``os.link(tmp, dest)`` raises ``FileExistsError``
    atomically if ``dest`` already exists. On filesystems where hard links are
    unavailable even within the same directory, there is no single syscall
    that is simultaneously (a) a no-replace publish and (b) guaranteed never
    to expose a partially-written ``dest``: claiming ``dest`` itself with
    ``O_CREAT|O_EXCL`` would publish an empty file before the content write
    completes -- reopening the exact defect ``PRRT_kwDOQr1kjM6mf6TU`` fixed --
    while renaming a fully-written temp file over ``dest`` is atomic but
    always replaces, never fails, so it cannot detect a rival's record at all.

    The fallback therefore does both: check ``dest.exists()`` first (so an
    already-present rival is refused, matching the hard-link path), then
    publish via ``tmp.replace(dest)``, then immediately re-read ``dest`` and
    compare it against the bytes just written. A mismatch means a rival's
    write landed in the gap between the check and the replace and this
    replace overwrote it (or a still-later rival overwrote this one before
    the re-read) -- ``_NoClobberRaceLost`` is raised so the caller treats the
    outcome as unpublished rather than trusting a replace that may have
    destroyed another worker's record. The window is narrow (bounded by one
    replace and one read, not by however long ``_transition_lock`` is held
    elsewhere) and every existing caller already runs under that lock for
    every lock-aware writer; the residual risk is ``enqueue()``, which
    deliberately writes pending/ without the lock for a brand-new job, and
    this check is what catches a collision with it.
    """
    content = staged.read_bytes()
    tmp = dest.with_name(f"{_publish_temp_prefix(dest)}{uuid.uuid4().hex}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    # Publish atomically: os.link raises FileExistsError if dest exists,
    # preserving the no-clobber guarantee.
    try:
        os.link(tmp, dest)
    except FileExistsError:
        tmp.unlink(missing_ok=True)
        raise
    except OSError:
        # Hard links unavailable even within the directory. dest.exists()
        # never creates a placeholder there, so a pre-existing rival is
        # refused exactly as the hard-link path refuses one.
        if dest.exists():
            tmp.unlink(missing_ok=True)
            raise FileExistsError(dest)
        # Second existence check, immediately before the replace, to catch a
        # rival that created dest in the gap between the check above and now.
        # This does not eliminate the window but narrows it to the shortest
        # possible interval before the replace, making any remaining gap
        # detectable by the post-replace content re-read below (which catches
        # a rival that replaces us after our own write).
        if dest.exists():
            tmp.unlink(missing_ok=True)
            raise FileExistsError(dest)
        tmp.replace(dest)
        # Detect a rival that claimed dest in the narrow gap between the
        # second check above and this replace: re-read what is on disk now and
        # compare it to the bytes we just wrote. A mismatch means a rival
        # overwrote our record (or we overwrote theirs and a still-later rival
        # then overwrote us) -- raise so the caller leaves staged in place for
        # recover_staged_requeues rather than trusting a publish that may have
        # destroyed another worker's record.
        try:
            observed = dest.read_bytes()
        except FileNotFoundError:
            # Gone already -- something else raced past our own publish.
            raise _NoClobberRaceLost(dest) from None
        if observed != content:
            raise _NoClobberRaceLost(dest)
        return
    tmp.unlink(missing_ok=True)


def _publish_temp_prefix(dest: Path) -> str:
    """Name prefix of the hidden temp files ``_copy_exclusive`` writes for ``dest``."""
    return f".{dest.name}.tmp."


def _discard_publish_temps(dest: Path) -> None:
    """Remove ``_copy_exclusive`` temp files left beside ``dest`` that are ``dest``.

    A crash after ``os.link(tmp, dest)`` but before ``tmp.unlink()`` leaves the
    temp name as a second link to the published record. Only temps that are
    the same inode as ``dest`` are removed, so nothing but a redundant name
    for the record already published is ever deleted.
    """
    for tmp in dest.parent.glob(f"{glob_escape(_publish_temp_prefix(dest))}*"):
        try:
            if tmp.samefile(dest):
                tmp.unlink()
        except OSError:
            pass  # nosec B110 - a leftover name is harmless; the record itself is published


def _is_own_interrupted_publish(staged: Path, dest: Path) -> bool:
    """True if ``dest`` is ``staged``'s record from an earlier, interrupted publish.

    An earlier publish can create ``dest`` and then crash before
    ``staged.unlink()``. Treating that ``dest`` as a rival strands ``staged``:
    once ``dest`` is claimed into processing/, a later recovery pass finds
    pending/ free and publishes ``staged`` again, running the job twice.

    Inode identity recognises only the direct hard-link publish. The
    ``_copy_exclusive`` fallback links ``dest`` to its hidden temp file (or
    renames the temp over ``dest``), so ``dest`` is never ``staged``'s inode
    there, and a retry's ``os.link(staged, dest)`` reports FileExistsError
    before the fallback is ever reached. Identical bytes are therefore also
    recognised: every publisher writes ``staged`` before publishing it, so
    ``dest`` holds exactly those bytes. A rival with a different record (or an
    unreadable ``dest``) is not a match and is left for the caller to refuse.
    """
    try:
        return dest.samefile(staged) or dest.read_bytes() == staged.read_bytes()
    except OSError:
        return False  # nosec B110 - unreadable dest is treated as a rival, not a self-match


def _publish_no_clobber(staged: Path, dest: Path) -> bool:
    """Move ``staged`` to ``dest`` unless ``dest`` already holds another file.

    A hard link publishes atomically and fails if ``dest`` exists, so a
    pending/ job with the same id is never overwritten. If ``dest`` is
    already ``staged``'s record -- the same inode or identical bytes, left by
    an earlier publish that stopped before its unlink (see
    ``_is_own_interrupted_publish``) -- only the staging name and any leftover
    temp link are removed. Without hard links the record
    is copied into an exclusively created ``dest``; a crash mid-copy can
    leave a partial ``dest`` beside the intact staged file, never a lost job.
    Returns False when ``staged`` is gone (published by someone else) or,
    leaving ``staged`` in place for a later recovery, when ``dest`` is a
    different file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(staged, dest)
    except FileExistsError:
        if not _is_own_interrupted_publish(staged, dest):
            _log.warning("Not publishing %s: %s already exists", staged.name, dest)
            return False
        _discard_publish_temps(dest)
    except FileNotFoundError:
        _log.debug("Not publishing %s: it is already gone", staged.name)
        return False
    except OSError:
        # No hard links on this filesystem: exclusive create, never check-then-replace.
        try:
            _copy_exclusive(staged, dest)
        except FileExistsError:
            if _is_own_interrupted_publish(staged, dest):
                _discard_publish_temps(dest)
                staged.unlink(missing_ok=True)
                return True
            _log.warning("Not publishing %s: %s already exists", staged.name, dest)
            return False
        except FileNotFoundError:
            _log.debug("Not publishing %s: it is already gone", staged.name)
            return False
        except _NoClobberRaceLost:
            # A rival (most likely a lock-free enqueue() of the same id)
            # claimed dest in the narrow check-then-replace gap this
            # filesystem class cannot close atomically. staged is left in
            # place for recover_staged_requeues rather than trusting a
            # replace that may have destroyed the rival's record.
            _log.warning(
                "Not publishing %s: lost a no-clobber race for %s", staged.name, dest
            )
            return False
    staged.unlink(missing_ok=True)
    return True


def _stage(src: Path) -> Path | None:
    """Rename ``src`` to its staging name; None if ``src`` is already gone.

    The staging name matches no queue listing, so the rename is an atomic
    claim that no other worker can race.
    """
    staged = src.with_name(src.name + _REQUEUE_STAGING_SUFFIX)
    try:
        src.rename(staged)
    except FileNotFoundError:
        return None
    return staged


def _complete_interrupted_finish(src: Path, data: object, root: Path) -> bool:
    """Move ``src`` to done/ or error/ if ``finish`` already rewrote it; True if moved.

    Call with ``_transition_lock`` held. A processing/ record whose status is
    terminal is one whose ``finish`` failed at its final rename (see
    ``_write_finished``): the job already ran to an outcome, so requeueing it
    would run it again. Checked before staging, so a failed move leaves the
    record where it was rather than as a staged file recovery would publish
    to pending/. ``data`` is ``src``'s record as read under the lock.
    """
    status = data.get("status") if isinstance(data, dict) else None
    if status not in _TERMINAL_FOLDERS:
        return False
    _rename(src, _job_path(root / str(status), src.stem))
    _log.warning("Completed interrupted finish of job %s into %s/", src.stem, status)
    return True


def _stage_and_requeue(
    src: Path,
    pending_dir: Path,
    reason: str,
    *,
    expected_token: str | None | object = _NO_TOKEN_CHECK,
    lock_timeout: float | None = None,
) -> Path | None:
    """Claim ``src`` from processing/ by renaming it, normalise it, then publish it.

    Runs under ``_transition_lock`` for the queue that owns ``pending_dir``,
    so no other worker can pick up the pending/ copy before its metadata is
    written and recovery never sees it half-done. Returns the pending/ path,
    or None when ``src`` was already gone (nothing is written) or the publish
    was refused (the staged file stays for ``recover_staged_requeues``).
    A record ``finish`` already rewrote to a terminal status is moved to its
    terminal folder instead and None is returned (see
    ``_complete_interrupted_finish``): requeueing it would run it again.

    When ``expected_token`` is given -- anything other than the module's
    ``_NO_TOKEN_CHECK`` sentinel, including an explicit ``None`` -- the
    record's claim token is compared against it under the lock, before
    staging. A mismatch means the job was reclaimed while the caller was
    deciding to requeue it; nothing is moved and None is returned, leaving
    the new claim undisturbed. Passing ``None`` explicitly checks that the
    record STILL carries no token (the caller's own claim failed its metadata
    write, so it never had one) rather than skipping the check: a bare
    ``None`` default could not tell "no token to compare" apart from "caller
    has no token concept at all", because a missing claim token is itself
    represented as ``None`` -- that ambiguity is exactly what let two call
    sites requeue a stem with no ownership check at all.

    ``lock_timeout`` is forwarded to ``_transition_lock``: when given, the
    call raises ``_TransitionLockTimeout`` instead of blocking indefinitely.
    All callers use the default (None = block forever) except
    ``drain_live_threads``, which passes a deadline-derived budget to avoid
    exceeding the shutdown grace period.
    """
    with _transition_lock(pending_dir.parent, timeout=lock_timeout):
        # Every writer of a processing/ record holds this lock, so the record
        # read here is the one staged below. Checking it before staging means
        # a refusal leaves the record untouched: there is no staged file to
        # restore, and so none that per-tick recovery could publish while
        # another worker still owns the claim.
        data = safe_load_json(src, default=None)
        if _complete_interrupted_finish(src, data, pending_dir.parent):
            return None
        if expected_token is not _NO_TOKEN_CHECK and (
            not isinstance(data, dict) or data.get(CLAIM_TOKEN_FIELD) != expected_token
        ):
            _log.debug(
                "Skipping requeue of %s: gone, or claim token changed (job was reclaimed)",
                src.stem,
            )
            return None
        staged = _stage(src)
        if staged is None:
            return None
        try:
            _rewrite_staged(staged, reason, only_if_unnormalized=False)
        except Exception as exc:  # still move the job: stale metadata beats a stranded file
            _log.debug("Failed to update metadata for requeued job %s: %s", src.stem, exc)
        new_path = _job_path(pending_dir, src.stem)
        return new_path if _publish_no_clobber(staged, new_path) else None


def requeue_processing(
    job_id: str,
    *,
    reason: str,
    root: Path | None = None,
    claim_token: str | None | object = _NO_TOKEN_CHECK,
    lock_timeout: float | None = None,
) -> Path | None:
    """Move processing/<job_id> back to pending/ without consuming an attempt.

    The job becomes eligible immediately and records ``reason`` as
    ``last_error``. Returns the pending/ path, or None when the job is no
    longer in processing/ (it finished or was moved elsewhere first), in
    which case nothing is written, or when pending/ already holds a job with
    that id (the staged copy is kept for ``recover_staged_requeues``).

    Unlike ``retry``, a job that vanished before the claim is never
    recreated from empty metadata, and no other worker can claim the
    pending/ copy before its metadata is written; see ``_stage_and_requeue``.

    ``claim_token``, when given -- including an explicit ``None`` -- is
    revalidated under the transition lock (see ``_stage_and_requeue``'s
    ``expected_token``): identifying the job by stem alone is not enough when
    another worker's stale-job reaper, or a finish-then-reclaim, can put a
    *different* claim at the same stem between the caller's decision to
    requeue and this call acquiring the lock. A mismatch means the stem is
    now owned by someone else, so nothing is written and the new claim is
    left alone. Pass ``None`` explicitly (not by omission) when the caller's
    own claim never had a token to begin with -- a failed ``start_processing``
    metadata write -- so this still verifies the record has not since been
    claimed by someone else with a real token; leaving the parameter
    unset skips the check entirely, for callers with no token to compare.

    ``lock_timeout`` is forwarded to ``_stage_and_requeue`` and from there to
    ``_transition_lock``. All callers use the default (None = block forever)
    except ``drain_live_threads``, which passes a deadline-derived budget to
    avoid exceeding the shutdown grace period.
    """
    paths = _ensure_dirs(root)
    return _stage_and_requeue(
        _job_path(paths["processing"], job_id),
        paths["pending"],
        reason,
        expected_token=claim_token,
        lock_timeout=lock_timeout,
    )


def recover_staged_requeues(root: Path | None = None) -> list[str]:
    """Complete any interrupted staged requeue in processing/.

    A crash between staging a job and publishing it leaves a
    ``*.json.requeue`` file that ``_list_job_paths`` never matches (it
    filters to ``suffix == ".json"``). Every queue-consuming entry point
    (``worker daemon`` and ``worker run-once``) calls this before claiming
    work; it publishes each staged file to pending/ and returns the
    recovered job ids. It holds ``_transition_lock`` throughout, so a staged
    file another live worker is still writing is never touched.

    A crash can also land before the staged metadata was rewritten, leaving
    ``status: processing``. Such a record is normalised exactly as
    ``requeue_processing`` would have, with ``SHUTDOWN_REQUEUE_REASON`` as
    ``last_error``; one already rewritten is published unchanged. An
    existing pending/ job with the same id is never overwritten, and a
    second call is a no-op.
    """
    paths = _ensure_dirs(root)
    recovered: list[str] = []
    with _transition_lock(root):
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
                # Warning, not debug: the staged file stays invisible to every
                # listing until a later pass succeeds, so a failure is worth seeing.
                _log.warning("Failed to recover staged requeue for job %s: %s", job_id, exc)
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

    Used by requeue_error(), which writes the new job file first and then
    removes the old one. The message stays generic because the path itself
    identifies which queue directory the job came from.
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
    claim_token: str | None = None


def _reap_move_to_pending(ctx: ReapJobContext, log: logging.Logger) -> bool:
    """Requeue a stale processing job, writing its metadata before it is published.

    Passes the claim token observed before the lock to ``_stage_and_requeue``,
    which revalidates it under the lock.  A token mismatch means the job was
    reclaimed between the stale check and the transition; nothing is written.
    """
    reason = f"reaped after {ctx.age}s (timeout {ctx.job_timeout}s)"
    try:
        new_path = _stage_and_requeue(
            ctx.p, ctx.paths["pending"], reason, expected_token=ctx.claim_token
        )
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
    """Reap one processing job if stale. Returns its job_id if reaped, else None.

    A record that is not a JSON object is skipped with a warning rather than
    raising out of the caller's loop and leaving every later job unreaped.
    """
    data = safe_load_json(p, default={})
    if not isinstance(data, dict):
        log.warning("Not reaping %s: record is not a JSON object", p.name)
        return None
    started = _reap_resolve_start_time(data, p)
    if not started:
        return None

    age = int((now - started).total_seconds())
    effective_timeout = _reap_effective_timeout(data, job_timeout)
    if effective_timeout <= 0 or age < effective_timeout:
        return None

    job_id = p.stem
    # Capture the claim token observed before acquiring the transition lock.
    # _reap_move_to_pending passes it to _stage_and_requeue, which revalidates
    # it under the lock: a mismatch means this generation of the job finished
    # and was re-claimed while we were deciding to requeue it.
    observed_token = str(t) if (t := data.get(CLAIM_TOKEN_FIELD)) else None
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
        claim_token=observed_token,
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
