"""Regression tests for PR #421 run-5 review threads.

Covers two findings raised after round 4's push (731f420):

Finding 1 (PRRT_kwDOQr1kjM6mhr1i, job_runtime.py _prune_live_threads):
  A queue I/O or transition-lock error from _prune_live_threads' new
  requeue_processing call (added in round 4) propagated out of tick() and
  would terminate run_daemon -- unlike drain_live_threads, which already had
  a per-stem error boundary. Fixed by wrapping the call in a try/except,
  logging the failure, and keeping (not popping) the registry entry so the
  stem is retried on a later tick.

Finding 2 (PRRT_kwDOQr1kjM6mhr1z, job_runtime.py drain_live_threads):
  lock_budget = max(0.1, remaining) floored the post-deadline lock_timeout
  budget at 0.1s even when the deadline had already passed (remaining <= 0),
  so every contended stem could still add up to 100ms past shutdown_grace --
  across many stems this could extend the drain well beyond the configured
  grace period. Fixed by flooring at 0.0 instead: _transition_lock still
  attempts one non-blocking acquisition at timeout=0.0 (so a free lock is
  still used), but a contended lock now fails immediately rather than
  waiting.

A third finding (PRRT_kwDOQr1kjM6mhqb-, a github-code-quality lint finding
about an unused local `_tok` in tests/worker_tests/test_pr421_threads.py's
_ContestedStart.__call__) has no new test here: it is a pure style fix with
no behavior change, already covered by that class's existing tests.
"""

from __future__ import annotations

import json
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.worker_tests.helpers import QueueRootIsolationMixin
from tests.worker_tests.test_daemon_nonblocking import (
    _make_runner,
    _patch_queue_root,
    _wait_for,
)
from worker.queue_ops import Job, enqueue
from worker import queue_ops as q


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Finding 1: _prune_live_threads keeps the registry entry on a failed requeue
# ---------------------------------------------------------------------------


class TestPruneLiveThreadsSurvivesRequeueError(unittest.TestCase, QueueRootIsolationMixin):
    """_prune_live_threads must not let a requeue_processing failure escape
    tick()/terminate run_daemon, and must retain the registry entry so the
    stem is retried on a later tick rather than being silently dropped."""

    def setUp(self) -> None:
        self.setup_queue_root()
        self.join_new_threads_before_restore()
        base = _patch_queue_root(self.root)
        base.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"fast": lambda _d: (True, "ok")}))
        self.addCleanup(base.close)

    def test_happy_path_normal_completion_still_prunes_cleanly(self) -> None:
        """A thread that finishes normally is pruned without error, same as
        before this fix."""
        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="prune5-ok", type="fast", payload={}), root=self.root)
        runner.tick()
        self.assertTrue(
            _wait_for(lambda: (self.root / "done" / "prune5-ok.json").exists(), timeout=5)
        )
        # The done/ record is written just before the worker thread returns,
        # so there is a small window where the file exists but the thread
        # object has not yet transitioned to not-alive. Join it directly
        # (bounded) rather than racing is_alive() against thread teardown.
        thread, _tok = runner._live_threads["prune5-ok"]
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "worker thread did not finish in time")
        runner._prune_live_threads()
        self.assertEqual(runner._live_threads, {})

    def test_sad_path_requeue_error_keeps_entry_for_retry(self) -> None:
        """When requeue_processing raises for a dead thread's stem,
        _prune_live_threads must log it, keep the registry entry (not pop
        it), and not let the exception propagate.

        Pre-fix: an uncaught exception here would propagate out of tick()
        and terminate run_daemon.
        """
        pending = enqueue(Job(id="prune5-err", type="fast", payload={}, attempts=1), root=self.root)
        real_start = q.start_processing
        claim = real_start(pending, self.root)
        self.assertIsNotNone(claim)
        assert claim is not None  # nosec B101 - narrows Optional for type checker
        _proc, token = claim

        runner = _make_runner(self.root, max_per_tick=1)
        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join()
        self.assertFalse(dead_thread.is_alive())
        runner._live_threads["prune5-err"] = (dead_thread, token)

        def _raise(*_a: object, **_kw: object) -> None:
            raise OSError("simulated I/O error during prune")

        with patch("worker.job_runtime.q.requeue_processing", side_effect=_raise), \
             self.assertLogs("worker.job_runtime", "ERROR"):
            runner._prune_live_threads()  # must not raise

        # The registry entry must survive so a later tick retries it.
        self.assertIn("prune5-err", runner._live_threads)


# ---------------------------------------------------------------------------
# Finding 2: drain_live_threads' post-deadline lock_timeout is not floored
# above zero
# ---------------------------------------------------------------------------


class TestDrainLockBudgetFloorsAtZero(unittest.TestCase, QueueRootIsolationMixin):
    """drain_live_threads must pass a lock_timeout of exactly 0.0 (not a
    small positive floor) once the shared deadline has passed, so a
    contended lock fails immediately instead of adding up to 100ms per
    stem across every contended job."""

    def setUp(self) -> None:
        self.setup_queue_root()
        self.join_new_threads_before_restore()

    def test_happy_path_uncontended_lock_still_succeeds_at_zero_budget(self) -> None:
        """A lock_timeout of 0.0 still lets an uncontended lock succeed:
        _transition_lock attempts one non-blocking acquisition before
        giving up."""
        gate = threading.Event()
        self.addCleanup(gate.set)

        def _slow(_d: dict[str, object]) -> tuple[bool, object]:
            gate.wait(timeout=5)
            return True, "ok"

        base = _patch_queue_root(self.root)
        base.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"slow": _slow}))
        self.addCleanup(base.close)

        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="lockfloor-ok", type="slow", payload={}), root=self.root)
        runner.tick()
        self.assertTrue(
            _wait_for(lambda: (self.root / "processing" / "lockfloor-ok.json").exists(), timeout=5)
        )

        # grace=0 means the deadline has already passed by the time the loop
        # reaches the requeue call, so lock_budget should floor at 0.0.
        with self.assertLogs("worker.job_runtime", "WARNING"):
            requeued = runner.drain_live_threads(grace=0.0)

        self.assertIn("lockfloor-ok", requeued)
        self.assertTrue((self.root / "pending" / "lockfloor-ok.json").exists())

    def test_sad_path_contended_lock_fails_fast_not_after_100ms_floor(self) -> None:
        """When the lock is contended and the deadline has passed, the
        lock_timeout passed to requeue_processing must be 0.0, not floored
        up to 0.1 -- verified by capturing the actual lock_timeout argument
        and asserting it is not positive once remaining time is exhausted.
        """
        gate = threading.Event()
        self.addCleanup(gate.set)

        def _slow(_d: dict[str, object]) -> tuple[bool, object]:
            gate.wait(timeout=5)
            return True, "ok"

        base = _patch_queue_root(self.root)
        base.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"slow": _slow}))
        self.addCleanup(base.close)

        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="lockfloor-contended", type="slow", payload={}, attempts=1), root=self.root)
        runner.tick()
        self.assertTrue(
            _wait_for(lambda: (self.root / "processing" / "lockfloor-contended.json").exists(), timeout=5)
        )

        captured_timeouts: list[float | None] = []
        real_requeue = q.requeue_processing

        def _capture(*args: object, **kwargs: object) -> Path | None:
            captured_timeouts.append(kwargs.get("lock_timeout"))  # type: ignore[arg-type]
            return real_requeue(*args, **kwargs)  # type: ignore[arg-type]

        with patch("worker.job_runtime.q.requeue_processing", side_effect=_capture), \
             self.assertLogs("worker.job_runtime", "WARNING"):
            # grace=0 means time.monotonic() + 0 as the deadline: by the time
            # the post-join loop reaches the requeue call, remaining is <= 0.
            runner.drain_live_threads(grace=0.0)

        self.assertEqual(len(captured_timeouts), 1)
        budget = captured_timeouts[0]
        self.assertIsNotNone(budget)
        assert budget is not None  # nosec B101 - narrows Optional for type checker
        self.assertLessEqual(
            budget, 0.05,
            "lock_timeout budget must not be floored above zero once the deadline has passed",
        )

    def test_transition_lock_with_zero_timeout_fails_immediately_when_held(self) -> None:
        """_transition_lock(timeout=0.0) raises _TransitionLockTimeout right
        away (one non-blocking attempt, no sleep loop) when the lock is
        already held elsewhere."""
        import fcntl

        lock_held = threading.Event()
        lock_release = threading.Event()
        lock_path = self.root / q._TRANSITION_LOCK_NAME
        self.root.mkdir(parents=True, exist_ok=True)

        def _hold_lock() -> None:
            with lock_path.open("a") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                lock_held.set()
                lock_release.wait(timeout=5)
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

        holder = threading.Thread(target=_hold_lock, daemon=True)
        holder.start()
        self.assertTrue(lock_held.wait(timeout=5), "background lock was not acquired")
        self.addCleanup(lock_release.set)
        self.addCleanup(holder.join)

        start = time.monotonic()
        with self.assertRaises(q._TransitionLockTimeout):
            with q._transition_lock(self.root, timeout=0.0):
                self.fail("lock must raise before this body executes")
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.05, "a zero-budget lock attempt must not sleep at all")


if __name__ == "__main__":
    unittest.main()
