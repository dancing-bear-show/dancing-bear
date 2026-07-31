"""Worker command classes and dataclasses.

Each command is extracted into its own class for maintainability and testability.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.cli_errors import CLIError, ExitCode, UsageError
from core.cli_output import OutputWriter, emit_one
from core.pipeline import BaseProducer, RequestConsumer, ResultEnvelope, SafeProcessor
from worker._helpers import (
    DATE_FORMAT_YMD,
    ISO_DATETIME_FORMAT,
    log_perf_jsonl,
    now_utc,
    parse_iso_utc,
    parse_window,
    get_repo_root,
)
from worker import queue as q
from worker.handlers import REGISTRY as HANDLERS

logger = logging.getLogger(__name__)

# ============================================================================
# Helpers
# ============================================================================


def _undo_retry_attempt(job_stem: str, original_attempts: int, q_root: Path) -> None:
    """Reset attempts to original_attempts after a deferred re-queue.

    q.retry increments attempts; deferred jobs should not consume an attempt.
    """
    try:
        from worker._helpers import atomic_write_json, safe_load_json

        paths = q._ensure_dirs(q_root)
        path = q._job_path(paths["pending"], job_stem)
        if not path.exists():
            return
        data = safe_load_json(path)
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


# ============================================================================
# Outcome dispatch
# ============================================================================


def _handle_outcome(
    proc_path: Path,
    ctx: JobContext,
    success: bool,
    out: object,
    duration: int,
    command: str,
    config: WorkerConfig,
) -> None:
    """Dispatch a completed handler invocation to the appropriate queue operation."""
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
        attempts = ctx.attempts + 1
        if attempts >= ctx.max_attempts:
            q.finish(proc_path, success=False, error_msg=out_str)
            log_perf_jsonl(
                "worker", duration, args=[command, ctx.job_type, "error"], exit_code=1
            )
        else:
            q.retry(proc_path, delay_sec=config.backoff, reason=out_str)
            log_perf_jsonl(
                "worker", duration, args=[command, ctx.job_type, "retry"], exit_code=1
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
        proc_path: Path,
        ctx: JobContext,
        duration: int,
        command: str,
        config: WorkerConfig,
        writer: OutputWriter | None = None,
    ) -> None:
        super().__init__(writer)
        self._proc_path = proc_path
        self._ctx = ctx
        self._duration = duration
        self._command = command
        self._config = config

    def _produce_success(
        self, payload: JobResult, diagnostics: dict[str, object] | None
    ) -> None:
        """Dispatch outcome to queue operations based on the outcome string."""
        success = payload.outcome == "success"
        out_val: object = payload.outcome if not success else payload.logs[0] if payload.logs else True
        _handle_outcome(
            self._proc_path,
            self._ctx,
            success,
            out_val,
            self._duration,
            self._command,
            self._config,
        )


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
        try:
            _per_job = int(job_data.get("timeout_sec") or 0)
            job_timeout_sec = _per_job if _per_job > 0 else self.config.job_timeout
        except (TypeError, ValueError):
            job_timeout_sec = self.config.job_timeout
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
            attempts = ctx.attempts + 1
            if attempts >= ctx.max_attempts:
                q.finish(proc_path, success=False, error_msg=str(reason))
            else:
                q.retry(proc_path, delay_sec=self.config.backoff, reason=str(reason))
            log_perf_jsonl(
                "worker",
                duration,
                args=[self.command, ctx.job_type, "exception"],
                exit_code=2,
            )
            return 1

        producer = JobResultProducer(proc_path, ctx, duration, self.command, self.config)
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
                cur_proc = int(q.counts(root=q.QUEUE_ROOT).get("processing", 0))
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

        def _effective_timeout(d: dict[str, object]) -> int:
            try:
                per_job = int(d.get("timeout_sec") or 0)
                return per_job if per_job > 0 else self.config.job_timeout
            except (TypeError, ValueError):
                return self.config.job_timeout

        timeouts: list[int] = [_effective_timeout(d) for _, d in items]

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


# ============================================================================
# Command Classes
# ============================================================================


class EnqueueCommand:
    """Enqueue a new job to the queue."""

    @staticmethod
    def run(args) -> int:
        """Execute enqueue command."""
        payload = {}
        try:
            payload = json.loads(str(getattr(args, "payload_json", "") or "{}"))
        except Exception:
            logger.exception("Invalid --payload-json")
            return 2

        job_id = str(getattr(args, "job_id", "") or uuid.uuid4().hex)
        job = q.Job(
            id=job_id,
            type=str(args.type),
            payload=payload,
            priority=int(getattr(args, "priority", 5) or 5),
            not_before=str(getattr(args, "not_before", "") or ""),
            attempts=0,
            max_attempts=int(getattr(args, "max_attempts", 3) or 3),
            enqueued_at=datetime.now(UTC).strftime(ISO_DATETIME_FORMAT),
        )

        path = q.enqueue(job, root=q.QUEUE_ROOT)
        emit_one({"enqueued": True, "id": job_id, "path": str(path)}, fmt="jsonl")
        return 0


class ListCommand:
    """List queue counts."""

    @staticmethod
    def run(args) -> int:
        """Execute list command."""
        emit_one(q.counts(root=q.QUEUE_ROOT))
        return 0


class StatusCommand:
    """Show queue status with optional throughput metrics."""

    @staticmethod
    def run(args, writer: OutputWriter | None = None) -> int:
        """Execute status command."""
        s = q.status(root=q.QUEUE_ROOT)

        if getattr(args, "text", False) and not getattr(args, "json", False):
            StatusCommand._print_text_status(s, args, writer=writer)
        else:
            emit_one(s)

        return 0

    @staticmethod
    def _print_text_status(
        status: dict[str, object], args, writer: OutputWriter | None = None
    ) -> None:
        """Print human-readable status."""
        out = writer or OutputWriter()
        nxt = status.get("next_scheduled_in_sec")
        nxt_txt = f"{nxt}s" if nxt is not None else "-"
        counts: dict[str, object] = (
            status.get("counts") if isinstance(status.get("counts"), dict) else {}
        )  # type: ignore[assignment]
        error_ids: list[str] = (
            status.get("recent_error_ids")
            if isinstance(status.get("recent_error_ids"), list)
            else []
        )  # type: ignore[assignment]

        lines = [
            f"Queue root: {status.get('root')}",
            f"Counts: pending={counts.get('pending', 0)} processing={counts.get('processing', 0)} done={counts.get('done', 0)} error={counts.get('error', 0)}",
            f"Pending by priority: {status.get('pending_by_priority', {})}",
            f"Oldest pending wait: {status.get('oldest_pending_wait_sec', 0)}s",
            f"Next scheduled in: {nxt_txt}",
            f"Oldest processing age: {status.get('processing_oldest_age_sec', 0)}s",
            f"Recent errors: {', '.join(error_ids) or '-'}",
        ]

        if getattr(args, "with_throughput", False):
            throughput_line = StatusCommand._calculate_throughput()
            if throughput_line:
                lines.append(throughput_line)

        out.print("\n".join(lines))

    @staticmethod
    def _calculate_throughput() -> str | None:
        """Calculate throughput from today's perf log."""
        try:
            ymd = datetime.now(UTC).strftime(DATE_FORMAT_YMD)
            path = Path.cwd() / "_data" / "logs" / f"perf-worker-{ymd}.jsonl"

            if not path.exists():
                return None

            rows: list[dict] = []
            for line in path.open("r", encoding="utf-8"):
                try:
                    rec = json.loads(line)
                    if rec.get("args") == ["daemon", "run_cli", "ok"]:
                        rows.append(rec)
                except Exception:  # nosec B112 - skip malformed log lines
                    continue

            if not rows:
                return None

            rows.sort(key=lambda r: r.get("ts", ""))
            start = datetime.strptime(rows[0]["ts"], ISO_DATETIME_FORMAT)
            end = datetime.strptime(rows[-1]["ts"], ISO_DATETIME_FORMAT)
            secs = max(1, (end - start).total_seconds())
            rate = len(rows) / secs * 60.0
            avg_ms = sum(int(r.get("duration_ms", 0)) for r in rows) / max(1, len(rows))

            return f"Throughput (today): {rate:.2f} jobs/min, avg {avg_ms:.0f} ms/job"
        except Exception:  # nosec B110 - best-effort throughput calculation
            return None


class ShowCommand:
    """Show a job by ID."""

    @staticmethod
    def run(args, writer: OutputWriter | None = None) -> int:
        """Execute show command."""
        out = writer or OutputWriter()
        jid = str(args.id)
        root = q.QUEUE_ROOT

        for folder in ["pending", "processing", "done", "error"]:
            p = root / folder / f"{jid}.json"
            if p.exists():
                out.print(p.read_text(encoding="utf-8"))
                return 0

        raise CLIError(f"Job not found: {jid}", code=ExitCode.NOT_FOUND)


class RequeueErrorsCommand:
    """Requeue error jobs with optional filtering."""

    @staticmethod
    def run(args) -> int:
        """Execute requeue-errors command."""
        limit = int(getattr(args, "limit", 0) or 0) or None
        delay = int(getattr(args, "delay", 0) or 0)
        reset = bool(getattr(args, "reset_attempts", False))
        newmax = int(getattr(args, "new_max_attempts", 0) or 0) or None
        since = getattr(args, "since", None)
        match = [str(m) for m in (getattr(args, "match", []) or [])]

        items = q.list_error(root=q.QUEUE_ROOT)
        items = RequeueErrorsCommand._apply_since_filter(items, since)
        items = RequeueErrorsCommand._apply_match_filter(items, match)

        if limit is not None:
            items = items[: int(limit)]

        paths: list[Path] = []
        for p, _ in items:
            paths.append(
                q.requeue_error(
                    p,
                    delay_sec=delay,
                    root=q.QUEUE_ROOT,
                    reset_attempts=reset,
                    new_max_attempts=newmax,
                )
            )

        emit_one({"requeued": len(paths), "paths": [str(p) for p in paths]})
        return 0

    @staticmethod
    def _apply_since_filter(
        items: list[tuple[Path, dict]], since: str | None
    ) -> list[tuple[Path, dict]]:
        """Filter items by time window."""
        if not since:
            return items

        try:
            win = parse_window(since)
            cutoff = now_utc() - win

            def _ts(d):
                s = d.get("updated_at") or d.get("enqueued_at") or ""
                dt = parse_iso_utc(s)
                return dt if dt else now_utc()

            return [(p, d) for (p, d) in items if _ts(d) >= cutoff]
        except Exception:  # nosec B110 - best-effort filter; return all on error
            return items

    @staticmethod
    def _apply_match_filter(
        items: list[tuple[Path, dict]], match: list[str]
    ) -> list[tuple[Path, dict]]:
        """Filter items by string matching."""
        if not match:
            return items

        def _has(d) -> bool:
            try:
                blob = json.dumps(d)
            except Exception:  # nosec B110 - fallback to str repr
                blob = str(d)
            return all(m.lower() in blob.lower() for m in match)

        return [(p, d) for (p, d) in items if _has(d)]


class RetryCommand:
    """Retry a specific error job by ID."""

    @staticmethod
    def run(args) -> int:
        """Execute retry command."""
        jid = str(args.id)
        p = q.find_job_path_by_id(jid, root=q.QUEUE_ROOT)

        if not p or p.parent.name != "error":
            raise CLIError(f"Job {jid!r} not found in error/", code=ExitCode.NOT_FOUND)

        np = q.requeue_error(
            p,
            delay_sec=int(getattr(args, "delay", 0) or 0),
            root=q.QUEUE_ROOT,
            reset_attempts=bool(getattr(args, "reset_attempts", False)),
            new_max_attempts=(int(getattr(args, "new_max_attempts", 0) or 0) or None),
        )

        emit_one({"requeued": True, "path": str(np)})
        return 0


class PurgeCommand:
    """Purge old jobs from done/error folders."""

    @staticmethod
    def run(args) -> int:
        """Execute purge command."""
        win = parse_window(str(getattr(args, "older_than", "30d")))
        secs = int(win.total_seconds())
        folders = [
            s.strip()
            for s in str(getattr(args, "folders", "done,error")).split(",")
            if s.strip()
        ]

        res = q.purge(secs, root=q.QUEUE_ROOT, folders=folders)
        emit_one(res)
        return 0
