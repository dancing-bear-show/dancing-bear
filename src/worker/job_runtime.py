"""Worker job runtime: config, job context, processing pipeline, and daemon loop.

Split out of commands.py to separate runtime concerns from CLI command classes.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType

from core.cli_errors import UsageError
from core.cli_output import OutputWriter
from core.pipeline import BaseProducer, RequestConsumer, ResultEnvelope, SafeProcessor
from worker._helpers import (
    log_perf_jsonl,
    get_repo_root,
)
from worker import queue_ops as q
from worker.handlers import REGISTRY as HANDLERS

logger = logging.getLogger(__name__)

# Signals that ask the daemon to stop. launchd stops an agent with SIGTERM,
# so treating SIGTERM like Ctrl-C is what lets the drain run under launchd.
_STOP_SIGNALS: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT)

_SignalHandler = Callable[[int, FrameType | None], object] | int | None

# last_error for a claimed job requeued because its worker thread never started.
_THREAD_START_FAILED_REASON = "requeued-thread-start-failed"
# last_error for a claimed job requeued because its thread died with an unhandled
# exception (outside the SafeProcessor guard) and left a processing/ record behind.
_THREAD_DIED_REASON = "requeued-thread-died-unhandled"

# ============================================================================
# Helpers
# ============================================================================


def _finish_or_retry(
    proc_path: Path, ctx: JobContext, config: WorkerConfig, reason: str
) -> None:
    """Finish the job as errored if attempts are exhausted, else retry it."""
    attempts = ctx.attempts + 1
    if attempts >= ctx.max_attempts:
        q.finish(proc_path, success=False, error_msg=reason, claim_token=ctx.claim_token)
    else:
        q.retry(
            proc_path, delay_sec=config.backoff, reason=reason, claim_token=ctx.claim_token
        )


def _write_shutdown_timeout_marker(job_id: str, claim_token: str | None, root: Path) -> None:
    """Delegate to queue_ops to write a shutdown-timeout sentinel for ``job_id``.

    ``claim_token`` is the token this runner observed for the stem before the
    lock timed out; it is encoded into the marker so recovery can verify
    ownership atomically instead of requeueing by stem alone.
    """
    q.write_shutdown_timeout_marker(job_id, claim_token, root)


def _remove_shutdown_timeout_marker(job_id: str, claim_token: str | None, root: Path) -> None:
    """Delegate to queue_ops to remove a shutdown-timeout marker for ``job_id``.

    Called when a post-deadline requeue that raced ahead of its own
    precautionary marker write succeeds after all, so the marker's recovery
    intent is no longer needed.
    """
    q.remove_shutdown_timeout_marker(job_id, claim_token, root)


def _mark_for_recovery(stem: str, token: str | None) -> None:
    """Write the shutdown-timeout marker for ``stem``; log on failure.

    The marker is the queue's durable requeue intent: the next worker start
    (``recover_shutdown_timeout_markers``) requeues the processing/ record if
    ``token`` still matches it. The marker encodes ``token`` so recovery
    revalidates ownership under the transition lock instead of requeueing by
    stem alone.
    """
    try:
        _write_shutdown_timeout_marker(stem, token, q.QUEUE_ROOT)
    except Exception:  # nosec B110 - logged; the job may stay in processing/ if the process dies now
        logger.exception(
            "could not write shutdown-timeout marker for job %s; "
            "job may remain stranded in processing/ if shutdown does not complete",
            stem,
        )


def _release_unrun_claim(stem: str, token: str | None, reason: str) -> bool:
    """Requeue a claim this worker will not run; return False if the requeue raised.

    One policy for every site that gives a claim up without running it (a
    tokenless claim in ``process_one`` and ``_start_batch``, a thread that
    never started in ``_abandon_claim``): one requeue attempt, and when it
    raises, an error log naming the stem plus a recovery marker, so the
    processing/ record is never left with nothing tracking it. The next
    worker start requeues it from the marker; the daemon sites also keep a
    registry entry so ``_prune_live_threads`` retries every tick. No thread
    ever ran these claims, so the marker names no drain owner and any
    worker's recovery may consume it. A marker left after a later successful
    retry is stale and is discarded at the next start once the record is
    gone or carries a different token.

    ``token`` is passed through as ``claim_token`` (an explicit ``None`` for a
    tokenless claim), so the requeue revalidates ownership under the
    transition lock rather than moving a stem someone else has since claimed.
    """
    try:
        result = q.requeue_processing(stem, reason=reason, root=q.QUEUE_ROOT, claim_token=token)
    except Exception:  # nosec B110 - logged; a recovery marker keeps the claim tracked
        logger.exception(
            "could not requeue unrun claim for job %s; leaving a recovery marker "
            "for the next worker start",
            stem,
        )
        _mark_for_recovery(stem, token)
        return False
    if result is None:
        logger.warning(
            "unrun claim for job %s not requeued (already gone or reclaimed)", stem
        )
    return True


def _recover_at_start() -> None:
    """Run both startup recoveries, each isolated so one failure skips neither.

    Staged requeues (``*.json.requeue``) and shutdown-timeout markers are
    independent: an error from one must not stop the other or abort the
    caller's startup. Anything not recovered stays on disk; the daemon tick
    retries staged requeues every interval, and markers are retried at the
    next start.
    """
    recoveries: tuple[tuple[str, Callable[..., list[str]]], ...] = (
        ("staged requeues", q.recover_staged_requeues),
        ("shutdown-timeout markers", q.recover_shutdown_timeout_markers),
    )
    for label, recover in recoveries:
        try:
            recover(root=q.QUEUE_ROOT)
        except Exception:  # nosec B110 - logged; left on disk for a later pass
            logger.exception("could not recover %s at startup", label)


def _processing_stems(root: Path) -> set[str]:
    """Return the job stems currently in processing/ under ``root``."""
    folder = q._ensure_dirs(root)["processing"]
    return {p.stem for p in q._list_job_paths(folder)}


def _claimable(
    pending: list[tuple[Path, dict[str, object]]], skip: set[str]
) -> list[tuple[Path, dict[str, object]]]:
    """Drop pending jobs in ``skip`` or whose id is already in processing/.

    ``start_processing`` refuses such a duplicate, so selecting it would spend
    a slot of the ``allowed`` slice on a claim that cannot succeed -- every
    tick, while the original runs. The claim itself re-checks under the lock.
    """
    busy = skip | _processing_stems(q.QUEUE_ROOT)
    return [(p, d) for p, d in pending if p.stem not in busy]


def _reap_stale_unowned(job_timeout: int, root: Path, owned: set[str]) -> list[str]:
    """Reap stale processing/ jobs under ``root``, skipping stems in ``owned``.

    Mirrors ``q.reap_stale_processing_jobs`` but never touches a job a live
    local thread is still executing: moving it back to pending/ would let a
    later tick run it a second time while the original is still running.
    """
    paths = q._ensure_dirs(root)
    now = datetime.now(UTC)
    log = logging.getLogger(q.__name__)
    reaped: list[str] = []
    for p in q._list_job_paths(paths["processing"]):
        if p.stem in owned:
            continue
        job_id = q._reap_one_job(p, job_timeout, paths, now, log)
        if job_id:
            reaped.append(job_id)
    return reaped


def _make_stop_handler(stop: threading.Event) -> Callable[[int, FrameType | None], None]:
    """Return a signal handler that only sets ``stop``.

    Kept to one Event.set so it is safe to run between any two bytecodes of
    the main thread; the daemon loop does the actual shutdown work.
    """

    def _handler(signum: int, _frame: FrameType | None) -> None:
        stop.set()

    return _handler


def _install_stop_handlers(stop: threading.Event) -> dict[signal.Signals, _SignalHandler]:
    """Route SIGTERM and SIGINT to ``stop``; return the handlers they replace.

    Python only allows signal handlers to be installed from the main thread,
    so a daemon run from any other thread installs nothing and stops via the
    Event alone.
    """
    if threading.current_thread() is not threading.main_thread():
        return {}
    handler = _make_stop_handler(stop)
    previous: dict[signal.Signals, _SignalHandler] = {}
    for sig in _STOP_SIGNALS:
        previous[sig] = signal.getsignal(sig)
        signal.signal(sig, handler)
    return previous


def _restore_signal_handlers(previous: dict[signal.Signals, _SignalHandler]) -> None:
    """Reinstate handlers captured by ``_install_stop_handlers``."""
    for sig, handler in previous.items():
        # getsignal returns None for a handler not installed from Python;
        # SIG_DFL is the closest installable equivalent.
        signal.signal(sig, signal.SIG_DFL if handler is None else handler)


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass
class WorkerConfig:
    """Configuration for worker daemon/processing."""

    backoff: int = 60
    max_per_tick: int = 3
    max_inflight: int = 0
    job_timeout: int = 0
    interval: float = 5.0
    # Seconds the daemon waits for running jobs after a stop request before
    # requeueing them; also bounds the requeue's transition-lock wait, but not
    # its filesystem I/O. Kept below launchd's default ExitTimeOut (20s) to
    # leave the requeue room before SIGKILL; a requeue killed mid-way is
    # recovered at the next start from its shutdown-timeout marker.
    shutdown_grace: float = 10.0


@dataclass
class JobContext:
    """Context for processing a single job."""

    job_path: Path
    job_data: dict[str, object]
    job_type: str
    attempts: int
    max_attempts: int
    # This worker's claim on the processing/ file (see q.claim_token); outcome
    # transitions pass it so a job requeued or re-claimed elsewhere is left alone.
    claim_token: str | None = None

    @classmethod
    def from_item(
        cls,
        job_path: Path,
        job_data: dict[str, object],
        *,
        claim_token: str | None = None,
    ) -> JobContext:
        """Create JobContext from queue item."""
        raw_attempts = job_data.get("attempts") or 0
        raw_max = job_data.get("max_attempts") or 3
        return cls(
            job_path=job_path,
            job_data=job_data,
            job_type=str(job_data.get("type") or ""),
            attempts=int(raw_attempts) if isinstance(raw_attempts, (int, float, str)) else 0,
            max_attempts=int(raw_max) if isinstance(raw_max, (int, float, str)) else 3,
            claim_token=claim_token,
        )


@dataclass
class JobRequest:
    """Request payload for a single job invocation."""

    job_id: str
    payload: dict[str, object]


@dataclass
class JobResult:
    """Result of a single job invocation."""

    outcome: str
    logs: list[str]


@dataclass(frozen=True)
class OutcomeContext:
    """Bundle of state for dispatching a job outcome to queue operations."""

    proc_path: Path
    ctx: JobContext
    duration: int
    command: str
    config: WorkerConfig


# ============================================================================
# Outcome dispatch
# ============================================================================


def _handle_outcome(outcome_ctx: OutcomeContext, success: bool, out: object) -> None:
    """Dispatch a completed handler invocation to the appropriate queue operation."""
    proc_path = outcome_ctx.proc_path
    ctx = outcome_ctx.ctx
    duration = outcome_ctx.duration
    command = outcome_ctx.command
    config = outcome_ctx.config
    out_str = str(out)
    token = ctx.claim_token
    if success:
        q.finish(proc_path, success=True, result=out, claim_token=token)
        log_perf_jsonl(
            "worker", duration, args=[command, ctx.job_type, "ok"], exit_code=0
        )
    elif out_str.startswith("deferred-"):
        # Handler requested deferral — move back to pending without consuming
        # an attempt, inside the same transition as the move itself.
        q.retry(
            proc_path,
            delay_sec=config.backoff,
            reason=out_str,
            claim_token=token,
            count_attempt=False,
        )
        log_perf_jsonl(
            "worker", duration, args=[command, ctx.job_type, "deferred"], exit_code=0
        )
    elif out_str.startswith("terminal-"):
        # Handler signalled an unrecoverable failure — skip retry loop entirely.
        q.finish(proc_path, success=False, error_msg=out_str, claim_token=token)
        log_perf_jsonl(
            "worker", duration, args=[command, ctx.job_type, "terminal"], exit_code=1
        )
    else:
        status = "error" if ctx.attempts + 1 >= ctx.max_attempts else "retry"
        _finish_or_retry(proc_path, ctx, config, out_str)
        log_perf_jsonl(
            "worker", duration, args=[command, ctx.job_type, status], exit_code=1
        )


# ============================================================================
# SafeProcessor / BaseProducer pipeline wrappers
# ============================================================================


class JobSafeProcessor(SafeProcessor[JobRequest, JobResult]):
    """SafeProcessor wrapper for a single job invocation.

    Delegates to the registered handler for the job type and returns a
    JobResult carrying the outcome string and any log lines.
    """

    def __init__(self, job_type: str, job_data: dict[str, object]) -> None:
        self._job_type = job_type
        self._job_data = job_data

    def _process_safe(self, payload: JobRequest) -> JobResult:
        """Invoke the handler and return a JobResult; raises on unrecoverable error."""
        handler = HANDLERS.get(self._job_type)
        if not handler:
            raise UsageError(f"unknown handler: {self._job_type}")
        success, out = handler(self._job_data)
        outcome = "success" if success else str(out)
        logs: list[str] = [str(out)] if out else []
        return JobResult(outcome=outcome, logs=logs)


class JobResultProducer(BaseProducer):
    """BaseProducer that dispatches a completed JobResult to the queue outcome handler."""

    def __init__(
        self,
        outcome_ctx: OutcomeContext,
        writer: OutputWriter | None = None,
    ) -> None:
        super().__init__(writer)
        self._outcome_ctx = outcome_ctx

    def _produce_success(
        self, payload: JobResult, diagnostics: dict[str, object] | None
    ) -> None:
        """Dispatch outcome to queue operations based on the outcome string."""
        success = payload.outcome == "success"
        if not success:
            out_val: object = payload.outcome
        elif payload.logs:
            out_val = payload.logs[0]
        else:
            out_val = True
        _handle_outcome(self._outcome_ctx, success, out_val)


# ============================================================================
# Job Processor
# ============================================================================


class JobProcessor:
    """Processes individual jobs from the queue."""

    def __init__(self, config: WorkerConfig, command: str) -> None:
        """Initialize processor with configuration."""
        self.config = config
        self.command = command

    def process_one(self, job_path: Path, job_data: dict[str, object]) -> int:
        """Claim a pending job, then process it via ``process_claimed``.

        Returns:
            1 if processed, 0 if skipped (already claimed by another worker,
            or the claim's metadata write failed and the token could not be
            recovered)
        """
        st = time.time()
        claim = q.start_processing(job_path)

        if claim is None:
            # Already claimed by another worker
            return 0

        proc_path, token = claim
        if not token:
            # start_processing's metadata write failed: the same undefined
            # ownership state _start_batch treats as a lost claim. Requeuing
            # here (rather than calling process_claimed with claim_token=None,
            # which would run the handler and let every finish()/retry() call
            # skip its ownership check) keeps run_once consistent with the
            # daemon-tick path.
            #
            # claim_token=None (explicit, not omitted) makes requeue_processing
            # verify under the transition lock that the record still carries no
            # token, rather than requeuing this stem unconditionally: another
            # worker's reaper could have already reclaimed it with a real
            # token in the time between the metadata failure and this call.
            logger.warning(
                "worker claim token missing for job %s after start_processing; requeueing",
                job_path.stem,
            )
            # A failed requeue leaves a recovery marker (see _release_unrun_claim).
            _release_unrun_claim(job_path.stem, None, _THREAD_START_FAILED_REASON)
            return 0

        self.process_claimed(proc_path, job_data, started_at=st, claim_token=token)
        return 1

    def process_claimed(
        self,
        proc_path: Path,
        job_data: dict[str, object],
        *,
        started_at: float | None = None,
        claim_token: str | None = None,
    ) -> None:
        """Process a job this worker has already moved into processing/.

        The daemon tick claims each job itself before starting a thread on
        this method, so only confirmed claims ever run here. ``started_at``
        lets ``process_one`` include its claim in the logged duration.
        Every path ends in a queue transition (finish or retry), each passing
        ``claim_token`` so it does nothing if the job was requeued meanwhile.
        """
        st = time.time() if started_at is None else started_at
        ctx = JobContext.from_item(proc_path, job_data, claim_token=claim_token)

        # A non-object payload can never be handled — terminal failure, no retry.
        raw_payload = job_data.get("payload")
        if raw_payload is not None and not isinstance(raw_payload, dict):
            q.finish(
                proc_path,
                success=False,
                error_msg=f"invalid payload: expected object, got {type(raw_payload).__name__}",
                claim_token=claim_token,
            )
            log_perf_jsonl(
                "worker",
                int((time.time() - st) * 1000),
                args=[self.command, "invalid_payload", ctx.job_type],
                exit_code=2,
            )
            return
        base_payload: dict[str, object] = dict(raw_payload or {})

        # Resolve effective per-job timeout
        job_timeout_sec = q.effective_job_timeout(job_data, self.config.job_timeout)
        if job_timeout_sec > 0:
            base_payload["timeout"] = job_timeout_sec
        # Handlers always see an object payload, whether or not a timeout applies.
        job_data = {**job_data, "payload": base_payload}

        # Check for handler — unknown type is a terminal failure, no retry.
        handler = HANDLERS.get(ctx.job_type)
        if not handler:
            q.finish(
                proc_path,
                success=False,
                error_msg=f"unknown handler: {ctx.job_type}",
                claim_token=claim_token,
            )
            log_perf_jsonl(
                "worker",
                int((time.time() - st) * 1000),
                args=[self.command, "unknown", ctx.job_type],
                exit_code=2,
            )
            return

        # Execute handler via JobSafeProcessor; always call finish/retry even on exception.
        request = JobRequest(job_id=str(job_data.get("id") or ""), payload=dict(base_payload))
        processor = JobSafeProcessor(ctx.job_type, job_data)
        envelope: ResultEnvelope[JobResult] = processor.process(RequestConsumer(request).consume())

        duration = int((time.time() - st) * 1000)

        if not envelope.ok():
            # SafeProcessor caught an exception — treat as handler-raised error.
            reason = (envelope.diagnostics or {}).get("message", "handler raised: unknown error")
            _finish_or_retry(proc_path, ctx, self.config, str(reason))
            log_perf_jsonl(
                "worker",
                duration,
                args=[self.command, ctx.job_type, "exception"],
                exit_code=2,
            )
            return

        outcome_ctx = OutcomeContext(
            proc_path=proc_path,
            ctx=ctx,
            duration=duration,
            command=self.command,
            config=self.config,
        )
        producer = JobResultProducer(outcome_ctx)
        producer.produce(envelope)


# ============================================================================
# Daemon Runner
# ============================================================================


class DaemonRunner:
    """Runs the worker daemon loop.

    ``tick()`` is the non-blocking, DAEMON-mode tick: it starts threads for
    newly claimed jobs and returns immediately without waiting for them to
    finish, so one long-running job never blocks a later tick from claiming
    other work. Live threads are tracked in ``_live_threads`` (keyed by job
    stem) across ticks and pruned as they finish; an entry exists only for a
    job this runner claimed itself. ``run_once()`` uses a
    separate, still-blocking path (``_run_once_batch``) because
    ``worker run-once``, the workflow ``worker_queue`` dispatch stage, and
    existing tests depend on it waiting for the batch to complete before
    returning.
    """

    def __init__(self, config: WorkerConfig, processor: JobProcessor):
        """Initialize daemon with configuration and processor."""
        self.config = config
        self.processor = processor
        # Maps job stem → (thread, claim_token).  The claim_token is stored
        # alongside the thread so that drain_live_threads and _abandon_claim can
        # verify ownership before requeueing, avoiding the race where another
        # worker claimed the same stem after our thread finished or was requeued.
        self._live_threads: dict[str, tuple[threading.Thread, str | None]] = {}
        self._registry_lock = threading.Lock()
        self.stop_event = threading.Event()

    def tick(self) -> int:
        """Start newly claimed jobs without blocking; return count started.

        Never joins the threads it starts. Each job is claimed in this
        thread before its worker thread starts (see ``_start_batch``).
        Capacity counts live threads alongside the on-disk processing/
        jobs, so a finished-but-unpruned thread still holds its slot. The
        stale-job reap skips every job a live local thread still owns, so a
        slow local job is never requeued and run twice.
        """
        self._prune_live_threads()
        self._recover_staged()
        with self._registry_lock:
            owned = set(self._live_threads)
        _reap_stale_unowned(self.config.job_timeout, q.QUEUE_ROOT, owned)

        allowed = self._calculate_allowed_jobs()
        if allowed <= 0:
            return 0

        items = _claimable(q.list_pending(), set(self._live_threads))[:allowed]
        if not items:
            return 0

        return self._start_batch(items)

    def _prune_live_threads(self) -> None:
        """Requeue any unfinished processing/ records for dead threads, then drop them.

        After ``_run_guarded`` catches an exception from ``process_claimed``,
        the thread can exit while ``processing/<stem>.json`` remains on disk.
        Without this requeue step, the next tick would silently drop the registry
        entry and leave the job stranded in processing/ — ``drain_live_threads``
        can no longer see it (the stem is gone from the registry), and with
        ``job_timeout=0`` the stale-job reaper also skips it.

        ``requeue_processing`` is a no-op when the processing/ record is already
        gone (normal completion moved it), so calling it unconditionally on every
        dead entry is safe and never recreates a job that finished cleanly.

        The token is passed through as ``claim_token`` to verify ownership under
        the transition lock before staging the record, matching the same pattern
        ``drain_live_threads`` uses.

        A queue I/O or transition-lock error from ``requeue_processing`` is
        caught per stem and logged rather than left to propagate out of
        ``tick()`` and terminate ``run_daemon``: unlike a normal completion,
        a failed requeue attempt is worth retrying, so the registry entry is
        kept (not popped) on failure and this stem is tried again on a later
        tick.
        """
        with self._registry_lock:
            dead_stems = [
                (s, tok)
                for s, (t, tok) in self._live_threads.items()
                if not t.is_alive()
            ]
        for stem, token in dead_stems:
            try:
                q.requeue_processing(
                    stem,
                    reason=_THREAD_DIED_REASON,
                    root=q.QUEUE_ROOT,
                    claim_token=token,
                )
            except Exception:  # nosec B112 - retry this stem on a later tick; logged
                logger.exception(
                    "could not requeue dead thread's job %s (retrying next tick)",
                    stem,
                )
                continue
            with self._registry_lock:
                self._live_threads.pop(stem, None)

    @staticmethod
    def _recover_staged() -> None:
        """Publish staged requeues a failed transition left in processing/.

        A requeue or retry that raises after staging (a publish or rewrite
        failure) leaves a ``*.json.requeue`` file no listing matches, and a
        retry of the same stem then finds its processing/ record gone. Running
        the startup recovery every tick publishes it within one interval
        instead of at the next process start. It takes the transition lock,
        so it never touches a staged file a live transition is still writing.
        """
        try:
            q.recover_staged_requeues(root=q.QUEUE_ROOT)
        except Exception:  # nosec B110 - retried next tick; logged
            logger.exception("could not recover staged requeues (retrying next tick)")

    @staticmethod
    def _run_guarded(stem: str, target: Callable[[], int]) -> int:
        """Run a job thread's body, logging any exception it lets escape.

        An error raised outside SafeProcessor (bad job metadata, queue I/O)
        must never surface as an uncaught thread exception.
        """
        try:
            return target()
        except Exception:  # nosec B110 - thread boundary; logged, counted as processed
            logger.exception("worker job %s raised outside the handler", stem)
            return 1

    def _process_one_guarded(self, job_path: Path, job_data: dict[str, object]) -> int:
        """run_once thread target: claim and process one pending job."""
        return self._run_guarded(
            job_path.stem, lambda: self.processor.process_one(job_path, job_data)
        )

    def _process_claimed_guarded(
        self, proc_path: Path, job_data: dict[str, object], claim_token: str | None
    ) -> None:
        """Daemon-tick thread target: process a job ``_start_batch`` already claimed."""

        def _body() -> int:
            self.processor.process_claimed(proc_path, job_data, claim_token=claim_token)
            return 1

        self._run_guarded(proc_path.stem, _body)

    @staticmethod
    def _claim(job_path: Path) -> tuple[Path, str] | None:
        """Claim a pending job for this runner; None if it cannot be claimed.

        None covers both another worker winning the claim and a claim that
        raised (logged), so one bad file never stops the daemon loop.

        Returns the (path, token) tuple from ``start_processing`` so the
        caller never needs a second file-read to learn its token: reading the
        file again after ``start_processing`` releases the transition lock has
        a TOCTOU window where a stale-job reaper on another worker could
        reclaim the stem and write a new token.
        """
        try:
            return q.start_processing(job_path)
        except Exception:  # nosec B110 - skip this job; logged, the loop continues
            logger.exception("worker could not claim job %s", job_path.stem)
            return None

    def _start_batch(self, items: list[tuple[Path, dict[str, object]]]) -> int:
        """Claim each item, then start and register a thread per confirmed claim.

        The claim runs here, in the dispatching thread, before any thread is
        registered. ``_live_threads`` therefore only ever holds jobs this
        runner has moved into processing/ itself, which is what lets
        ``drain_live_threads`` requeue its entries without touching a job
        another worker claimed. Nothing is claimed once a stop is requested.

        A missing claim token means ``start_processing``'s metadata write
        failed; the claim is treated as lost and requeued so the job is not
        run without ownership tracking.

        If a thread fails to start, its registry entry is removed and its
        claim is requeued (no attempt consumed), and no further job is
        claimed this tick: the failure is usually resource exhaustion.
        """
        started = 0
        for p, d in items:
            if self.stop_event.is_set():
                break
            claim = self._claim(p)
            if claim is None:
                continue
            proc_path, token = claim
            if not token:
                # Metadata write inside start_processing failed; we cannot
                # track ownership for this claim.  Requeue it and stop — the
                # missing token means the record is in an undefined state.
                #
                # claim_token=None (explicit) verifies under the transition
                # lock that the record still carries no token before staging
                # it, rather than requeuing this stem unconditionally: a
                # stale-job reaper on another worker could already have
                # reclaimed it with a real token between the metadata failure
                # and this call.
                logger.warning(
                    "worker claim token missing for job %s after start_processing; requeueing",
                    p.stem,
                )
                if not _release_unrun_claim(p.stem, None, _THREAD_START_FAILED_REASON):
                    # Track the claim with a never-started placeholder so
                    # _prune_live_threads retries the requeue every tick.
                    self._register_unrun(p.stem, None)
                break
            t = threading.Thread(
                target=self._process_claimed_guarded,
                args=(proc_path, d, token),
                daemon=True,
            )
            with self._registry_lock:
                self._live_threads[p.stem] = (t, token)
            try:
                t.start()
            except Exception:  # nosec B110 - requeue the claim; logged, the loop continues next tick
                self._abandon_claim(p.stem, token)
                break
            started += 1
        return started

    def _abandon_claim(self, stem: str, token: str | None) -> None:
        """Undo a claim whose worker thread never started: unregister and requeue it.

        ``token`` was captured at claim time and is passed through to
        ``requeue_processing`` as ``claim_token``, which revalidates it under
        the transition lock (see ``_stage_and_requeue``'s ``expected_token``).
        A pre-lock read-then-compare here would leave the same window this
        check exists to close: another worker's stale-job reaper can move the
        just-claimed record and re-claim it between our read and the requeue,
        so the comparison must happen atomically under the lock the requeue
        itself takes, not before it.

        The registry entry is dropped only once the requeue call returns. If
        it raises, the never-started thread stays registered, so
        ``_prune_live_threads`` retries the requeue on the next tick, and a
        recovery marker covers a process that dies first (see
        ``_release_unrun_claim``).
        """
        logger.exception("worker thread for job %s failed to start; requeueing", stem)
        if not _release_unrun_claim(stem, token, _THREAD_START_FAILED_REASON):
            return
        with self._registry_lock:
            self._live_threads.pop(stem, None)

    def _register_unrun(self, stem: str, token: str | None) -> None:
        """Track a claim no thread will run so ``_prune_live_threads`` retries its requeue.

        The placeholder thread is never started, so it reports ``is_alive()``
        False and the prune treats it like a thread that already exited.
        """
        placeholder = threading.Thread(target=lambda: None, daemon=True)
        with self._registry_lock:
            self._live_threads[stem] = (placeholder, token)

    def _calculate_allowed_jobs(self) -> int:
        """Calculate how many jobs can be started based on max_inflight cap.

        In-flight is the union, by job stem, of one processing/ listing
        (ours or another worker's, e.g. a concurrent ``worker run-once``)
        and the live local threads. A single read means no interleaving can
        drop a job: a live thread counts until it is pruned whether its file
        is still in processing/ or already gone, and each
        external processing/ job counts once. A finished-but-unpruned thread
        over-counts by at most one tick, which is the conservative
        direction. When max_inflight is unbounded (<= 0), live threads are
        still capped at max_per_tick to preserve today's effective
        concurrency rather than spawning unboundedly.
        """
        with self._registry_lock:
            live_stems = set(self._live_threads.keys())
        live = len(live_stems)
        if self.config.max_inflight <= 0:
            return max(0, self.config.max_per_tick - live)
        try:
            in_flight = len(_processing_stems(q.QUEUE_ROOT) | live_stems)
        except Exception:  # nosec B110 - unreadable queue; fall back to live threads only
            in_flight = live
        return max(
            0,
            min(self.config.max_per_tick, self.config.max_inflight - in_flight),
        )

    def _run_once_batch(self) -> int:
        """Process one batch of jobs, blocking until every job finishes.

        Uses ``_calculate_allowed_jobs`` for the capacity check; the
        live-thread registry it also accounts for is unpopulated here since
        this path never starts a registered thread, so it degrades to a
        plain processing/-count check.
        """
        q.reap_stale_processing_jobs(self.config.job_timeout, root=q.QUEUE_ROOT)

        allowed = self._calculate_allowed_jobs()
        if allowed <= 0:
            return 0

        items = _claimable(q.list_pending(), set())[:allowed]
        if not items:
            return 0

        return self._process_batch(items)

    def _process_batch(self, items: list[tuple[Path, dict[str, object]]]) -> int:
        """Process a batch of jobs in parallel with threading."""
        threads: list[threading.Thread] = []
        results: list[int] = [0] * len(items)

        timeouts: list[int] = [
            q.effective_job_timeout(d, self.config.job_timeout) for _, d in items
        ]

        def _run(idx: int, pth: Path, dat: dict[str, object]) -> None:
            results[idx] = self._process_one_guarded(pth, dat)

        for i, (p, d) in enumerate(items):
            t = threading.Thread(target=_run, args=(i, p, d), daemon=True)
            try:
                t.start()
            except Exception:  # nosec B110 - unclaimed job stays pending; join what started
                # Each thread claims its own job, so an unstarted one claimed
                # nothing. Stop here and still join the started ones: raising
                # would let the process exit with their jobs half-run.
                logger.exception("worker thread for job %s failed to start", p.stem)
                timeouts = timeouts[: len(threads)]
                break
            threads.append(t)

        if any(t > 0 for t in timeouts):
            self._join_with_timeout(threads, timeouts)
        else:
            for t in threads:
                t.join()

        return sum(int(x or 0) for x in results)

    def _join_with_timeout(self, threads: list[threading.Thread], timeouts: list[int]) -> None:
        """Join threads using per-job timeouts."""
        start_time = time.time()
        for t, job_timeout in zip(threads, timeouts):
            if job_timeout <= 0:
                t.join()
                continue
            elapsed = time.time() - start_time
            remaining = max(0.0, job_timeout - elapsed)
            t.join(timeout=remaining)

    def run_once(self) -> int:
        """Run one batch, blocking until it finishes, and exit.

        Deliberately does not call ``tick()``: ``worker run-once``, the
        workflow ``worker_queue`` dispatch stage, and existing tests depend
        on this call waiting for every started job to finish before
        returning, which the non-blocking ``tick()`` no longer does.
        Like ``run_daemon`` it first publishes any staged requeue a killed
        worker left behind, which no queue listing would otherwise see.
        """
        _recover_at_start()
        self._run_once_batch()
        return 0

    def drain_live_threads(self, grace: float) -> list[str]:
        """Wait up to ``grace`` seconds for live job threads; requeue the rest.

        One deadline covers every thread, so the wait for running jobs never
        exceeds ``grace``, and each requeue's lock acquisition is bounded by
        what remains of it. Filesystem I/O is not bounded: a requeue that
        stalls in the filesystem can run past ``grace`` (see
        ``_drain_one_stem``), and the marker written before each attempt
        makes a job interrupted there recoverable at the next start.
        After the deadline every registered claim is probed,
        whatever its thread's state: a thread that died outside the handler
        guard can leave its record behind, and ``requeue_processing`` is a
        no-op once a normal completion has moved the record. A record still in
        processing/ under this runner's token is moved back to pending/ without
        consuming an attempt, with ``last_error`` set to
        ``q.SHUTDOWN_REQUEUE_REASON``; one whose requeue cannot finish before
        the deadline keeps a marker for startup recovery. Only jobs owned by
        this runner's live threads are touched: ``_start_batch`` registers a
        thread only after this runner's own claim succeeded, so a job another
        worker won is never in the registry and its processing/ file is left
        alone. A job that already left processing/ (it finished during the
        race) is not recreated. A registered thread that never started is
        requeued too. Returns the requeued job stems.

        Delivery is at-least-once. Threads cannot be killed, so a requeued
        job's thread keeps running until the interpreter exits, and the job
        runs again on the next start after a partial first run. If that
        thread finishes first, its outcome transition finds the job gone (or
        claimed again under a new token) and writes nothing, so the requeued
        copy is never overwritten and no done/ or error/ record appears.
        """
        deadline = time.monotonic() + max(0.0, grace)
        with self._registry_lock:
            live = dict(self._live_threads)
        for thread, _tok in live.values():
            if thread.ident is not None:  # join() raises on a never-started thread
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        requeued: list[str] = []
        for stem, (thread, token) in live.items():
            # Probe every registered entry regardless of alive state: a thread
            # whose _run_guarded caught an exception outside process_claimed can
            # exit while its processing/<id>.json remains, so skipping dead
            # threads (the old `if thread.ident is not None and not
            # thread.is_alive(): continue`) would strand those jobs.
            # requeue_processing is a no-op when the record is already gone
            # (normal completion moved it), so probing a finished thread is
            # safe — it never recreates a job that legitimately completed.
            if self._drain_one_stem(stem, token, deadline):
                requeued.append(stem)
        return requeued

    def _drain_one_stem(self, stem: str, token: str | None, deadline: float) -> bool:
        """Requeue one live-thread's job on shutdown; return True if requeued.

        Split out of ``drain_live_threads`` to keep that loop's cognitive
        complexity in check.

        The token is passed through as claim_token rather than compared here
        first: a pre-check-then-requeue has the same window this check exists
        to close (another worker's reaper can reclaim the stem between the
        check and the requeue), so the comparison must happen atomically
        under requeue_processing's transition lock.

        The remaining time budget, measured after the marker write, is passed
        as lock_timeout, floored at 0.0 (one non-blocking attempt once the
        deadline has passed), so a contended lock never extends the drain.
        The transition lock is the only lock the drain takes on a stem. A
        lock-timeout or I/O failure for one stem is logged and the drain
        continues; its marker stays for startup recovery.

        lock_timeout bounds only acquiring the lock, not the filesystem work
        requeue_processing does while holding it, and a call that starts
        before the deadline can overrun it. Neither can be bounded from pure
        Python short of abandoning a thread mid-syscall, and a stalled
        filesystem would stall the marker write as well. So the shutdown-
        timeout marker is written before every attempt, not only once the
        deadline has passed: whenever the call hangs and launchd SIGKILLs the
        process, recovery intent is already on disk and the next start
        requeues the job. The marker is removed once the call returns
        normally, whatever it returned, and kept if it raises.
        """
        _mark_for_recovery(stem, token)
        # Measured after the marker write, not before it: a write that stalls
        # would otherwise leave the lock wait its full pre-write budget and
        # carry the drain past the deadline.
        lock_budget = max(0.0, deadline - time.monotonic())
        try:
            requeue_result = q.requeue_processing(
                stem,
                reason=q.SHUTDOWN_REQUEUE_REASON,
                root=q.QUEUE_ROOT,
                claim_token=token,
                lock_timeout=lock_budget,
            )
        except Exception:  # nosec B112 - best-effort shutdown drain; log and continue to remaining jobs
            # A _TransitionLockTimeout means a live job still holds the lock
            # (inside finish()/retry()) past the grace period. Either way the
            # marker stays for recovery at the next start; rewrite it in case
            # the write before the call failed.
            logger.exception(
                "could not requeue job %s on shutdown (skipped); "
                "leaving shutdown-timeout marker for recovery on next start",
                stem,
            )
            _mark_for_recovery(stem, token)
            return False
        try:
            _remove_shutdown_timeout_marker(stem, token, q.QUEUE_ROOT)
        except Exception:  # nosec B110 - a leftover marker is re-verified by token at next start
            logger.exception("could not remove shutdown-timeout marker for job %s", stem)
        if requeue_result:
            logger.warning("requeued running job %s on shutdown", stem)
            return True
        return False

    def _tick_guarded(self) -> int:
        """Run one ``tick()``; log a failure and report nothing started.

        A queue I/O error escaping one tick (an unreadable pending/ listing, a
        failed reap) must not end the loop: that would skip
        ``drain_live_threads`` and leave every running job's claim in
        processing/. The next tick retries after the idle interval.
        """
        try:
            return self.tick()
        except Exception:  # nosec B110 - logged; the loop retries next interval
            logger.exception("worker tick failed; retrying next interval")
            return 0

    def run_daemon(self) -> int:
        """Run continuous daemon loop until stopped, then drain.

        Calls the non-blocking ``tick()`` each iteration so a long-running
        job never blocks the daemon from claiming other pending work.

        SIGTERM (how launchd stops the agent) and SIGINT both set
        ``stop_event``; handlers are installed only when running in the main
        thread and the previous ones are restored on exit. On stop the loop
        claims no new jobs, then ``drain_live_threads`` waits up to
        ``config.shutdown_grace`` seconds and requeues any job still running
        instead of leaving it in processing/. See
        ``drain_live_threads`` for the at-least-once consequence.
        """
        # Anchor the daemon's cwd to the repo root so job scripts that use
        # relative paths (./bin/...) resolve correctly.
        os.chdir(str(get_repo_root()))
        # Install stop handlers before staged-requeue recovery so that a
        # SIGTERM/SIGINT arriving while recover_staged_requeues holds
        # _transition_lock still sets stop_event and allows drain_live_threads
        # to run, rather than terminating via the default handler.
        previous = _install_stop_handlers(self.stop_event)
        try:
            # Publish any staged requeue a previous crash interrupted
            # (*.json.requeue files invisible to the normal listing), and
            # requeue any job a prior drain could not move before the lock
            # timed out (*.json.shutdown-timeout markers).
            _recover_at_start()
            try:
                while not self.stop_event.is_set():
                    n = self._tick_guarded()
                    self.stop_event.wait(self.config.interval if n == 0 else 0.1)
            except KeyboardInterrupt:
                self.stop_event.set()
            logger.info("stopping; waiting up to %ss for running jobs", self.config.shutdown_grace)
            self.drain_live_threads(self.config.shutdown_grace)
        finally:
            _restore_signal_handlers(previous)
        logger.info("stopped")
        return 0
