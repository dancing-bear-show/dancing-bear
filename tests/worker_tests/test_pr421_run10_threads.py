"""Regression tests for PR #421 review thread on duplicate-id claims.

``enqueue()`` accepts an explicit id and writes pending/ without looking at
processing/, so a second pending copy can exist for a job that is already
running. Claiming that copy used ``Path.replace`` into processing/, which
silently overwrote the active claim's record -- its claim token and payload --
before any ownership check could protect it. ``start_processing`` now refuses
the claim under the transition lock and leaves the duplicate pending, and both
claim loops skip pending jobs whose id is already in processing/ so the
duplicate cannot take a slot another job could use.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from tests.worker_tests.helpers import QueueRootIsolationMixin
from worker import queue_ops as q
from worker.job_runtime import DaemonRunner, JobProcessor, WorkerConfig
from worker.queue_ops import Job, enqueue


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def _make_runner(**config_kwargs: Any) -> DaemonRunner:
    cfg = WorkerConfig(**config_kwargs)
    return DaemonRunner(cfg, JobProcessor(cfg, "daemon"))


class _Base(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()
        self.pending = self.root / "pending"
        self.processing = self.root / "processing"

    def _active_claim(self, job_id: str) -> tuple[Path, str, bytes]:
        """Enqueue and claim ``job_id``; return its path, token and record bytes."""
        pending = enqueue(Job(id=job_id, type="noop", payload={"gen": 1}), root=self.root)
        claim = q.start_processing(pending, self.root)
        if claim is None or not claim[1]:
            self.fail(f"could not claim {job_id}")
        proc, token = claim
        return proc, token, proc.read_bytes()

    def _enqueue_duplicate(self, job_id: str, *, priority: int = 5) -> Path:
        return enqueue(
            Job(id=job_id, type="noop", payload={"gen": 2}, priority=priority),
            root=self.root,
        )


class TestDuplicateClaimIsRefused(_Base):
    def test_duplicate_claim_leaves_active_record_untouched(self) -> None:
        proc, token, before = self._active_claim("x")
        dup = self._enqueue_duplicate("x")

        with self.assertLogs("worker.queue_ops", "WARNING") as logs:
            self.assertIsNone(q.start_processing(dup, self.root))

        self.assertEqual(proc.read_bytes(), before, "active claim's record was rewritten")
        self.assertEqual(q.claim_token(proc), token)
        self.assertEqual(json.loads(proc.read_text())["payload"], {"gen": 1})
        self.assertTrue(dup.exists(), "the duplicate must stay pending")
        self.assertTrue(any("x" in line for line in logs.output))

    def test_duplicate_is_claimable_once_active_claim_finishes(self) -> None:
        proc, token, _ = self._active_claim("x")
        dup = self._enqueue_duplicate("x")
        self.assertIsNone(q.start_processing(dup, self.root))

        self.assertIsNotNone(q.finish(proc, True, root=self.root, claim_token=token))
        claim = q.start_processing(dup, self.root)

        if claim is None:
            self.fail("duplicate was not claimable after the active claim finished")
        new_proc, new_token = claim
        self.assertTrue(new_token)
        self.assertNotEqual(new_token, token)
        self.assertEqual(json.loads(new_proc.read_text())["payload"], {"gen": 2})
        self.assertEqual(_names(self.pending), [])


class TestClaimLoopsSkipAlreadyRunningIds(_Base):
    """The duplicate must not occupy the only slot and starve other pending jobs."""

    def _setup_queue(self) -> bytes:
        _, _, before = self._active_claim("x")
        # Priority 1 sorts the duplicate ahead of "y", into the single slot.
        self._enqueue_duplicate("x", priority=1)
        enqueue(Job(id="y", type="noop", payload={}, priority=9), root=self.root)
        return before

    def _assert_y_claimed_x_untouched(self, before: bytes) -> None:
        self.assertEqual((self.processing / "x.json").read_bytes(), before)
        self.assertIn("x.json", _names(self.pending), "duplicate must stay pending")
        self.assertNotIn("y.json", _names(self.pending), "y was never claimed")

    def test_run_once_claims_next_job_instead_of_duplicate(self) -> None:
        before = self._setup_queue()
        runner = _make_runner(max_per_tick=1)

        runner._run_once_batch()

        self._assert_y_claimed_x_untouched(before)

    def test_daemon_tick_claims_next_job_instead_of_duplicate(self) -> None:
        before = self._setup_queue()
        runner = _make_runner(max_per_tick=1)

        runner.tick()
        entry = runner._live_threads.get("y")
        if entry is not None:
            entry[0].join(timeout=5)

        self.assertNotIn("x", runner._live_threads)
        self._assert_y_claimed_x_untouched(before)


if __name__ == "__main__":
    unittest.main()
