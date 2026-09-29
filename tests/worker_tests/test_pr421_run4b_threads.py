"""Regression tests for PR #421 run-4b review threads.

Covers four findings raised after round 3's push (8dae3f5):

Finding 1 (PRRT_kwDOQr1kjM6mhE3K, job_runtime.py _prune_live_threads):
  When _run_guarded catches an exception from process_claimed, the thread
  exits while processing/<stem>.json remains on disk. _prune_live_threads was
  dropping the dead registry entry without requeueing, stranding the job in
  processing/. Fixed by calling requeue_processing (with the stored token for
  ownership verification) before removing the entry; requeue_processing is a
  safe no-op when the record is already gone (normal completion).

Finding 2 (PRRT_kwDOQr1kjM6mhE3V, job_runtime.py _claim + _start_batch,
           queue_ops.py start_processing):
  start_processing released _transition_lock before the caller's separate
  claim_token() read. In the window between the lock release and the re-read,
  another worker's reaper could reclaim the stem and write a new token; the
  re-read then returned the replacement token and the thread proceeded to
  process a job it did not own. Fixed by returning the token from
  start_processing as the second element of a (path, token) tuple, so callers
  never need a second file-read. claim_token() is retained for other uses.

Finding 3 (job_runtime.py drain_live_threads I/O exception in loop):
  An I/O or publish error from q.requeue_processing escaped the drain loop,
  aborting the shutdown drain before later registered jobs were probed and
  leaving them stranded in processing/. Fixed by wrapping each requeue call in
  a per-stem try/except, logging the error, and continuing.

Finding 4 (job_runtime.py drain_live_threads blocking past grace period):
  The shutdown deadline only bounded the preceding join() calls. Each
  requeue_processing call acquired the blocking _transition_lock, so if a live
  job was still inside finish()/retry() when the grace period expired, drain
  could wait beyond shutdown_grace. Fixed by adding an optional timeout
  parameter to _transition_lock (and threading it through _stage_and_requeue
  and requeue_processing), and by passing the remaining deadline budget as
  lock_timeout in drain_live_threads. A _TransitionLockTimeout (or other
  exception) is caught per-stem and the drain continues.
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
from worker.queue_ops import (
    Job,
    enqueue,
    start_processing as _real_start,
)
from worker import queue_ops as q


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


# ---------------------------------------------------------------------------
# Finding 1: _prune_live_threads requeues dead threads with residual records
# ---------------------------------------------------------------------------


class TestPruneLiveThreadsRequeuesDeadRecords(unittest.TestCase, QueueRootIsolationMixin):
    """_prune_live_threads must requeue a dead thread's processing/ record
    rather than silently dropping it from the registry."""

    def setUp(self) -> None:
        self.setup_queue_root()
        self.join_new_threads_before_restore()
        base = _patch_queue_root(self.root)
        base.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"fast": lambda _d: (True, "ok")}))
        self.addCleanup(base.close)

    def test_happy_path_completed_thread_leaves_no_residual(self) -> None:
        """A thread that finishes normally moves its job to done/; the next
        _prune_live_threads call removes the entry without requeueing."""
        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="prune-ok", type="fast", payload={}), root=self.root)
        runner.tick()
        # Wait for the job to complete.
        self.assertTrue(
            _wait_for(lambda: (self.root / "done" / "prune-ok.json").exists(), timeout=5)
        )
        # Thread is dead and processing/ is gone; pruning removes the entry safely.
        runner._prune_live_threads()
        self.assertEqual(runner._live_threads, {})
        self.assertEqual(_names(self.root / "pending"), [])
        self.assertFalse((self.root / "processing" / "prune-ok.json").exists())

    def test_sad_path_dead_thread_with_processing_record_is_requeued(self) -> None:
        """A thread that died (exception outside process_claimed) while its
        processing/ record remained is requeued by _prune_live_threads, so the
        job is not stranded.

        Simulated by injecting a dead thread whose processing/ record is still
        on disk. Previously _prune_live_threads just dropped the registry entry,
        leaving the job stuck in processing/ until either a timeout-based reap
        or a restart.
        """
        # Claim a job manually to get a real processing/ record and token.
        pending = enqueue(Job(id="prune-dead", type="fast", payload={}, attempts=1), root=self.root)
        claim = _real_start(pending, self.root)
        self.assertIsNotNone(claim)
        assert claim is not None  # nosec B101 - narrows Optional for type checker
        proc, token = claim

        # Inject the dead thread into the runner's registry.
        runner = _make_runner(self.root, max_per_tick=1)
        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join()  # ensure it is dead
        self.assertFalse(dead_thread.is_alive())
        runner._live_threads["prune-dead"] = (dead_thread, token)

        # _prune_live_threads should requeue the processing/ record.
        runner._prune_live_threads()

        # Registry entry must be gone.
        self.assertNotIn("prune-dead", runner._live_threads)
        # Job must be back in pending/ with its attempt count intact.
        pending_path = self.root / "pending" / "prune-dead.json"
        self.assertTrue(pending_path.exists(), "dead thread's processing/ record must be requeued")
        self.assertEqual(_read(pending_path)["attempts"], 1, "requeue must not consume an attempt")
        # Processing/ must be cleared.
        self.assertFalse(proc.exists(), "processing/ record must be removed by the requeue")


# ---------------------------------------------------------------------------
# Finding 2: start_processing returns the token atomically
# ---------------------------------------------------------------------------


class TestStartProcessingReturnsTokenAtomically(unittest.TestCase, QueueRootIsolationMixin):
    """start_processing returns (proc_path, token) so the caller never has to
    re-read the file to learn its own token."""

    def setUp(self) -> None:
        self.setup_queue_root()
        self.join_new_threads_before_restore()

    def test_happy_path_returned_token_matches_file_contents(self) -> None:
        """The token in the returned tuple matches what is written to disk."""
        pending = enqueue(Job(id="tok-match", type="noop", payload={}), root=self.root)
        result = q.start_processing(pending, self.root)
        self.assertIsNotNone(result)
        assert result is not None  # nosec B101 - narrows Optional for type checker
        proc_path, token = result
        self.assertTrue(token, "token must be non-empty after a successful claim")
        data = json.loads(proc_path.read_text(encoding="utf-8"))
        self.assertEqual(data.get(q.CLAIM_TOKEN_FIELD), token, "returned token must match the on-disk record")

    def test_sad_path_metadata_failure_returns_empty_token(self) -> None:
        """When the metadata write inside start_processing fails, the returned
        token is empty (not None), so the caller can distinguish a failed-metadata
        claim from a fully-lost claim (which returns None).

        _start_batch and process_one treat an empty token as a lost claim and
        requeue without running the handler."""
        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="tok-empty", type="fast", payload={}, attempts=1), root=self.root)

        ran: list[str] = []

        def _record(job_data: dict[str, object]) -> tuple[bool, object]:
            ran.append(str(job_data.get("id")))
            return True, "ok"

        real_start = q.start_processing

        def _start_empty_token(
            job_path: Path, root: Path | None = None
        ) -> tuple[Path, str] | None:
            result = real_start(job_path, root)
            if result is not None:
                proc, _tok = result
                data = json.loads(proc.read_text(encoding="utf-8"))
                data.pop(q.CLAIM_TOKEN_FIELD, None)
                proc.write_text(json.dumps(data), encoding="utf-8")
                return proc, ""
            return result

        with patch.dict("worker.job_runtime.HANDLERS", {"fast": _record}), \
             patch("worker.job_runtime.q.start_processing", side_effect=_start_empty_token), \
             self.assertLogs("worker.job_runtime", "WARNING"):
            started = runner.tick()

        self.assertEqual(started, 0, "no thread should start when the token is empty")
        self.assertEqual(ran, [], "handler must not run when the token is empty")
        # Job must be requeued, not stranded.
        pending_path = self.root / "pending" / "tok-empty.json"
        self.assertTrue(pending_path.exists(), "job must be requeued when token is empty")
        self.assertEqual(_names(self.root / "done"), [])

    def test_returns_none_when_already_claimed(self) -> None:
        """start_processing returns None (not a tuple) when the job was already
        claimed by another worker (FileNotFoundError on the rename)."""
        pending = enqueue(Job(id="tok-gone", type="noop", payload={}), root=self.root)
        # Claim once.
        first = q.start_processing(pending, self.root)
        self.assertIsNotNone(first)
        # Pending/ is gone now; a second claim attempt must return None.
        second = q.start_processing(pending, self.root)
        self.assertIsNone(second)


# ---------------------------------------------------------------------------
# Finding 3: drain_live_threads catches per-stem I/O errors and continues
# ---------------------------------------------------------------------------


class TestDrainContinuesAfterRequeueError(unittest.TestCase, QueueRootIsolationMixin):
    """An I/O or publish error for one stem must not abort the shutdown drain.
    The remaining registered jobs must still be probed and requeued."""

    def setUp(self) -> None:
        self.setup_queue_root()
        self.join_new_threads_before_restore()
        self._threads_before = set(threading.enumerate())
        self.addCleanup(self._join_new_threads)

    def _join_new_threads(self) -> None:
        for t in threading.enumerate():
            if t not in self._threads_before and t.ident is not None:
                t.join(timeout=10)

    def test_happy_path_all_stems_requeued_when_no_errors(self) -> None:
        """Happy path: all live stems are requeued when requeue_processing
        succeeds for each."""
        gate = threading.Event()
        self.addCleanup(gate.set)

        def _slow(_d: dict[str, object]) -> tuple[bool, object]:
            gate.wait(timeout=5)
            return True, "ok"

        base = _patch_queue_root(self.root)
        base.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"slow": _slow}))
        self.addCleanup(base.close)

        runner = _make_runner(self.root, max_per_tick=2)
        enqueue(Job(id="drain-a", type="slow", payload={}), root=self.root)
        enqueue(Job(id="drain-b", type="slow", payload={}), root=self.root)
        runner.tick()
        # Wait for both jobs to be processing.
        self.assertTrue(
            _wait_for(lambda: len(runner._live_threads) == 2, timeout=5),
            "both jobs should be running",
        )

        with self.assertLogs("worker.job_runtime", "WARNING"):
            requeued = runner.drain_live_threads(grace=0.2)

        self.assertEqual(sorted(requeued), ["drain-a", "drain-b"])
        self.assertTrue((self.root / "pending" / "drain-a.json").exists())
        self.assertTrue((self.root / "pending" / "drain-b.json").exists())

    def test_sad_path_error_on_first_stem_does_not_skip_second(self) -> None:
        """When requeue_processing raises an exception for one stem, drain must
        catch it, log it, and still probe the remaining stems.

        Pre-fix: an exception in the loop body aborted the drain, leaving later
        stems stranded in processing/.
        """
        gate = threading.Event()
        self.addCleanup(gate.set)

        def _slow(_d: dict[str, object]) -> tuple[bool, object]:
            gate.wait(timeout=5)
            return True, "ok"

        base = _patch_queue_root(self.root)
        base.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"slow": _slow}))
        self.addCleanup(base.close)

        runner = _make_runner(self.root, max_per_tick=2)
        enqueue(Job(id="err-first", type="slow", payload={}), root=self.root)
        enqueue(Job(id="ok-second", type="slow", payload={}), root=self.root)
        runner.tick()
        self.assertTrue(_wait_for(lambda: len(runner._live_threads) == 2, timeout=5))

        call_count = [0]
        real_requeue = q.requeue_processing

        def _fail_first(job_id: str, **kw: Any) -> Path | None:
            call_count[0] += 1
            if job_id == "err-first":
                raise OSError("simulated I/O error during drain")
            return real_requeue(job_id, **kw)

        with patch("worker.job_runtime.q.requeue_processing", side_effect=_fail_first), \
             self.assertLogs("worker.job_runtime", "ERROR"):
            requeued = runner.drain_live_threads(grace=0.2)

        # The second stem must still be requeued even though the first raised.
        self.assertIn("ok-second", requeued, "second stem must be requeued despite first error")
        self.assertNotIn("err-first", requeued)
        self.assertEqual(call_count[0], 2, "requeue must be attempted for both stems")
        self.assertTrue((self.root / "pending" / "ok-second.json").exists())


# ---------------------------------------------------------------------------
# Finding 4: drain respects shutdown grace via lock_timeout
# ---------------------------------------------------------------------------


class TestDrainRespectsDeadlineViaLockTimeout(unittest.TestCase, QueueRootIsolationMixin):
    """drain_live_threads passes a remaining-budget lock_timeout to
    requeue_processing so that a blocked _transition_lock cannot extend the
    drain beyond the configured shutdown grace period."""

    def setUp(self) -> None:
        self.setup_queue_root()
        self.join_new_threads_before_restore()
        # Registered after the temp-root cleanup, so it runs before it: a
        # handler thread released by a test's gate.set cleanup finishes its
        # queue transition before the temp tree is removed underneath it.
        self._threads_before = set(threading.enumerate())
        self.addCleanup(self._join_new_threads)

    def _join_new_threads(self) -> None:
        for t in threading.enumerate():
            if t not in self._threads_before and t.ident is not None:
                t.join(timeout=10)

    def test_happy_path_lock_acquired_quickly_requeues_job(self) -> None:
        """Happy path: no lock contention means requeue_processing succeeds
        normally within the budget."""
        gate = threading.Event()
        self.addCleanup(gate.set)

        def _slow(_d: dict[str, object]) -> tuple[bool, object]:
            gate.wait(timeout=5)
            return True, "ok"

        base = _patch_queue_root(self.root)
        base.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"slow": _slow}))
        self.addCleanup(base.close)

        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="lock-ok", type="slow", payload={}), root=self.root)
        runner.tick()
        self.assertTrue(
            _wait_for(lambda: (self.root / "processing" / "lock-ok.json").exists(), timeout=5)
        )

        with self.assertLogs("worker.job_runtime", "WARNING"):
            requeued = runner.drain_live_threads(grace=0.2)

        self.assertIn("lock-ok", requeued)
        self.assertTrue((self.root / "pending" / "lock-ok.json").exists())

    def test_sad_path_lock_timeout_logs_and_continues(self) -> None:
        """Sad path: when requeue_processing raises _TransitionLockTimeout (or
        any exception) while drain is trying to requeue, the stem is logged and
        skipped — drain must not block indefinitely or abort.

        _TransitionLockTimeout is raised by _transition_lock when a non-None
        timeout is given and the lock cannot be acquired in time.
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
        enqueue(Job(id="lock-timeout", type="slow", payload={}, attempts=1), root=self.root)
        runner.tick()
        self.assertTrue(
            _wait_for(lambda: (self.root / "processing" / "lock-timeout.json").exists(), timeout=5)
        )

        def _raise_lock_timeout(job_id: str, **kw: Any) -> Path | None:
            raise q._TransitionLockTimeout("simulated lock timeout during drain")

        with patch("worker.job_runtime.q.requeue_processing", side_effect=_raise_lock_timeout), \
             self.assertLogs("worker.job_runtime", "ERROR") as logs:
            requeued = runner.drain_live_threads(grace=0.5)

        self.assertEqual(requeued, [], "no job requeued when all locks timed out")
        # Must not hang: the entire drain must finish quickly.
        self.assertIn("lock-timeout", "\n".join(logs.output), "skipped stem must be logged")

    def test_transition_lock_timeout_raises_when_held(self) -> None:
        """_transition_lock raises _TransitionLockTimeout when the lock is held
        by another thread and the timeout elapses."""
        import fcntl

        # Acquire the lock in a background thread and hold it.
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

        # _transition_lock with a short timeout must raise rather than block.
        start = time.monotonic()
        with self.assertRaises(q._TransitionLockTimeout):
            with q._transition_lock(self.root, timeout=0.1):
                self.fail("lock must raise before this body executes")
        elapsed = time.monotonic() - start
        # Must not have blocked past the timeout by more than a small margin.
        self.assertLess(elapsed, 0.5, "lock acquisition must not block significantly past the timeout")

    def test_transition_lock_blocking_default_still_acquires(self) -> None:
        """The default (no timeout) still acquires the lock normally."""
        acquired = []
        with q._transition_lock(self.root):
            acquired.append(True)
        self.assertEqual(acquired, [True], "lock body must execute exactly once")


if __name__ == "__main__":
    unittest.main()
