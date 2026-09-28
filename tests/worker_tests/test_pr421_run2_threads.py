"""Regression tests for PR #421 run-2 review threads.

Covers the six correctness findings anchored to job_runtime.py:

Finding 1 (line 573, PRRT_kwDOQr1kjM6mf6Sz):
  claim_token() returns None when start_processing's metadata write fails;
  the claim must be treated as lost and the job requeued without starting a thread.

Finding 2 (line 732, PRRT_kwDOQr1kjM6mf6TE):
  drain_live_threads requeues only stems whose claim token still matches the
  one recorded at claim time; a token mismatch (another worker claimed it)
  skips the requeue.

Finding 3 (line 255, PRRT_kwDOQr1kjM6mgBcu):
  _undo_retry_attempt skips the write if the pending/ file is gone or empty
  after the retry() call, preventing ghost-job creation.

Finding 4 (line 591, PRRT_kwDOQr1kjM6mgBdG):
  _abandon_claim verifies the claim token still matches the processing/ file
  before calling requeue_processing; a changed token means another worker
  owns the record and we must not requeue it.

Findings 5 & 6 (lines 731/734, unlinked):
  drain_live_threads probes every registered stem regardless of whether the
  thread is still alive; a thread that exited via _run_guarded without
  processing_claimed completing can leave processing/<id>.json behind.
"""

from __future__ import annotations

import json
import threading
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
# Finding 1: missing claim token treated as failed claim
# ---------------------------------------------------------------------------


class TestMissingClaimTokenAbandonsClaim(unittest.TestCase, QueueRootIsolationMixin):
    """A None claim_token after start_processing causes the claim to be abandoned."""

    def setUp(self) -> None:
        self.setup_queue_root()
        base = _patch_queue_root(self.root)
        base.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"fast": lambda _d: (True, "ok")}))
        self.addCleanup(base.close)

    def test_none_claim_token_requeues_job_without_starting_thread(self) -> None:
        """Happy path: a real claim token lets the thread start normally."""
        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="tok1", type="fast", payload={"k": 1}, attempts=2), root=self.root)

        started = runner.tick()

        self.assertEqual(started, 1)
        self.assertTrue(_wait_for(lambda: (self.root / "done" / "tok1.json").exists(), timeout=5))
        self.assertFalse((self.root / "pending" / "tok1.json").exists())

    def test_sad_none_claim_token_requeues_job_without_starting_thread(self) -> None:
        """Sad path: when claim_token() returns None, the claim is abandoned
        and the job is requeued to pending/ without a thread being started."""
        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="tok2", type="fast", payload={"k": 2}, attempts=3), root=self.root)

        # Simulate a metadata-write failure: claim_token always returns None.
        with patch("worker.job_runtime.q.claim_token", return_value=None), \
             self.assertLogs("worker.job_runtime", "WARNING") as logs:
            started = runner.tick()

        self.assertEqual(started, 0, "thread must not start when claim_token is None")
        self.assertEqual(runner._live_threads, {})
        # Job must end up back in pending/ (requeued) with no done/ or error/ copy.
        pending = self.root / "pending" / "tok2.json"
        self.assertTrue(pending.exists(), "job must be requeued to pending/ when token is None")
        self.assertEqual(_names(self.root / "done"), [])
        self.assertIn("tok2", "\n".join(logs.output))


# ---------------------------------------------------------------------------
# Finding 2: drain skips requeue when token changed (another worker re-claimed)
# ---------------------------------------------------------------------------


class TestDrainSkipsRequeueOnTokenMismatch(unittest.TestCase, QueueRootIsolationMixin):
    """drain_live_threads does not requeue a job whose token changed after the
    original claim — another worker now owns the processing/ record."""

    def setUp(self) -> None:
        self.setup_queue_root()
        self.gate = threading.Event()

        def _gated(job_data: dict[str, object]) -> tuple[bool, object]:
            self.gate.wait(timeout=5)
            return True, "ok"

        base = _patch_queue_root(self.root)
        base.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"slow": _gated}))
        self.addCleanup(base.close)
        self.addCleanup(self.gate.set)
        self._threads_before = set(threading.enumerate())
        self.addCleanup(self._join_new_threads)

    def _join_new_threads(self) -> None:
        for t in threading.enumerate():
            if t not in self._threads_before and t.ident is not None:
                t.join(timeout=10)

    def test_happy_path_drain_requeues_job_with_matching_token(self) -> None:
        """Drain requeues a job whose processing/ token still matches our recorded token."""
        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="match1", type="slow", payload={}, attempts=1), root=self.root)
        runner.tick()
        # Wait for thread to reach handler.
        self.assertTrue(_wait_for(lambda: (self.root / "processing" / "match1.json").exists(), timeout=5))

        with self.assertLogs("worker.job_runtime", "WARNING"):
            requeued = runner.drain_live_threads(grace=0)

        self.assertEqual(requeued, ["match1"])
        self.assertTrue((self.root / "pending" / "match1.json").exists())

    def test_sad_path_drain_skips_requeue_when_token_changed(self) -> None:
        """Drain skips a job whose processing/ token changed after our original claim.

        Simulates: our thread published a deferred outcome (creating a new pending/ copy),
        another worker claimed that copy, and now drain must NOT move the other worker's
        processing/ record back to pending/.
        """
        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="foreign1", type="slow", payload={}, attempts=1), root=self.root)
        runner.tick()
        self.assertTrue(
            _wait_for(lambda: (self.root / "processing" / "foreign1.json").exists(), timeout=5)
        )

        # Simulate token change: write a different token to the processing/ file,
        # as another worker would do after re-claiming the job.
        proc = self.root / "processing" / "foreign1.json"
        data = _read(proc)
        data[q.CLAIM_TOKEN_FIELD] = "not-our-token"
        proc.write_text(json.dumps(data), encoding="utf-8")

        requeued = runner.drain_live_threads(grace=0)

        self.assertEqual(requeued, [], "must not requeue a job whose token changed")
        self.assertTrue(proc.exists(), "another worker's processing/ file was moved")
        self.assertEqual(_names(self.root / "pending"), [], "job must not appear in pending/")


# ---------------------------------------------------------------------------
# Finding 3: _undo_retry_attempt does not create ghost jobs
# ---------------------------------------------------------------------------


class TestUndoRetryAttemptNoGhostJob(unittest.TestCase, QueueRootIsolationMixin):
    """_undo_retry_attempt skips the write when the pending/ file is absent or empty."""

    def setUp(self) -> None:
        self.setup_queue_root()

    def test_happy_path_undo_corrects_attempts_on_present_file(self) -> None:
        """Happy path: pending/ file exists with full data → attempts are corrected."""
        from worker.job_runtime import _undo_retry_attempt

        paths = q._ensure_dirs(self.root)
        path = paths["pending"] / "undo1.json"
        path.write_text(
            json.dumps({"id": "undo1", "type": "t", "payload": {}, "attempts": 2}),
            encoding="utf-8",
        )

        _undo_retry_attempt("undo1", original_attempts=1, q_root=self.root)

        data = _read(path)
        self.assertEqual(data["attempts"], 1)
        self.assertEqual(data["type"], "t")  # payload preserved

    def test_sad_path_undo_skips_write_when_file_is_gone(self) -> None:
        """Sad path: pending/ file is gone (job was claimed) → no ghost job created.

        Before the fix, safe_load_json returned {} (default) and the next
        atomic_write_json wrote {"attempts": N} back, creating a ghost job
        with no payload/type/id — corrupting the queue.
        """
        from worker.job_runtime import _undo_retry_attempt

        q._ensure_dirs(self.root)
        pending_dir = self.root / "pending"

        # File is absent; _undo_retry_attempt must not create it.
        _undo_retry_attempt("ghost1", original_attempts=0, q_root=self.root)

        ghost = pending_dir / "ghost1.json"
        self.assertFalse(ghost.exists(), "ghost job was created from an absent pending/ file")

    def test_sad_path_undo_skips_write_when_file_is_empty(self) -> None:
        """Sad path: pending/ file contains {} (empty/unreadable) → no write."""
        from worker.job_runtime import _undo_retry_attempt

        paths = q._ensure_dirs(self.root)
        path = paths["pending"] / "empty1.json"
        # safe_load_json of "{}" is {} — same as the default; simulates a
        # partially written or raced-over file.
        path.write_text("{}", encoding="utf-8")

        _undo_retry_attempt("empty1", original_attempts=1, q_root=self.root)

        # File must remain as-is (not overwritten with just {"attempts": 1}).
        self.assertEqual(path.read_text(encoding="utf-8"), "{}")


# ---------------------------------------------------------------------------
# Finding 4: _abandon_claim checks token before requeueing
# ---------------------------------------------------------------------------


class TestAbandonClaimTokenCheck(unittest.TestCase, QueueRootIsolationMixin):
    """_abandon_claim does not requeue a job whose processing/ token changed."""

    def setUp(self) -> None:
        self.setup_queue_root()
        base = _patch_queue_root(self.root)
        self.addCleanup(base.close)

    def test_happy_path_abandon_requeues_when_token_matches(self) -> None:
        """Happy path: token still matches → job is requeued to pending/.

        _abandon_claim(stem, token) passes token to requeue_processing which
        validates ownership atomically under the transition lock.
        """
        runner = _make_runner(self.root, max_per_tick=1)
        pending = enqueue(Job(id="ab1", type="fast", payload={"k": 1}, attempts=2), root=self.root)
        proc = _real_start(pending, self.root)
        if proc is None:
            self.fail("could not claim ab1")
        token = q.claim_token(proc)
        if token is None:
            self.fail("no claim token written for ab1")

        # Register the claim in the runner registry and call _abandon_claim.
        runner._live_threads["ab1"] = (threading.Thread(target=lambda: None), token)
        # _abandon_claim logs at ERROR (logger.exception); provide the exc context.
        try:
            raise RuntimeError("thread start failed")
        except RuntimeError:
            runner._abandon_claim("ab1", token)

        pending_path = self.root / "pending" / "ab1.json"
        self.assertTrue(pending_path.exists(), "job must be requeued when token matches")
        self.assertEqual(_names(self.root / "processing"), [])

    def test_sad_path_abandon_skips_requeue_when_token_changed(self) -> None:
        """Sad path: token changed (another worker claimed it) → no requeue.

        requeue_processing validates the token under the transition lock;
        a mismatch returns None and nothing is written.
        """
        runner = _make_runner(self.root, max_per_tick=1)
        pending = enqueue(Job(id="ab2", type="fast", payload={"k": 2}, attempts=0), root=self.root)
        proc = _real_start(pending, self.root)
        if proc is None:
            self.fail("could not claim ab2")
        original_token = q.claim_token(proc)
        if original_token is None:
            self.fail("no claim token for ab2")

        # Another worker claims the same stem: write a new token to processing/.
        data = _read(proc)
        data[q.CLAIM_TOKEN_FIELD] = "other-workers-token"
        proc.write_text(json.dumps(data), encoding="utf-8")

        runner._live_threads["ab2"] = (threading.Thread(target=lambda: None), original_token)
        try:
            raise RuntimeError("thread start failed")
        except RuntimeError:
            runner._abandon_claim("ab2", original_token)

        # Pending/ must NOT gain a copy: the other worker's claim should be left alone.
        self.assertFalse(
            (self.root / "pending" / "ab2.json").exists(),
            "must not requeue when token changed (another worker's claim)",
        )
        # The processing/ file (owned by the other worker) must still be there.
        self.assertTrue(proc.exists(), "other worker's processing/ record was moved")


# ---------------------------------------------------------------------------
# Findings 5 & 6: dead threads with remaining processing/ records get requeued
# ---------------------------------------------------------------------------


class TestDrainRequeuesDeadThreadsWithResidualRecord(unittest.TestCase, QueueRootIsolationMixin):
    """drain_live_threads probes every registered stem regardless of alive state.

    A thread whose _run_guarded caught an exception outside process_claimed
    can exit while its processing/<id>.json remains.  The old code skipped
    dead threads, leaving the job stranded.
    """

    def setUp(self) -> None:
        self.setup_queue_root()
        base = _patch_queue_root(self.root)
        self.addCleanup(base.close)

    def _plant_processing_record(self, stem: str, token: str) -> Path:
        """Write a processing/ record with the given claim token."""
        paths = q._ensure_dirs(self.root)
        proc = paths["processing"] / f"{stem}.json"
        proc.write_text(
            json.dumps({
                "id": stem,
                "type": "t",
                "payload": {},
                "attempts": 0,
                "status": "processing",
                q.CLAIM_TOKEN_FIELD: token,
            }),
            encoding="utf-8",
        )
        return proc

    def test_happy_path_alive_thread_is_requeued(self) -> None:
        """Happy path: an alive registered thread's job is requeued on drain."""
        runner = _make_runner(self.root, max_per_tick=1)
        gate = threading.Event()
        self.addCleanup(gate.set)
        thread = threading.Thread(target=gate.wait, args=(5,), daemon=True)
        token = "my-token"  # nosec B105 - test claim token, not a secret
        thread.start()
        proc = self._plant_processing_record("alive1", token)
        runner._live_threads["alive1"] = (thread, token)

        with self.assertLogs("worker.job_runtime", "WARNING"):
            requeued = runner.drain_live_threads(grace=0)

        self.assertIn("alive1", requeued)
        self.assertTrue((self.root / "pending" / "alive1.json").exists())
        self.assertFalse(proc.exists())

    def test_sad_path_dead_thread_with_processing_record_is_requeued(self) -> None:
        """Sad path: a dead registered thread whose processing/ record remains
        is still requeued by drain_live_threads.

        Before the fix, drain skipped dead threads (the `continue` at line 730),
        so a thread that exited via _run_guarded without cleaning up its
        processing/ file would strand the job.
        """
        runner = _make_runner(self.root, max_per_tick=1)
        token = "dead-thread-token"  # nosec B105 - test claim token, not a secret
        # Thread that exits immediately (dead by the time drain runs).
        thread = threading.Thread(target=lambda: None, daemon=True)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "precondition: thread must be dead")

        proc = self._plant_processing_record("dead1", token)
        runner._live_threads["dead1"] = (thread, token)

        with self.assertLogs("worker.job_runtime", "WARNING"):
            requeued = runner.drain_live_threads(grace=0)

        self.assertIn("dead1", requeued, "dead thread's processing/ record must be requeued")
        self.assertTrue(
            (self.root / "pending" / "dead1.json").exists(),
            "job must land in pending/ after drain",
        )
        self.assertFalse(proc.exists(), "processing/ record must be removed after drain")

    def test_sad_path_dead_thread_without_processing_record_is_noop(self) -> None:
        """Sad path: a dead thread whose job already finished (no processing/ record)
        is a no-op in drain — requeue_processing returns None and nothing is created."""
        runner = _make_runner(self.root, max_per_tick=1)
        q._ensure_dirs(self.root)
        token = "finished-token"  # nosec B105 - test claim token, not a secret
        thread = threading.Thread(target=lambda: None, daemon=True)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())

        # No processing/ record: job already finished normally.
        runner._live_threads["fin1"] = (thread, token)

        requeued = runner.drain_live_threads(grace=0)

        self.assertNotIn("fin1", requeued, "a dead thread with no record must not create a phantom requeue")
        self.assertFalse(
            (self.root / "pending" / "fin1.json").exists(),
            "requeue_processing must not create a pending/ job from nothing",
        )


if __name__ == "__main__":
    unittest.main()
