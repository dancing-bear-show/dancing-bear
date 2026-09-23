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

# ============================================================================
# Helpers
# ============================================================================


def _finish_or_retry(
    proc_path: Path, ctx: JobContext, config: WorkerConfig, reason: str
) -> None:
    """Finish the job as errored if attempts are exhausted, else retry it."""
    attempts = ctx.attempts + 1
    if attempts >= ctx.max_attempts:
        q.finish(proc_path, success=False, error_msg=reason)
    else:
        q.retry(proc_path, delay_sec=config.backoff, reason=reason)


def _effective_job_timeout(job_data: dict[str, object], default_timeout: int) -> int:
    """Resolve per-job timeout override, falling back to default_timeout."""
    try:
        raw = job_data.get("timeout_sec") or 0
        per_job = int(raw) if isinstance(raw, (int, float, str)) else 0
        return per_job if per_job > 0 else default_timeout
    except (TypeError, ValueError):
        return default_timeout


def _undo_retry_attempt(job_stem: str, original_attempts: int, q_root: Path) -> None:
    """Reset attempts to original_attempts after a deferred re-queue.

    q.retry increments attempts; deferred jobs should not consume an attempt.
    """
    try:
        from core.fileutil import atomic_write_json, safe_load_json

        paths = q._ensure_dirs(q_root)
        path = q._job_path(paths["pending"], job_stem)
        if not path.exists():
            return
        data = safe_load_json(path, default={})
        data["attempts"] = original_attempts
        atomic_write_json(path, data)
    except Exception:  # nosec B110 - best-effort; worker will still retry correctly
        pass


def _processing_stems(root: Path) -> set[str]:
    """Return the job stems currently in processing/ under ``root``."""
    folder = q._ensure_dirs(root)["processing"]
    return {p.stem for p in q._list_job_paths(folder)}


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
    # requeueing them. Kept below launchd's default ExitTimeOut (20s) so the
    # requeue finishes before launchd escalates to SIGKILL.
    shutdown_grace: float = 10.0


@dataclass
class JobContext:
    """Context for processing a single job."""

    job_path: Path
    job_data: dict[str, object]
    job_type: str
    attempts: int
    max_attempts: int

    @classmethod
    def from_item(cls, job_path: Path, job_data: dict[str, object]) -> JobContext:
        """Create JobContext from queue item."""
        raw_attempts = job_data.get("attempts") or 0
        raw_max = job_data.get("max_attempts") or 3
        return cls(
            job_path=job_path,
            job_data=job_data,
            job_type=str(job_data.get("type") or ""),
            attempts=int(raw_attempts) if isinstance(raw_attempts, (int, float, str)) else 0,
            max_attempts=int(raw_max) if isinstance(raw_max, (int, float, str)) else 3,
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
    if success:
        q.finish(proc_path, success=True, result=out)
        log_perf_jsonl(
            "worker", duration, args=[command, ctx.job_type, "ok"], exit_code=0
        )
    elif out_str.startswith("deferred-"):
        # Handler requested deferral — move back to pending without consuming an attempt.
        q.retry(proc_path, delay_sec=config.backoff, reason=out_str)
        _undo_retry_attempt(proc_path.stem, ctx.attempts, q_root=q.QUEUE_ROOT)
        log_perf_jsonl(
            "worker", duration, args=[command, ctx.job_type, "deferred"], exit_code=0
        )
    elif out_str.startswith("terminal-"):
        # Handler signalled an unrecoverable failure — skip retry loop entirely.
        q.finish(proc_path, success=False, error_msg=out_str)
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
            1 if processed, 0 if skipped (already claimed by another worker)
        """
        st = time.time()
        proc_path = q.start_processing(job_path)

        if not proc_path:
            # Already claimed by another worker
            return 0

        return self.process_claimed(proc_path, job_data, started_at=st)

    def process_claimed(
        self,
        proc_path: Path,
        job_data: dict[str, object],
        *,
        started_at: float | None = None,
    ) -> int:
        """Process a job this worker has already moved into processing/.

        The daemon tick claims each job itself before starting a thread on
        this method, so only confirmed claims ever run here. ``started_at``
        lets ``process_one`` include its claim in the logged duration.

        Returns:
            1 (the job was handled, finished, or retried)
        """
        st = time.time() if started_at is None else started_at
        ctx = JobContext.from_item(proc_path, job_data)

        # A non-object payload can never be handled — terminal failure, no retry.
        raw_payload = job_data.get("payload")
        if raw_payload is not None and not isinstance(raw_payload, dict):
            q.finish(
                proc_path,
                success=False,
                error_msg=f"invalid payload: expected object, got {type(raw_payload).__name__}",
            )
            log_perf_jsonl(
                "worker",
                int((time.time() - st) * 1000),
                args=[self.command, "invalid_payload", ctx.job_type],
                exit_code=2,
            )
            return 1
        base_payload: dict[str, object] = dict(raw_payload or {})

        # Resolve effective per-job timeout
        job_timeout_sec = _effective_job_timeout(job_data, self.config.job_timeout)
        if job_timeout_sec > 0:
            base_payload["timeout"] = job_timeout_sec
        # Handlers always see an object payload, whether or not a timeout applies.
        job_data = {**job_data, "payload": base_payload}

        # Check for handler — unknown type is a terminal failure, no retry.
        handler = HANDLERS.get(ctx.job_type)
        if not handler:
            q.finish(
                proc_path, success=False, error_msg=f"unknown handler: {ctx.job_type}"
            )
            log_perf_jsonl(
                "worker",
                int((time.time() - st) * 1000),
                args=[self.command, "unknown", ctx.job_type],
                exit_code=2,
            )
            return 1

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
            return 1

        outcome_ctx = OutcomeContext(
            proc_path=proc_path,
            ctx=ctx,
            duration=duration,
            command=self.command,
            config=self.config,
        )
        producer = JobResultProducer(outcome_ctx)
        producer.produce(envelope)
        return 1


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
        self._live_threads: dict[str, threading.Thread] = {}
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
        with self._registry_lock:
            owned = set(self._live_threads)
        _reap_stale_unowned(self.config.job_timeout, q.QUEUE_ROOT, owned)

        allowed = self._calculate_allowed_jobs()
        if allowed <= 0:
            return 0

        items = [
            (p, d) for p, d in q.list_pending() if p.stem not in self._live_threads
        ][:allowed]
        if not items:
            return 0

        return self._start_batch(items)

    def _prune_live_threads(self) -> None:
        """Drop finished threads from the live-thread registry."""
        with self._registry_lock:
            for stem in [s for s, t in self._live_threads.items() if not t.is_alive()]:
                del self._live_threads[stem]

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

    def _process_claimed_guarded(self, proc_path: Path, job_data: dict[str, object]) -> int:
        """Daemon-tick thread target: process a job ``_start_batch`` already claimed."""
        return self._run_guarded(
            proc_path.stem, lambda: self.processor.process_claimed(proc_path, job_data)
        )

    @staticmethod
    def _claim(job_path: Path) -> Path | None:
        """Claim a pending job for this runner; None if it cannot be claimed.

        None covers both another worker winning the claim and a claim that
        raised (logged), so one bad file never stops the daemon loop.
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
        """
        started = 0
        for p, d in items:
            if self.stop_event.is_set():
                break
            proc_path = self._claim(p)
            if proc_path is None:
                continue
            t = threading.Thread(
                target=self._process_claimed_guarded, args=(proc_path, d), daemon=True
            )
            with self._registry_lock:
                self._live_threads[p.stem] = t
            t.start()
            started += 1
        return started

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
            live_stems = set(self._live_threads)
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

        items = q.list_pending()[:allowed]
        if not items:
            return 0

        return self._process_batch(items)

    def _process_batch(self, items: list[tuple[Path, dict[str, object]]]) -> int:
        """Process a batch of jobs in parallel with threading."""
        threads: list[threading.Thread] = []
        results: list[int] = [0] * len(items)

        timeouts: list[int] = [
            _effective_job_timeout(d, self.config.job_timeout) for _, d in items
        ]

        def _run(idx: int, pth: Path, dat: dict[str, object]) -> None:
            results[idx] = self._process_one_guarded(pth, dat)

        for i, (p, d) in enumerate(items):
            t = threading.Thread(target=_run, args=(i, p, d), daemon=True)
            threads.append(t)
            t.start()

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
        """
        self._run_once_batch()
        return 0

    def drain_live_threads(self, grace: float) -> list[str]:
        """Wait up to ``grace`` seconds for live job threads; requeue the rest.

        One deadline covers every thread, so the total wait never exceeds
        ``grace``. Each thread still alive at the deadline has its job moved
        from processing/ back to pending/ without consuming an attempt, with
        ``last_error`` set to ``q.SHUTDOWN_REQUEUE_REASON``. Only jobs owned by
        this runner's live threads are touched: ``_start_batch`` registers a
        thread only after this runner's own claim succeeded, so a job another
        worker won is never in the registry and its processing/ file is left
        alone. A job that already left processing/ (it finished during the
        race) is not recreated. Returns the requeued job stems.

        Delivery is at-least-once. Threads cannot be killed, so a requeued
        job's thread keeps running until the interpreter exits, and the job
        runs again on the next start after a partial first run. A thread that
        finishes in the moment between the requeue and interpreter exit can
        also leave a done/ or error/ record beside the requeued copy.
        """
        deadline = time.monotonic() + max(0.0, grace)
        with self._registry_lock:
            live = dict(self._live_threads)
        for thread in live.values():
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        requeued: list[str] = []
        for stem, thread in live.items():
            if not thread.is_alive():
                continue
            if q.requeue_processing(stem, reason=q.SHUTDOWN_REQUEUE_REASON, root=q.QUEUE_ROOT):
                logger.warning("requeued running job %s on shutdown", stem)
                requeued.append(stem)
        return requeued

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
        # Publish any staged requeue a previous crash interrupted
        # (*.json.requeue files invisible to the normal listing).
        q.recover_staged_requeues(root=q.QUEUE_ROOT)
        previous = _install_stop_handlers(self.stop_event)
        try:
            try:
                while not self.stop_event.is_set():
                    n = self.tick()
                    self.stop_event.wait(self.config.interval if n == 0 else 0.1)
            except KeyboardInterrupt:
                self.stop_event.set()
            logger.info("stopping; waiting up to %ss for running jobs", self.config.shutdown_grace)
            self.drain_live_threads(self.config.shutdown_grace)
        finally:
            _restore_signal_handlers(previous)
        logger.info("stopped")
        return 0
