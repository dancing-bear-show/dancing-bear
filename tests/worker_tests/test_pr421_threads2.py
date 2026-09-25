"""Regression tests for PR #421 review threads, round 3.

Pre-fix behaviour (0a62f195):
- Ownership (PRRT_kwDOQr1kjM6lWhMg): after a drain requeued a running job,
  the job's thread still finished, and ``retry()``/``finish()`` loaded the
  missing processing/ file as ``{}``. ``retry()`` overwrote the requeued
  pending/ copy with near-empty metadata; ``finish()`` wrote a done/ or
  error/ record for a job that was back in pending/. A job re-claimed by
  another worker in between had its processing/ file finished by the stale
  thread.
- No-clobber fallback (PRRT_kwDOQr1kjM6lWhNC): without hard links the
  publish checked ``dest.exists()`` and then replaced it, so a pending/ file
  created in between was overwritten.
- Recovery (PRRT_kwDOQr1kjM6lWhNp): only ``run_daemon`` recovered staged
  requeues; ``run_once`` left a ``*.json.requeue`` file invisible.
- Thread start (PRRT_kwDOQr1kjM6lXFQk): a ``Thread.start()`` failure after
  the claim left the job in processing/ with a dead registry entry that
  ``drain_live_threads`` skipped.
"""

from __future__ import annotations

import errno
import json
import os
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.worker_tests.helpers import QueueRootIsolationMixin
from tests.worker_tests.test_daemon_nonblocking import _make_runner, _patch_queue_root
from worker import queue_ops as q
from worker.queue_ops import Job, enqueue

_REAL_START = threading.Thread.start
_REAL_REPLACE = Path.replace
_REAL_OPEN = os.open


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def _claim(test: unittest.TestCase, pending: Path, root: Path) -> Path:
    """Claim ``pending`` as a worker would; fail the test if the claim is lost."""
    proc = q.start_processing(pending, root)
    if proc is None:
        test.fail(f"could not claim {pending.name}")
    return proc


class _Gated:
    """Handler that blocks until ``gate`` opens, then returns ``result``."""

    def __init__(self, result: tuple[bool, object]) -> None:
        self.gate = threading.Event()
        self.started = threading.Event()
        self._result = result

    def __call__(self, job_data: dict[str, object]) -> tuple[bool, object]:
        self.started.set()
        self.gate.wait(timeout=5)
        return self._result


class _RuntimeTestBase(unittest.TestCase, QueueRootIsolationMixin):
    """Temp queue root, every job_runtime queue call redirected to it."""

    def setUp(self) -> None:
        self.setup_queue_root()
        self.stack = _patch_queue_root(self.root)
        self.addCleanup(self.stack.close)
        self._threads_before = set(threading.enumerate())
        self.addCleanup(self._join_new_threads)

    def _join_new_threads(self) -> None:
        for t in threading.enumerate():
            if t not in self._threads_before and t.ident is not None:
                t.join(timeout=10)

    def _handlers(self, mapping: dict[str, Callable[[dict[str, object]], tuple[bool, object]]]) -> None:
        self.stack.enter_context(patch.dict("worker.job_runtime.HANDLERS", mapping))


# ---------------------------------------------------------------------------
# PRRT_kwDOQr1kjM6lWhMg: outcome transitions verify ownership
# ---------------------------------------------------------------------------


class TestOutcomeAfterDrainRequeue(_RuntimeTestBase):
    """A job requeued by the drain keeps its metadata whatever its thread does next."""

    def _run_then_drain(self, result: tuple[bool, object]) -> Path:
        handler = _Gated(result)
        self.addCleanup(handler.gate.set)
        self._handlers({"slow": handler})
        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(
            Job(id="j1", type="slow", payload={"k": 1}, attempts=2, max_attempts=5),
            root=self.root,
        )
        self.assertEqual(runner.tick(), 1)
        self.assertTrue(handler.started.wait(timeout=5), "handler never started")
        with self.assertLogs("worker.job_runtime", "WARNING"):
            self.assertEqual(runner.drain_live_threads(grace=0), ["j1"])
        thread = runner._live_threads["j1"]
        handler.gate.set()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        return self.root / "pending" / "j1.json"

    def _assert_requeued_copy_intact(self, pending: Path) -> None:
        self.assertEqual(_names(self.root / "pending"), ["j1.json"])
        data = _read(pending)
        self.assertEqual(data["payload"], {"k": 1})
        self.assertEqual(data["type"], "slow")
        self.assertEqual(data["attempts"], 2)
        self.assertEqual(data["last_error"], q.SHUTDOWN_REQUEUE_REASON)
        self.assertEqual(_names(self.root / "done"), [])
        self.assertEqual(_names(self.root / "error"), [])
        self.assertEqual(_names(self.root / "processing"), [])

    def test_retryable_error_after_requeue_keeps_pending_copy(self) -> None:
        self._assert_requeued_copy_intact(self._run_then_drain((False, "boom")))

    def test_deferred_after_requeue_keeps_pending_copy(self) -> None:
        self._assert_requeued_copy_intact(self._run_then_drain((False, "deferred-later")))

    def test_success_after_requeue_writes_no_done_record(self) -> None:
        self._assert_requeued_copy_intact(self._run_then_drain((True, "ok")))

    def test_terminal_after_requeue_writes_no_error_record(self) -> None:
        self._assert_requeued_copy_intact(self._run_then_drain((False, "terminal-x")))

    def test_stale_thread_leaves_another_workers_claim_alone(self) -> None:
        """Requeued, then re-claimed elsewhere: the stale thread must not finish it."""
        handler = _Gated((True, "ok"))
        self.addCleanup(handler.gate.set)
        self._handlers({"slow": handler})
        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="j2", type="slow", payload={"k": 2}), root=self.root)
        runner.tick()
        self.assertTrue(handler.started.wait(timeout=5))
        with self.assertLogs("worker.job_runtime", "WARNING"):
            runner.drain_live_threads(grace=0)
        other = _claim(self, self.root / "pending" / "j2.json", self.root)
        before = other.read_bytes()

        thread = runner._live_threads["j2"]
        handler.gate.set()
        thread.join(timeout=5)

        self.assertTrue(other.exists(), "the other worker's claim was consumed")
        self.assertEqual(other.read_bytes(), before)
        self.assertEqual(_names(self.root / "done"), [])


class TestTransitionsRefuseMissingSource(unittest.TestCase, QueueRootIsolationMixin):
    """finish()/retry() never write a record from an absent processing/ file."""

    def setUp(self) -> None:
        self.setup_queue_root()
        enqueue(Job(id="m1", type="t", payload={"k": 1}, attempts=3), root=self.root)
        self.pending = self.root / "pending" / "m1.json"
        self.before = self.pending.read_bytes()
        self.missing = self.root / "processing" / "m1.json"

    def test_retry_of_missing_file_leaves_pending_untouched(self) -> None:
        with self.assertLogs("worker.queue_ops", "WARNING"):
            self.assertIsNone(q.retry(self.missing, delay_sec=0, root=self.root))
        self.assertEqual(self.pending.read_bytes(), self.before)

    def test_finish_of_missing_file_writes_nothing(self) -> None:
        for success in (True, False):
            with self.subTest(success=success), self.assertLogs("worker.queue_ops", "WARNING"):
                self.assertIsNone(q.finish(self.missing, success, root=self.root))
        self.assertEqual(_names(self.root / "done"), [])
        self.assertEqual(_names(self.root / "error"), [])

    def test_wrong_claim_token_is_refused(self) -> None:
        proc = _claim(self, self.pending, self.root)
        before = proc.read_bytes()
        with self.assertLogs("worker.queue_ops", "WARNING"):
            self.assertIsNone(q.finish(proc, True, root=self.root, claim_token="not-mine"))  # nosec B106 - claim token, not a secret
        self.assertEqual(proc.read_bytes(), before)
        self.assertEqual(_names(self.root / "done"), [])

    def test_matching_claim_token_transitions(self) -> None:
        proc = _claim(self, self.pending, self.root)
        token = q.claim_token(proc)
        self.assertTrue(token)
        new = q.retry(proc, delay_sec=0, root=self.root, claim_token=token)
        self.assertEqual(new, self.pending)
        data = _read(self.pending)
        self.assertEqual((data["attempts"], data["payload"], data["status"]), (4, {"k": 1}, "pending"))
        self.assertNotIn(q.CLAIM_TOKEN_FIELD, data)
        self.assertEqual(_names(self.root / "processing"), [])


# ---------------------------------------------------------------------------
# PRRT_kwDOQr1kjM6lWhNC: no-clobber publish without hard links
# ---------------------------------------------------------------------------


class TestPublishWithoutHardLinks(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()
        paths = q._ensure_dirs(self.root)
        self.staged = paths["processing"] / "p1.json.requeue"
        self.staged.write_text(json.dumps({"id": "p1", "payload": {"mine": True}}), encoding="utf-8")
        self.dest = paths["pending"] / "p1.json"
        self.rival = json.dumps({"id": "p1", "payload": {"theirs": True}})
        link = patch("worker.queue_ops.os.link", side_effect=OSError(errno.EPERM, "no links"))
        link.start()
        self.addCleanup(link.stop)

    def _rival_creates_dest_before(self, real: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap a publish syscall so another worker creates ``dest`` just before it."""

        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            target = args[1] if real is _REAL_REPLACE else args[0]
            if Path(target) == self.dest and not self.dest.exists():
                self.dest.write_text(self.rival, encoding="utf-8")
            return real(*args, **kwargs)

        return _wrapped

    def test_file_created_between_check_and_publish_is_not_overwritten(self) -> None:
        with patch.object(Path, "replace", self._rival_creates_dest_before(_REAL_REPLACE)), \
                patch("worker.queue_ops.os.open", self._rival_creates_dest_before(_REAL_OPEN)), \
                self.assertLogs("worker.queue_ops", "WARNING"):
            self.assertFalse(q._publish_no_clobber(self.staged, self.dest))
        self.assertEqual(self.dest.read_text(encoding="utf-8"), self.rival)
        self.assertTrue(self.staged.exists(), "staged job lost")
        self.assertEqual(_read(self.staged)["payload"], {"mine": True})

    def test_publishes_when_dest_is_free(self) -> None:
        self.assertTrue(q._publish_no_clobber(self.staged, self.dest))
        self.assertEqual(_read(self.dest)["payload"], {"mine": True})
        self.assertFalse(self.staged.exists())

    def test_missing_staged_file_returns_false(self) -> None:
        self.staged.unlink()
        self.assertFalse(q._publish_no_clobber(self.staged, self.dest))
        self.assertFalse(self.dest.exists())


# ---------------------------------------------------------------------------
# PRRT_kwDOQr1kjM6lWhNp: recovery on every queue-consuming entry point
# ---------------------------------------------------------------------------


class TestRunOnceRecoversStagedRequeues(_RuntimeTestBase):
    def test_run_once_recovers_and_runs_staged_job(self) -> None:
        ran: list[str] = []

        def _record(job_data: dict[str, object]) -> tuple[bool, object]:
            ran.append(str(job_data.get("id")))
            return True, "ok"

        self._handlers({"fast": _record})
        enqueue(Job(id="s1", type="fast", payload={}), root=self.root)
        proc = _claim(self, self.root / "pending" / "s1.json", self.root)
        staged = proc.with_name(proc.name + ".requeue")
        proc.rename(staged)

        runner = _make_runner(self.root, max_per_tick=1)
        self.assertEqual(runner.run_once(), 0)

        self.assertFalse(staged.exists(), "staged requeue left invisible")
        self.assertEqual(ran, ["s1"])
        self.assertEqual(_names(self.root / "done"), ["s1.json"])

    def test_recovery_waits_for_an_in_flight_transition(self) -> None:
        """A run-once beside a live worker must not publish a staged file mid-write."""
        staged = q._ensure_dirs(self.root)["processing"] / "s2.json.requeue"
        staged.write_text(json.dumps({"id": "s2", "status": "processing"}), encoding="utf-8")
        result: list[list[str]] = []
        with q._transition_lock(self.root):
            t = threading.Thread(target=lambda: result.append(q.recover_staged_requeues(self.root)))
            t.start()
            t.join(timeout=0.3)
            self.assertTrue(t.is_alive(), "recovery ran while a transition held the lock")
            self.assertTrue(staged.exists())
        t.join(timeout=5)
        self.assertEqual(result, [["s2"]])


# ---------------------------------------------------------------------------
# PRRT_kwDOQr1kjM6lXFQk: Thread.start failure after a claim
# ---------------------------------------------------------------------------


def _start_failing_on(call_numbers: set[int]) -> Callable[[threading.Thread], None]:
    """Thread.start stand-in raising on the given 1-based call numbers only."""
    counter = {"n": 0}
    lock = threading.Lock()

    def _start(self: threading.Thread) -> None:
        with lock:
            counter["n"] += 1
            n = counter["n"]
        if n in call_numbers:
            raise RuntimeError("can't start new thread")
        _REAL_START(self)

    return _start


class TestThreadStartFailure(_RuntimeTestBase):
    def setUp(self) -> None:
        super().setUp()
        self._handlers({"fast": lambda _d: (True, "ok")})

    def test_tick_requeues_claim_when_start_fails(self) -> None:
        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="t1", type="fast", payload={"k": 1}, attempts=1), root=self.root)
        with patch.object(threading.Thread, "start", _start_failing_on({1})), \
                self.assertLogs("worker.job_runtime", "ERROR"):
            self.assertEqual(runner.tick(), 0)
        self.assertEqual(runner._live_threads, {})
        self.assertEqual(_names(self.root / "processing"), [])
        data = _read(self.root / "pending" / "t1.json")
        self.assertEqual((data["payload"], data["attempts"]), ({"k": 1}, 1))

    def test_drain_requeues_a_registered_thread_that_never_started(self) -> None:
        runner = _make_runner(self.root)
        enqueue(Job(id="t2", type="fast", payload={"k": 2}), root=self.root)
        _claim(self, self.root / "pending" / "t2.json", self.root)
        runner._live_threads["t2"] = threading.Thread(target=lambda: None)

        with self.assertLogs("worker.job_runtime", "WARNING"):
            self.assertEqual(runner.drain_live_threads(grace=0), ["t2"])
        self.assertEqual(_names(self.root / "processing"), [])
        self.assertEqual(_read(self.root / "pending" / "t2.json")["payload"], {"k": 2})

    def test_run_once_joins_started_jobs_when_a_later_start_fails(self) -> None:
        runner = _make_runner(self.root, max_per_tick=2)
        enqueue(Job(id="a", type="fast", payload={}, priority=1), root=self.root)
        enqueue(Job(id="b", type="fast", payload={}, priority=2), root=self.root)
        with patch.object(threading.Thread, "start", _start_failing_on({2})), \
                self.assertLogs("worker.job_runtime", "ERROR"):
            self.assertEqual(runner.run_once(), 0)
        self.assertEqual(_names(self.root / "done"), ["a.json"], "started job was not joined")
        self.assertEqual(_names(self.root / "processing"), [])
        self.assertEqual(_names(self.root / "pending"), ["b.json"])


if __name__ == "__main__":
    unittest.main()
