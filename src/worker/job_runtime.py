"""Worker job runtime: config, job context, processing pipeline, and daemon loop.

Split out of commands.py to separate runtime concerns from CLI command classes.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from core.cli_errors import UsageError
from core.cli_output import OutputWriter
from core.pipeline import BaseProducer, RequestConsumer, ResultEnvelope, SafeProcessor
from worker._helpers import (
    log_perf_jsonl,
    get_repo_root,
)
from worker import queue_ops as q
from worker.handlers import REGISTRY as HANDLERS
from worker.queue_metrics import counts

logger = logging.getLogger(__name__)

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
        per_job = int(job_data.get("timeout_sec") or 0)
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
        return cls(
            job_path=job_path,
            job_data=job_data,
            job_type=str(job_data.get("type") or ""),
            attempts=int(job_data.get("attempts") or 0),
            max_attempts=int(job_data.get("max_attempts") or 3),
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
        """Process a single job.

        Returns:
            1 if processed, 0 if skipped (already claimed)
        """
        st = time.time()
        proc_path = q.start_processing(job_path)

        if not proc_path:
            # Already claimed by another worker
            return 0

        ctx = JobContext.from_item(job_path, job_data)

        # Resolve effective per-job timeout
        job_timeout_sec = _effective_job_timeout(job_data, self.config.job_timeout)
        if job_timeout_sec > 0:
            raw_payload = job_data.get("payload")
            base_payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
            job_data = {**job_data, "payload": {**base_payload, "timeout": job_timeout_sec}}

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
        request = JobRequest(job_id=str(job_data.get("id") or ""), payload=dict(job_data.get("payload") or {}))
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
    """Runs the worker daemon loop."""

    def __init__(self, config: WorkerConfig, processor: JobProcessor):
        """Initialize daemon with configuration and processor."""
        self.config = config
        self.processor = processor

    def tick(self) -> int:
        """Process one batch of jobs."""
        q.reap_stale_processing_jobs(self.config.job_timeout, root=q.QUEUE_ROOT)

        allowed = self._calculate_allowed_jobs()
        if allowed <= 0:
            return 0

        items = q.list_pending()[:allowed]
        if not items:
            return 0

        return self._process_batch(items)

    def _calculate_allowed_jobs(self) -> int:
        """Calculate how many jobs can be processed based on max_inflight cap."""
        if self.config.max_inflight > 0:
            try:
                cur_proc = int(counts(root=q.QUEUE_ROOT).get("processing", 0))
                return max(
                    0,
                    min(self.config.max_per_tick, self.config.max_inflight - cur_proc),
                )
            except Exception:  # nosec B110 - fallback to max_per_tick
                return self.config.max_per_tick
        return self.config.max_per_tick

    def _process_batch(self, items: list[tuple[Path, dict[str, object]]]) -> int:
        """Process a batch of jobs in parallel with threading."""
        threads: list[threading.Thread] = []
        results: list[int] = [0] * len(items)

        timeouts: list[int] = [
            _effective_job_timeout(d, self.config.job_timeout) for _, d in items
        ]

        def _run(idx: int, pth: Path, dat: dict[str, object]):
            try:
                results[idx] = self.processor.process_one(pth, dat)
            except Exception:  # nosec B110 - thread safety; result defaults to 1
                results[idx] = 1

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
        """Run one tick and exit."""
        self.tick()
        return 0

    def run_daemon(self) -> int:
        """Run continuous daemon loop."""
        # Anchor the daemon's cwd to the repo root so job scripts that use
        # relative paths (./bin/...) resolve correctly.
        os.chdir(str(get_repo_root()))
        try:
            while True:
                n = self.tick()
                sleep_time = self.config.interval if n == 0 else 0.1
                time.sleep(sleep_time)
        except KeyboardInterrupt:
            logger.info("stopped")
            return 0
