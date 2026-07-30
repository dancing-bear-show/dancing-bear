"""Tests for JobSafeProcessor/JobResultProducer and ShellJobProcessor (C8 coverage).

Covers the SafeProcessor/BaseProducer wrappers introduced in normalize-domains:
- JobSafeProcessor: happy-path (known handler) and sad-paths (unknown handler, handler raises)
- JobResultProducer: happy-path (success outcome dispatched to q.finish)
- ShellJobProcessor: happy-path (exit-0 subprocess) and sad-paths (timeout, OSError)
"""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from tests.worker_tests.helpers import QueueRootIsolationMixin, _make_root


# ---------------------------------------------------------------------------
# JobSafeProcessor
# ---------------------------------------------------------------------------


class TestJobSafeProcessorHappyPath(unittest.TestCase):
    """Consumer → JobSafeProcessor → JobResult: known handler returns success."""

    def test_known_handler_success_returns_job_result(self):
        from worker.commands import JobRequest, JobResult, JobSafeProcessor
        from core.pipeline import RequestConsumer

        def _ok_handler(job_data):
            return (True, {"output": "done"})

        with patch("worker.commands.HANDLERS", {"my_type": _ok_handler}):
            proc = JobSafeProcessor("my_type", {"type": "my_type", "payload": {}})
            request = JobRequest(job_id="abc", payload={})
            envelope = proc.process(RequestConsumer(request).consume())

        self.assertTrue(envelope.ok())
        result = envelope.unwrap()
        self.assertIsInstance(result, JobResult)
        self.assertEqual(result.outcome, "success")

    def test_known_handler_failure_outcome_carries_error_string(self):
        from worker.commands import JobRequest, JobResult, JobSafeProcessor
        from core.pipeline import RequestConsumer

        def _fail_handler(job_data):
            return (False, "something went wrong")

        with patch("worker.commands.HANDLERS", {"bad_type": _fail_handler}):
            proc = JobSafeProcessor("bad_type", {"type": "bad_type", "payload": {}})
            request = JobRequest(job_id="xyz", payload={})
            envelope = proc.process(RequestConsumer(request).consume())

        self.assertTrue(envelope.ok())
        result = envelope.unwrap()
        self.assertIsInstance(result, JobResult)
        self.assertEqual(result.outcome, "something went wrong")
        self.assertIn("something went wrong", result.logs)


class TestJobSafeProcessorSadPaths(unittest.TestCase):
    """Sad-paths: unknown handler raises UsageError; handler exception is caught by SafeProcessor."""

    def test_unknown_handler_raises_usage_error(self):
        from worker.commands import JobRequest, JobSafeProcessor
        from core.pipeline import RequestConsumer

        with patch("worker.commands.HANDLERS", {}):
            proc = JobSafeProcessor("nonexistent_type", {"type": "nonexistent_type"})
            request = JobRequest(job_id="u1", payload={})
            # SafeProcessor catches the raised UsageError and wraps it in a failed envelope
            envelope = proc.process(RequestConsumer(request).consume())

        self.assertFalse(envelope.ok())
        msg = (envelope.diagnostics or {}).get("message", "")
        self.assertIn("unknown handler", msg)

    def test_handler_exception_produces_failed_envelope(self):
        from worker.commands import JobRequest, JobSafeProcessor
        from core.pipeline import RequestConsumer

        def _boom(job_data):
            raise RuntimeError("handler exploded")

        with patch("worker.commands.HANDLERS", {"boom_type": _boom}):
            proc = JobSafeProcessor("boom_type", {"type": "boom_type"})
            request = JobRequest(job_id="b1", payload={})
            envelope = proc.process(RequestConsumer(request).consume())

        self.assertFalse(envelope.ok())
        msg = (envelope.diagnostics or {}).get("message", "")
        self.assertIn("handler exploded", msg)


# ---------------------------------------------------------------------------
# JobResultProducer
# ---------------------------------------------------------------------------


class TestJobResultProducerHappyPath(unittest.TestCase, QueueRootIsolationMixin):
    """Consumer → JobSafeProcessor → JobResultProducer: success outcome → q.finish."""

    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()
        from worker.queue import finish as _real_finish
        self._real_finish = _real_finish

    def _patched_finish(self, job_path, success, **kwargs):
        kwargs["root"] = self.root
        return self._real_finish(job_path, success, **kwargs)

    def test_success_outcome_dispatches_to_queue_finish(self):
        from worker.commands import (
            JobContext,
            JobResult,
            JobResultProducer,
            WorkerConfig,
        )
        from core.pipeline import ResultEnvelope
        from worker.queue import Job, enqueue, start_processing
        from worker import queue as q

        q.QUEUE_ROOT = self.root
        pending = enqueue(Job(id="rp_ok", type="noop", payload={}), root=self.root)
        proc_path = start_processing(pending, self.root)
        ctx = JobContext.from_item(pending, {"type": "noop", "attempts": 0, "max_attempts": 3})

        # Build a success envelope directly
        envelope = ResultEnvelope(status="success", payload=JobResult(outcome="success", logs=[]))
        producer = JobResultProducer(
            proc_path=proc_path,
            ctx=ctx,
            duration=10,
            command="daemon",
            config=WorkerConfig(),
        )
        with patch("worker.commands.log_perf_jsonl"), \
             patch("worker.commands.q.finish", side_effect=self._patched_finish):
            producer.produce(envelope)

        self.assertTrue((self.root / "done" / "rp_ok.json").exists())

    def test_error_envelope_skips_produce_success(self):
        """BaseProducer.produce() skips _produce_success on failed envelopes."""
        from worker.commands import (
            JobContext,
            JobResultProducer,
            WorkerConfig,
        )
        from core.pipeline import ResultEnvelope
        from worker.queue import Job, enqueue, start_processing
        from worker import queue as q

        q.QUEUE_ROOT = self.root
        pending = enqueue(Job(id="rp_err", type="noop", payload={}), root=self.root)
        proc_path = start_processing(pending, self.root)
        ctx = JobContext.from_item(pending, {"type": "noop", "attempts": 0, "max_attempts": 3})

        # Failed envelope — produce() should not call _produce_success
        envelope = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"message": "handler failed"},
        )
        producer = JobResultProducer(
            proc_path=proc_path,
            ctx=ctx,
            duration=5,
            command="daemon",
            config=WorkerConfig(),
        )
        with patch.object(producer, "_produce_success") as mock_ps:
            producer.produce(envelope)

        mock_ps.assert_not_called()


# ---------------------------------------------------------------------------
# ShellJobProcessor
# ---------------------------------------------------------------------------


class TestShellJobProcessorHappyPath(unittest.TestCase):
    """ShellJobProcessor happy-path: zero-exit subprocess returns ShellJobResult."""

    def test_success_subprocess_returns_shell_job_result(self):
        from worker.handlers import ShellJobProcessor, ShellJobRequest, ShellJobResult
        from core.pipeline import RequestConsumer

        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "hello\n"
        fake_result.stderr = ""

        with patch("worker.handlers.subprocess.run", return_value=fake_result):
            proc = ShellJobProcessor()
            request = ShellJobRequest(cmd=["echo", "hello"], env_overlay={}, timeout=10, cwd=None)
            envelope = proc.process(RequestConsumer(request).consume())

        self.assertTrue(envelope.ok())
        result = envelope.unwrap()
        self.assertIsInstance(result, ShellJobResult)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.stdout)
        self.assertTrue(result.ok())

    def test_nonzero_exit_still_returns_result_not_exception(self):
        from worker.handlers import ShellJobProcessor, ShellJobRequest, ShellJobResult
        from core.pipeline import RequestConsumer

        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = ""
        fake_result.stderr = "error output"

        with patch("worker.handlers.subprocess.run", return_value=fake_result):
            proc = ShellJobProcessor()
            request = ShellJobRequest(cmd=["false"], env_overlay={}, timeout=10, cwd=None)
            envelope = proc.process(RequestConsumer(request).consume())

        self.assertTrue(envelope.ok())
        result = envelope.unwrap()
        self.assertIsInstance(result, ShellJobResult)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(result.ok())


class TestShellJobProcessorSadPaths(unittest.TestCase):
    """Sad-paths: subprocess.TimeoutExpired and OSError surface as failed envelopes."""

    def test_timeout_expired_produces_failed_envelope(self):
        from worker.handlers import ShellJobProcessor, ShellJobRequest
        from core.pipeline import RequestConsumer

        with patch(
            "worker.handlers.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["sleep", "99"], timeout=1),
        ):
            proc = ShellJobProcessor()
            request = ShellJobRequest(cmd=["sleep", "99"], env_overlay={}, timeout=1, cwd=None)
            envelope = proc.process(RequestConsumer(request).consume())

        self.assertFalse(envelope.ok())
        msg = (envelope.diagnostics or {}).get("message", "")
        self.assertTrue(len(msg) > 0)

    def test_os_error_produces_failed_envelope(self):
        from worker.handlers import ShellJobProcessor, ShellJobRequest
        from core.pipeline import RequestConsumer

        with patch(
            "worker.handlers.subprocess.run",
            side_effect=OSError("No such file"),
        ):
            proc = ShellJobProcessor()
            request = ShellJobRequest(
                cmd=["/nonexistent/cmd"], env_overlay={}, timeout=10, cwd=None
            )
            envelope = proc.process(RequestConsumer(request).consume())

        self.assertFalse(envelope.ok())
        msg = (envelope.diagnostics or {}).get("message", "")
        self.assertIn("No such file", msg)


if __name__ == "__main__":
    unittest.main()
