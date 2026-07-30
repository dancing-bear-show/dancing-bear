"""Tests for worker/commands.py — covering gaps to reach 80%+ line coverage."""

from __future__ import annotations

import argparse
import json
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.worker_tests.helpers import QueueRootIsolationMixin, _make_root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs) -> argparse.Namespace:
    defaults = {
        "type": "run_cli",
        "payload_json": "{}",
        "priority": 5,
        "max_attempts": 3,
        "not_before": "",
        "job_id": "",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# WorkerConfig
# ---------------------------------------------------------------------------

class TestWorkerConfig(unittest.TestCase):
    def test_defaults(self):
        from worker.commands import WorkerConfig
        cfg = WorkerConfig()
        self.assertEqual(cfg.backoff, 60)
        self.assertEqual(cfg.max_per_tick, 3)
        self.assertEqual(cfg.max_inflight, 0)
        self.assertEqual(cfg.job_timeout, 0)
        self.assertEqual(cfg.interval, 5.0)

    def test_custom_values(self):
        from worker.commands import WorkerConfig
        cfg = WorkerConfig(backoff=30, max_per_tick=10, max_inflight=5)
        self.assertEqual(cfg.backoff, 30)
        self.assertEqual(cfg.max_per_tick, 10)
        self.assertEqual(cfg.max_inflight, 5)


# ---------------------------------------------------------------------------
# JobContext
# ---------------------------------------------------------------------------

class TestJobContext(unittest.TestCase):
    def test_from_item_parses_job_data(self):
        from worker.commands import JobContext
        job_data = {"type": "run_cli", "attempts": 1, "max_attempts": 5}
        ctx = JobContext.from_item(Path("/tmp/x.json"), job_data)  # nosec B108
        self.assertEqual(ctx.job_type, "run_cli")
        self.assertEqual(ctx.attempts, 1)
        self.assertEqual(ctx.max_attempts, 5)

    def test_from_item_defaults_on_missing_fields(self):
        from worker.commands import JobContext
        ctx = JobContext.from_item(Path("/tmp/x.json"), {})  # nosec B108
        self.assertEqual(ctx.job_type, "")
        self.assertEqual(ctx.attempts, 0)
        self.assertEqual(ctx.max_attempts, 3)


# ---------------------------------------------------------------------------
# _undo_retry_attempt
# ---------------------------------------------------------------------------

class TestUndoRetryAttempt(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_resets_attempts_on_pending_job(self):
        from worker.queue import Job, enqueue
        from worker.commands import _undo_retry_attempt
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        enqueue(Job(id="undo1", type="noop", payload={}, attempts=1), root=self.root)
        _undo_retry_attempt("undo1", 0, self.root)
        data = json.loads((self.root / "pending" / "undo1.json").read_text())
        self.assertEqual(data["attempts"], 0)

    def test_does_not_raise_when_job_missing(self):
        from worker.commands import _undo_retry_attempt
        from worker.queue import _ensure_dirs
        _ensure_dirs(self.root)
        # Should not raise even if job doesn't exist
        _undo_retry_attempt("nonexistent-job", 0, self.root)


# ---------------------------------------------------------------------------
# _handle_outcome
# ---------------------------------------------------------------------------

class TestHandleOutcome(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()
        # Import the real (unpatched) functions before any patching occurs
        from worker.queue import finish as _real_finish, retry as _real_retry
        self._real_finish = _real_finish
        self._real_retry = _real_retry

    def _make_proc_path(self, job_id: str) -> Path:
        from worker.queue import Job, enqueue, start_processing
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        job = Job(id=job_id, type="noop", payload={})
        pending = enqueue(job, root=self.root)
        return start_processing(pending, self.root)

    def _make_ctx(self, job_id: str, attempts: int = 0, max_attempts: int = 3):
        from worker.commands import JobContext
        return JobContext(
            job_path=Path(f"/tmp/{job_id}.json"),  # nosec B108
            job_data={"id": job_id},
            job_type="noop",
            attempts=attempts,
            max_attempts=max_attempts,
        )

    def _make_config(self):
        from worker.commands import WorkerConfig
        return WorkerConfig(backoff=0)

    def _patched_finish(self, job_path, success, **kwargs):
        """Call the real finish with the test root."""
        kwargs["root"] = self.root
        return self._real_finish(job_path, success, **kwargs)

    def _patched_retry(self, job_path, **kwargs):
        """Call the real retry with the test root."""
        kwargs["root"] = self.root
        return self._real_retry(job_path, **kwargs)

    def test_success_moves_job_to_done(self):
        from worker.commands import _handle_outcome
        proc = self._make_proc_path("h_ok")
        ctx = self._make_ctx("h_ok")
        with patch("worker.commands.log_perf_jsonl"), \
             patch("worker.commands.q.finish", side_effect=self._patched_finish):
            _handle_outcome(proc, ctx, True, {"ok": True}, 100, "daemon", self._make_config())
        self.assertTrue((self.root / "done" / "h_ok.json").exists())

    def test_deferred_outcome_moves_job_back_to_pending(self):
        from worker.commands import _handle_outcome
        proc = self._make_proc_path("h_defer")
        ctx = self._make_ctx("h_defer")
        with patch("worker.commands.log_perf_jsonl"), \
             patch("worker.commands._undo_retry_attempt"), \
             patch("worker.commands.q.retry", side_effect=self._patched_retry):
            _handle_outcome(proc, ctx, False, "deferred-needs-resource", 100, "daemon", self._make_config())
        self.assertTrue((self.root / "pending" / "h_defer.json").exists())

    def test_terminal_failure_moves_to_error(self):
        from worker.commands import _handle_outcome
        proc = self._make_proc_path("h_term")
        ctx = self._make_ctx("h_term")
        with patch("worker.commands.log_perf_jsonl"), \
             patch("worker.commands.q.finish", side_effect=self._patched_finish):
            _handle_outcome(proc, ctx, False, "terminal-unrecoverable", 100, "daemon", self._make_config())
        self.assertTrue((self.root / "error" / "h_term.json").exists())

    def test_retry_exhausted_moves_to_error(self):
        from worker.commands import _handle_outcome
        proc = self._make_proc_path("h_exhaust")
        # attempts=2, max_attempts=3: attempts+1=3 >= max_attempts -> error
        ctx = self._make_ctx("h_exhaust", attempts=2, max_attempts=3)
        with patch("worker.commands.log_perf_jsonl"), \
             patch("worker.commands.q.finish", side_effect=self._patched_finish):
            _handle_outcome(proc, ctx, False, "some error", 100, "daemon", self._make_config())
        self.assertTrue((self.root / "error" / "h_exhaust.json").exists())

    def test_retry_not_exhausted_moves_back_to_pending(self):
        from worker.commands import _handle_outcome
        proc = self._make_proc_path("h_retry")
        # attempts=0, max_attempts=3: can retry
        ctx = self._make_ctx("h_retry", attempts=0, max_attempts=3)
        with patch("worker.commands.log_perf_jsonl"), \
             patch("worker.commands.q.retry", side_effect=self._patched_retry):
            _handle_outcome(proc, ctx, False, "transient error", 100, "daemon", self._make_config())
        self.assertTrue((self.root / "pending" / "h_retry.json").exists())


# ---------------------------------------------------------------------------
# JobProcessor
# ---------------------------------------------------------------------------

class TestJobProcessor(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()
        # Capture real functions before any patching
        from worker.queue import (
            finish as _real_finish,
            retry as _real_retry,
            start_processing as _real_start,
        )
        self._real_finish = _real_finish
        self._real_retry = _real_retry
        self._real_start = _real_start

    def _make_config(self, **kwargs):
        from worker.commands import WorkerConfig
        return WorkerConfig(**kwargs)

    def _patched_finish(self, job_path, success, **kwargs):
        kwargs["root"] = self.root
        return self._real_finish(job_path, success, **kwargs)

    def _patched_retry(self, job_path, **kwargs):
        kwargs["root"] = self.root
        return self._real_retry(job_path, **kwargs)

    def _patched_start(self, job_path, root=None):
        return self._real_start(job_path, self.root)

    def test_process_one_unknown_handler_moves_to_error(self):
        from worker.queue import Job, enqueue, _ensure_dirs
        from worker.commands import JobProcessor
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)
        job = Job(id="proc_unk", type="unknown_type_xyz", payload={})
        pending = enqueue(job, root=self.root)
        job_data = json.loads(pending.read_text())

        processor = JobProcessor(self._make_config(), "daemon")
        with patch("worker.commands.log_perf_jsonl"), \
             patch("worker.commands.q.start_processing", side_effect=self._patched_start), \
             patch("worker.commands.q.finish", side_effect=self._patched_finish):
            result = processor.process_one(pending, job_data)

        self.assertEqual(result, 1)
        self.assertTrue((self.root / "error" / "proc_unk.json").exists())

    def test_process_one_success_moves_to_done(self):
        from worker.queue import Job, enqueue, _ensure_dirs
        from worker.commands import JobProcessor
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)
        job = Job(id="proc_ok", type="workflow_stage", payload={"cli_commands": []})
        pending = enqueue(job, root=self.root)
        job_data = json.loads(pending.read_text())

        processor = JobProcessor(self._make_config(), "daemon")
        with patch("worker.commands.HANDLERS", {"workflow_stage": lambda j: (True, {"ok": True})}), \
             patch("worker.commands.log_perf_jsonl"), \
             patch("worker.commands.q.start_processing", side_effect=self._patched_start), \
             patch("worker.commands.q.finish", side_effect=self._patched_finish):
            result = processor.process_one(pending, job_data)

        self.assertEqual(result, 1)
        self.assertTrue((self.root / "done" / "proc_ok.json").exists())

    def test_process_one_returns_zero_when_already_claimed(self):
        from worker.queue import Job, enqueue, _ensure_dirs
        from worker.commands import JobProcessor
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)
        job = Job(id="proc_claim", type="noop", payload={})
        pending = enqueue(job, root=self.root)
        job_data = json.loads(pending.read_text())

        processor = JobProcessor(self._make_config(), "daemon")
        # Patch start_processing to return None (already claimed)
        with patch("worker.commands.q.start_processing", return_value=None):
            result = processor.process_one(pending, job_data)

        self.assertEqual(result, 0)

    def test_process_one_exception_in_handler_causes_retry(self):
        from worker.queue import Job, enqueue, _ensure_dirs
        from worker.commands import JobProcessor
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)
        job = Job(id="proc_exc", type="bang", payload={}, max_attempts=3)
        pending = enqueue(job, root=self.root)
        job_data = json.loads(pending.read_text())

        def _boom(j):
            raise RuntimeError("unexpected error")

        processor = JobProcessor(self._make_config(backoff=0), "daemon")
        with patch("worker.commands.HANDLERS", {"bang": _boom}), \
             patch("worker.commands.log_perf_jsonl"), \
             patch("worker.commands.q.start_processing", side_effect=self._patched_start), \
             patch("worker.commands.q.retry", side_effect=self._patched_retry):
            result = processor.process_one(pending, job_data)

        self.assertEqual(result, 1)
        # Should be in pending (retry) since attempts=0 < max_attempts=3
        self.assertTrue((self.root / "pending" / "proc_exc.json").exists())

    def test_process_one_exception_exhausted_moves_to_error(self):
        from worker.queue import Job, enqueue, _ensure_dirs
        from worker.commands import JobProcessor
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)
        job = Job(id="proc_exc2", type="bang2", payload={}, attempts=2, max_attempts=3)
        pending = enqueue(job, root=self.root)
        job_data = json.loads(pending.read_text())
        job_data["attempts"] = 2  # ensure it's in the data dict

        def _boom(j):
            raise RuntimeError("boom")

        processor = JobProcessor(self._make_config(backoff=0), "daemon")
        with patch("worker.commands.HANDLERS", {"bang2": _boom}), \
             patch("worker.commands.log_perf_jsonl"), \
             patch("worker.commands.q.start_processing", side_effect=self._patched_start), \
             patch("worker.commands.q.finish", side_effect=self._patched_finish):
            result = processor.process_one(pending, job_data)

        self.assertEqual(result, 1)
        self.assertTrue((self.root / "error" / "proc_exc2.json").exists())

    def test_process_one_applies_job_timeout_to_payload(self):
        from worker.queue import Job, enqueue, _ensure_dirs
        from worker.commands import JobProcessor
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)
        job = Job(id="proc_to", type="with_timeout", payload={"x": 1})
        pending = enqueue(job, root=self.root)
        job_data = json.loads(pending.read_text())

        captured = {}

        def _handler(j):
            captured["payload"] = j.get("payload", {})
            return True, "ok"

        processor = JobProcessor(self._make_config(job_timeout=30), "daemon")
        with patch("worker.commands.HANDLERS", {"with_timeout": _handler}), \
             patch("worker.commands.log_perf_jsonl"), \
             patch("worker.commands.q.start_processing", side_effect=self._patched_start), \
             patch("worker.commands.q.finish", side_effect=self._patched_finish):
            processor.process_one(pending, job_data)

        self.assertEqual(captured["payload"].get("timeout"), 30)


# ---------------------------------------------------------------------------
# DaemonRunner
# ---------------------------------------------------------------------------

class TestDaemonRunnerTick(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def _make_runner(self, **config_kwargs):
        from worker.commands import DaemonRunner, JobProcessor, WorkerConfig
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        cfg = WorkerConfig(**config_kwargs)
        proc = MagicMock(spec=JobProcessor)
        proc.process_one.return_value = 1
        runner = DaemonRunner(cfg, proc)
        return runner, proc

    def test_tick_returns_zero_on_empty_queue(self):
        from worker.queue import _ensure_dirs
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)
        runner, _ = self._make_runner()
        with patch("worker.commands.q.reap_stale_processing_jobs"), \
             patch("worker.commands.q.list_pending", return_value=[]):
            result = runner.tick()
        self.assertEqual(result, 0)

    def test_tick_processes_pending_job(self):
        from worker.queue import Job, enqueue
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        pending_path = enqueue(Job(id="tick1", type="noop", payload={}), root=self.root)
        job_data = json.loads(pending_path.read_text())
        runner, mock_proc = self._make_runner()
        # Patch list_pending to use test root so tick finds the job
        with patch("worker.commands.q.reap_stale_processing_jobs"), \
             patch("worker.commands.q.list_pending", return_value=[(pending_path, job_data)]):
            result = runner.tick()
        self.assertGreater(result, 0)
        mock_proc.process_one.assert_called()

    def test_run_once_returns_zero(self):
        from worker.queue import _ensure_dirs
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)
        runner, _ = self._make_runner()
        with patch("worker.commands.q.reap_stale_processing_jobs"):
            result = runner.run_once()
        self.assertEqual(result, 0)

    def test_calculate_allowed_jobs_no_inflight_cap(self):
        runner, _ = self._make_runner(max_per_tick=5, max_inflight=0)
        result = runner._calculate_allowed_jobs()
        self.assertEqual(result, 5)

    def test_calculate_allowed_jobs_with_inflight_cap(self):
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        runner, _ = self._make_runner(max_per_tick=5, max_inflight=3)
        # No jobs in processing, so all 3 slots available (min of 5 and 3-0=3)
        with patch("worker.commands.q.counts", return_value={"processing": 0}):
            result = runner._calculate_allowed_jobs()
        self.assertEqual(result, 3)

    def test_calculate_allowed_jobs_inflight_cap_at_limit(self):
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        runner, _ = self._make_runner(max_per_tick=5, max_inflight=3)
        # 3 already processing, so 0 slots
        with patch("worker.commands.q.counts", return_value={"processing": 3}):
            result = runner._calculate_allowed_jobs()
        self.assertEqual(result, 0)

    def test_tick_respects_allowed_cap(self):
        from worker.queue import Job, enqueue
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        paths_and_data = []
        for i in range(5):
            p = enqueue(Job(id=f"cap{i}", type="noop", payload={}), root=self.root)
            paths_and_data.append((p, json.loads(p.read_text())))
        runner, mock_proc = self._make_runner(max_per_tick=2)
        with patch("worker.commands.q.reap_stale_processing_jobs"), \
             patch("worker.commands.q.list_pending", return_value=paths_and_data):
            runner.tick()
        self.assertLessEqual(mock_proc.process_one.call_count, 2)


class TestDaemonRunnerProcessBatch(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_process_batch_runs_in_threads(self):
        from worker.queue import Job, enqueue, _ensure_dirs
        from worker.commands import DaemonRunner, JobProcessor, WorkerConfig
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)

        enqueue(Job(id="th1", type="noop", payload={}), root=self.root)
        enqueue(Job(id="th2", type="noop", payload={}), root=self.root)

        cfg = WorkerConfig()
        mock_proc = MagicMock(spec=JobProcessor)
        mock_proc.process_one.return_value = 1
        runner = DaemonRunner(cfg, mock_proc)

        items = [(Path(self.root / "pending" / "th1.json"), {"id": "th1"}),
                 (Path(self.root / "pending" / "th2.json"), {"id": "th2"})]
        result = runner._process_batch(items)
        self.assertEqual(result, 2)

    def test_process_batch_with_per_job_timeout(self):
        from worker.queue import _ensure_dirs
        from worker.commands import DaemonRunner, JobProcessor, WorkerConfig
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)

        cfg = WorkerConfig(job_timeout=5)
        mock_proc = MagicMock(spec=JobProcessor)
        mock_proc.process_one.return_value = 1
        runner = DaemonRunner(cfg, mock_proc)

        items = [(Path(self.root / "pending" / "pt1.json"), {"id": "pt1", "timeout_sec": 10})]
        result = runner._process_batch(items)
        self.assertEqual(result, 1)


class TestDaemonRunnerDaemon(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_run_daemon_stops_on_keyboard_interrupt(self):
        from worker.commands import DaemonRunner, JobProcessor, WorkerConfig
        from worker import queue as q
        q.QUEUE_ROOT = self.root

        cfg = WorkerConfig(interval=0.01)
        mock_proc = MagicMock(spec=JobProcessor)
        mock_proc.process_one.return_value = 0
        runner = DaemonRunner(cfg, mock_proc)

        tick_count = [0]

        def _tick_raising():
            tick_count[0] += 1
            if tick_count[0] >= 2:
                raise KeyboardInterrupt()
            return 0

        with patch.object(runner, "tick", side_effect=_tick_raising), \
             patch("worker.commands.get_repo_root", return_value=Path(self.tmp.name)), \
             patch("os.chdir"):
            result = runner.run_daemon()

        self.assertEqual(result, 0)

    def test_run_daemon_chdirs_to_repo_root(self):
        from worker.commands import DaemonRunner, JobProcessor, WorkerConfig
        from worker import queue as q
        q.QUEUE_ROOT = self.root

        cfg = WorkerConfig(interval=0.01)
        mock_proc = MagicMock(spec=JobProcessor)
        runner = DaemonRunner(cfg, mock_proc)

        with patch.object(runner, "tick", side_effect=KeyboardInterrupt), \
             patch("worker.commands.get_repo_root", return_value=Path("/fake/repo")), \
             patch("os.chdir") as mock_chdir:
            runner.run_daemon()

        mock_chdir.assert_called_once_with("/fake/repo")


# ---------------------------------------------------------------------------
# EnqueueCommand
# ---------------------------------------------------------------------------

class TestEnqueueCommand(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_enqueue_command_creates_job(self):
        from worker.commands import EnqueueCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        args = _make_args(type="run_cli", payload_json='{"cmd": ["echo"]}')
        with patch("worker.commands.emit_one"):
            rc = EnqueueCommand.run(args)
        self.assertEqual(rc, 0)

    def test_enqueue_command_invalid_json_returns_2(self):
        from worker.commands import EnqueueCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        args = _make_args(payload_json="not-valid-json")
        rc = EnqueueCommand.run(args)
        self.assertEqual(rc, 2)

    def test_enqueue_command_uses_provided_job_id(self):
        from worker.commands import EnqueueCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        args = _make_args(job_id="my-custom-id")

        emitted = {}

        def capture(data, **kwargs):
            emitted.update(data)

        with patch("worker.commands.emit_one", side_effect=capture):
            EnqueueCommand.run(args)

        self.assertEqual(emitted["id"], "my-custom-id")

    def test_enqueue_command_generates_job_id_when_empty(self):
        from worker.commands import EnqueueCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        args = _make_args(job_id="")

        emitted = {}

        def capture(data, **kwargs):
            emitted.update(data)

        with patch("worker.commands.emit_one", side_effect=capture):
            EnqueueCommand.run(args)

        self.assertTrue(emitted["id"])  # non-empty UUID

    def test_enqueue_command_emits_enqueued_true(self):
        from worker.commands import EnqueueCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        args = _make_args()

        emitted = {}

        def capture(data, **kwargs):
            emitted.update(data)

        with patch("worker.commands.emit_one", side_effect=capture):
            EnqueueCommand.run(args)

        self.assertTrue(emitted["enqueued"])


# ---------------------------------------------------------------------------
# ListCommand
# ---------------------------------------------------------------------------

class TestListCommand(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_list_command_returns_zero(self):
        from worker.commands import ListCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        with patch("worker.commands.emit_one"):
            rc = ListCommand.run(argparse.Namespace())
        self.assertEqual(rc, 0)

    def test_list_command_emits_counts(self):
        from worker.commands import ListCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root

        emitted = {}

        def capture(data):
            emitted.update(data)

        with patch("worker.commands.emit_one", side_effect=capture):
            ListCommand.run(argparse.Namespace())

        for key in ("pending", "processing", "done", "error"):
            self.assertIn(key, emitted)


# ---------------------------------------------------------------------------
# StatusCommand
# ---------------------------------------------------------------------------

class TestStatusCommand(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_status_command_returns_zero(self):
        from worker.commands import StatusCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        with patch("worker.commands.emit_one"):
            rc = StatusCommand.run(argparse.Namespace(text=False, json=False))
        self.assertEqual(rc, 0)

    def test_status_command_json_output(self):
        from worker.commands import StatusCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root

        emitted = {}

        def capture(data):
            emitted.update(data)

        with patch("worker.commands.emit_one", side_effect=capture):
            StatusCommand.run(argparse.Namespace(text=False, json=True))

        self.assertIn("counts", emitted)

    def test_status_command_text_output(self):
        import io
        import contextlib
        from worker.commands import StatusCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root

        args = argparse.Namespace(text=True, json=False, with_throughput=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = StatusCommand.run(args)

        self.assertEqual(rc, 0)
        self.assertIn("Queue root", buf.getvalue())

    def test_status_command_text_with_throughput_no_logfile(self):
        import io
        import contextlib
        from worker.commands import StatusCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root

        args = argparse.Namespace(text=True, json=False, with_throughput=True)
        buf = io.StringIO()
        with patch("worker.commands.Path.cwd", return_value=Path(self.tmp.name)):
            with contextlib.redirect_stdout(buf):
                rc = StatusCommand.run(args)

        self.assertEqual(rc, 0)
        # No log file exists, so no throughput line
        self.assertNotIn("Throughput", buf.getvalue())

    def test_calculate_throughput_returns_string_with_log(self):
        from worker.commands import StatusCommand
        from worker._helpers import DATE_FORMAT_YMD
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log_dir = root / "_data" / "logs"
            log_dir.mkdir(parents=True)
            ymd = datetime.now(UTC).strftime(DATE_FORMAT_YMD)
            log_path = log_dir / f"perf-worker-{ymd}.jsonl"
            # Write two matching log entries
            for i in range(2):
                ts = f"2026-07-29T10:0{i}:00Z"
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(
                        json.dumps({"ts": ts, "args": ["daemon", "run_cli", "ok"],
                                    "duration_ms": 1000}) + "\n"
                    )
            with patch("worker.commands.Path.cwd", return_value=root):
                result = StatusCommand._calculate_throughput()

        self.assertIsNotNone(result)
        self.assertIn("Throughput", result)

    def test_calculate_throughput_returns_none_no_matching_rows(self):
        from worker.commands import StatusCommand
        from worker._helpers import DATE_FORMAT_YMD
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log_dir = root / "_data" / "logs"
            log_dir.mkdir(parents=True)
            ymd = datetime.now(UTC).strftime(DATE_FORMAT_YMD)
            log_path = log_dir / f"perf-worker-{ymd}.jsonl"
            # Write rows that don't match ["daemon", "run_cli", "ok"]
            log_path.write_text(
                json.dumps({"ts": "2026-07-29T10:00:00Z", "args": ["other"], "duration_ms": 100}) + "\n"
            )
            with patch("worker.commands.Path.cwd", return_value=root):
                result = StatusCommand._calculate_throughput()

        self.assertIsNone(result)

    def test_print_text_status_shows_all_sections(self):
        import io
        import contextlib
        from worker.commands import StatusCommand

        status_data = {
            "root": "/tmp/q",  # nosec B108
            "counts": {"pending": 1, "processing": 0, "done": 5, "error": 2},
            "pending_by_priority": {"5": 1},
            "oldest_pending_wait_sec": 30,
            "next_scheduled_in_sec": 120,
            "processing_oldest_age_sec": 0,
            "recent_error_ids": ["err1", "err2"],
        }
        args = argparse.Namespace(with_throughput=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            StatusCommand._print_text_status(status_data, args)

        out = buf.getvalue()
        self.assertIn("Queue root", out)
        self.assertIn("Counts", out)
        self.assertIn("Recent errors", out)
        self.assertIn("120s", out)


# ---------------------------------------------------------------------------
# ShowCommand
# ---------------------------------------------------------------------------

class TestShowCommand(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_show_found_job_prints_content(self):
        import io
        import contextlib
        from worker.commands import ShowCommand
        from worker.queue import Job, enqueue
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        enqueue(Job(id="show1", type="noop", payload={}), root=self.root)

        args = argparse.Namespace(id="show1")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ShowCommand.run(args)

        self.assertEqual(rc, 0)
        self.assertIn("show1", buf.getvalue())

    def test_show_missing_job_returns_1(self):
        from worker.commands import ShowCommand
        from worker.queue import _ensure_dirs
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)

        args = argparse.Namespace(id="no-such-job")
        rc = ShowCommand.run(args)
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# RequeueErrorsCommand
# ---------------------------------------------------------------------------

class TestRequeueErrorsCommand(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def _make_error_job(self, job_id: str, updated_at: str | None = None, error: str = "boom") -> Path:
        from worker.queue import _ensure_dirs
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)
        p = self.root / "error" / f"{job_id}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "id": job_id, "type": "noop", "payload": {},
            "status": "error",
            "updated_at": updated_at or "2025-01-01T00:00:00Z",
            "error": error,
        }), encoding="utf-8")
        return p

    def test_requeue_errors_all(self):
        from worker.commands import RequeueErrorsCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        self._make_error_job("e1")
        self._make_error_job("e2")

        args = argparse.Namespace(
            limit=None, delay=0, reset_attempts=False,
            new_max_attempts=None, since=None, match=[]
        )
        with patch("worker.commands.emit_one") as mock_emit:
            rc = RequeueErrorsCommand.run(args)

        self.assertEqual(rc, 0)
        mock_emit.assert_called_once()
        emitted = mock_emit.call_args[0][0]
        self.assertEqual(emitted["requeued"], 2)

    def test_requeue_errors_with_limit(self):
        from worker.commands import RequeueErrorsCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        self._make_error_job("e3")
        self._make_error_job("e4")
        self._make_error_job("e5")

        args = argparse.Namespace(
            limit=1, delay=0, reset_attempts=False,
            new_max_attempts=None, since=None, match=[]
        )
        with patch("worker.commands.emit_one") as mock_emit:
            RequeueErrorsCommand.run(args)

        emitted = mock_emit.call_args[0][0]
        self.assertEqual(emitted["requeued"], 1)

    def test_apply_since_filter_passes_recent(self):
        from worker.commands import RequeueErrorsCommand
        recent_ts = (datetime.now(UTC) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        items = [(Path("/tmp/x.json"), {"updated_at": recent_ts})]  # nosec B108
        result = RequeueErrorsCommand._apply_since_filter(items, "9m")
        self.assertEqual(len(result), 1)

    def test_apply_since_filter_excludes_old(self):
        from worker.commands import RequeueErrorsCommand
        old_ts = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        items = [(Path("/tmp/x.json"), {"updated_at": old_ts})]  # nosec B108
        result = RequeueErrorsCommand._apply_since_filter(items, "9m")
        self.assertEqual(len(result), 0)

    def test_apply_since_filter_no_since_returns_all(self):
        from worker.commands import RequeueErrorsCommand
        items = [(Path("/tmp/x.json"), {"updated_at": "2025-01-01T00:00:00Z"})]  # nosec B108
        result = RequeueErrorsCommand._apply_since_filter(items, None)
        self.assertEqual(len(result), 1)

    def test_apply_match_filter_matches_content(self):
        from worker.commands import RequeueErrorsCommand
        items = [
            (Path("/tmp/a.json"), {"error": "timeout error"}),   # nosec B108
            (Path("/tmp/b.json"), {"error": "connection refused"}),  # nosec B108
        ]
        result = RequeueErrorsCommand._apply_match_filter(items, ["timeout"])
        self.assertEqual(len(result), 1)
        self.assertIn("timeout", result[0][1]["error"])

    def test_apply_match_filter_no_match_terms_returns_all(self):
        from worker.commands import RequeueErrorsCommand
        items = [(Path("/tmp/x.json"), {"error": "anything"})]  # nosec B108
        result = RequeueErrorsCommand._apply_match_filter(items, [])
        self.assertEqual(len(result), 1)

    def test_apply_since_filter_bad_window_returns_all(self):
        from worker.commands import RequeueErrorsCommand
        items = [(Path("/tmp/x.json"), {"updated_at": "2025-01-01T00:00:00Z"})]  # nosec B108
        # parse_window will raise on "invalid", so returns all
        result = RequeueErrorsCommand._apply_since_filter(items, "invalid-window")
        self.assertEqual(len(result), 1)

    def test_requeue_errors_with_match(self):
        from worker.commands import RequeueErrorsCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        self._make_error_job("em1", error="timeout error")
        self._make_error_job("em2", error="connection failed")

        args = argparse.Namespace(
            limit=None, delay=0, reset_attempts=False,
            new_max_attempts=None, since=None, match=["timeout"]
        )
        with patch("worker.commands.emit_one") as mock_emit:
            RequeueErrorsCommand.run(args)

        emitted = mock_emit.call_args[0][0]
        self.assertEqual(emitted["requeued"], 1)


# ---------------------------------------------------------------------------
# RetryCommand
# ---------------------------------------------------------------------------

class TestRetryCommand(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def _make_error_job(self, job_id: str) -> Path:
        from worker.queue import _ensure_dirs
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)
        p = self.root / "error" / f"{job_id}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "id": job_id, "type": "noop", "payload": {},
            "status": "error", "error": "boom",
        }), encoding="utf-8")
        return p

    def test_retry_command_success(self):
        from worker.commands import RetryCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        self._make_error_job("retry1")

        args = argparse.Namespace(id="retry1", delay=0, reset_attempts=True, new_max_attempts=None)
        with patch("worker.commands.emit_one"):
            rc = RetryCommand.run(args)

        self.assertEqual(rc, 0)
        self.assertTrue((self.root / "pending" / "retry1.json").exists())

    def test_retry_command_job_not_in_error_returns_1(self):
        from worker.commands import RetryCommand
        from worker.queue import Job, enqueue, _ensure_dirs
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)
        # Job is in pending, not error
        enqueue(Job(id="notinerr", type="noop", payload={}), root=self.root)

        args = argparse.Namespace(id="notinerr", delay=0, reset_attempts=False, new_max_attempts=None)
        rc = RetryCommand.run(args)
        self.assertEqual(rc, 1)

    def test_retry_command_missing_job_returns_1(self):
        from worker.commands import RetryCommand
        from worker.queue import _ensure_dirs
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        _ensure_dirs(self.root)

        args = argparse.Namespace(id="no-such-job", delay=0, reset_attempts=False, new_max_attempts=None)
        rc = RetryCommand.run(args)
        self.assertEqual(rc, 1)

    def test_retry_command_emits_requeued(self):
        from worker.commands import RetryCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root
        self._make_error_job("retry2")

        emitted = {}

        def capture(data):
            emitted.update(data)

        args = argparse.Namespace(id="retry2", delay=0, reset_attempts=False, new_max_attempts=None)
        with patch("worker.commands.emit_one", side_effect=capture):
            RetryCommand.run(args)

        self.assertTrue(emitted["requeued"])
        self.assertIn("path", emitted)


# ---------------------------------------------------------------------------
# PurgeCommand
# ---------------------------------------------------------------------------

class TestPurgeCommand(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_purge_command_returns_zero(self):
        from worker.commands import PurgeCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root

        args = argparse.Namespace(older_than="30d", folders="done,error")
        with patch("worker.commands.emit_one"):
            rc = PurgeCommand.run(args)

        self.assertEqual(rc, 0)

    def test_purge_command_emits_counts(self):
        from worker.commands import PurgeCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root

        emitted = {}

        def capture(data):
            emitted.update(data)

        args = argparse.Namespace(older_than="30d", folders="done")
        with patch("worker.commands.emit_one", side_effect=capture):
            PurgeCommand.run(args)

        self.assertIn("done", emitted)

    def test_purge_command_parses_folder_list(self):
        from worker.commands import PurgeCommand
        from worker import queue as q
        q.QUEUE_ROOT = self.root

        called_with = {}

        def _fake_purge(secs, root, folders):
            called_with["folders"] = folders
            return {"done": 0, "error": 0}

        args = argparse.Namespace(older_than="7d", folders="done,error")
        with patch("worker.commands.q.purge", side_effect=_fake_purge), \
             patch("worker.commands.emit_one"):
            PurgeCommand.run(args)

        self.assertIn("done", called_with["folders"])
        self.assertIn("error", called_with["folders"])


# ---------------------------------------------------------------------------
# _join_with_timeout
# ---------------------------------------------------------------------------

class TestJoinWithTimeout(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_join_threads_with_zero_timeout(self):
        from worker.commands import DaemonRunner, JobProcessor, WorkerConfig
        from worker import queue as q
        q.QUEUE_ROOT = self.root

        cfg = WorkerConfig()
        proc = MagicMock(spec=JobProcessor)
        runner = DaemonRunner(cfg, proc)

        done_events = []

        def _work():
            done_events.append(True)

        threads = [threading.Thread(target=_work) for _ in range(3)]
        timeouts = [0, 0, 0]  # zero means join indefinitely

        for t in threads:
            t.start()

        runner._join_with_timeout(threads, timeouts)
        self.assertEqual(len(done_events), 3)

    def test_join_threads_with_positive_timeout(self):
        from worker.commands import DaemonRunner, JobProcessor, WorkerConfig
        from worker import queue as q
        q.QUEUE_ROOT = self.root

        cfg = WorkerConfig()
        proc = MagicMock(spec=JobProcessor)
        runner = DaemonRunner(cfg, proc)

        def _fast():
            pass

        threads = [threading.Thread(target=_fast)]
        for t in threads:
            t.start()

        # Should complete quickly with 10s timeout
        runner._join_with_timeout(threads, [10])
        self.assertFalse(threads[0].is_alive())


if __name__ == "__main__":
    unittest.main()
