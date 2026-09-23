"""Tests for the qwen model-call concurrency guard (contract.json:concurrency).

The lock protects the machine from running two model generations at once, so
it is tested at the level that matters: the number of /api/generate requests
that reached the transport, not just the handler's return value. A test that
only checks the return value would pass even if the handler generated anyway
and discarded the result.

Stale-lock rule is the CONTRACT's, not a plain age check:
  dead holder PID                          -> STALE, reclaim
  alive holder, age <= stale_ceiling_sec    -> active, wait
  alive holder, age  > stale_ceiling_sec    -> SUSPECT, reclaim ONLY IF
      _pid_is_worker(pid) is False OR the lane is empty

QwenHandlerCase points _lock_path at the test temp dir, so no test here
touches the real worker state dir.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import unittest
import urllib.error
import unittest.mock as mock

from worker import qwen
from tests.worker_tests.qwen_fixtures import QwenHandlerCase


class QwenLockHeldTests(QwenHandlerCase):
    def test_lock_already_held_returns_exact_deferred_busy_prefix(self) -> None:
        with mock.patch("worker.qwen._acquire_model_lock", return_value=False):
            ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, "deferred-qwen-busy"))
        self.assertEqual(self.generate_requests(), [])

    def test_model_not_called_while_lock_held(self) -> None:
        """Holds a real lock file for a live, fresh holder and lets the real
        acquire path poll it, rather than mocking the acquire result."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(json.dumps({"pid": os.getpid(), "started_at": time.time()}), encoding="utf-8")
        fast = qwen.QwenThresholds(wait_ceiling_sec=0.05, lock_poll_interval_sec=0.01)

        with mock.patch("worker.qwen.THRESHOLDS", fast):
            ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, "deferred-qwen-busy"))
        self.assertEqual(len(self.generate_requests()), 0)
        self.assertTrue(self.lock_path.exists(), "a live holder's lock must be left in place")


class QwenLockReleaseTests(QwenHandlerCase):
    def _assert_lock_free(self, message: str) -> None:
        acquired = qwen._acquire_model_lock("job-2", wait_ceiling_sec=1)
        if acquired:
            qwen._release_model_lock("job-2")
        self.assertTrue(acquired, message)

    def test_lock_released_after_successful_job_allows_second_job_to_acquire(self) -> None:
        ok, _ = self.run_handler(id="job-1")

        self.assertTrue(ok)
        self.assertFalse(self.lock_path.exists())
        self._assert_lock_free("lock was not released after a successful job")

    def test_lock_released_when_model_call_raises(self) -> None:
        """The failure path is what strands a lock in production: a real
        transport failure and an unanticipated exception both release it."""
        for error, patch_seam in (
            (urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")), False),
            (RuntimeError("boom"), True),
        ):
            with self.subTest(error=type(error).__name__):
                self.generate_error = error
                seam = (
                    mock.patch("worker.qwen._ollama_request", side_effect=error)
                    if patch_seam
                    else contextlib.nullcontext()
                )
                with seam:
                    ok, _ = self.run_handler(id="job-1")
                self.assertFalse(ok)
                self.assertFalse(self.lock_path.exists())
                self._assert_lock_free("lock was stranded after the model call raised")


class QwenLockAcquireTests(QwenHandlerCase):
    def test_lock_is_never_visible_without_its_holder_payload(self) -> None:
        """The lock appears via os.link of a fully written temp file, so a
        concurrent reader can never see an empty lock and reclaim it."""
        seen: list[dict[str, object]] = []
        real_link = os.link

        def checking_link(src: str, dst: str) -> None:
            with open(src, encoding="utf-8") as fh:
                seen.append(json.loads(fh.read()))
            real_link(src, dst)

        with mock.patch("os.link", side_effect=checking_link):
            self.assertTrue(qwen._try_acquire_lock(self.lock_path))

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["pid"], os.getpid())
        self.assertEqual(json.loads(self.lock_path.read_text(encoding="utf-8"))["pid"], os.getpid())
        self.assertEqual(sorted(p.name for p in self.lock_path.parent.iterdir()), ["model.lock"])

    def test_second_acquire_fails_while_held_and_leaves_no_temp_files(self) -> None:
        self.assertTrue(qwen._try_acquire_lock(self.lock_path))
        before = self.lock_path.read_text(encoding="utf-8")

        self.assertFalse(qwen._try_acquire_lock(self.lock_path))

        self.assertEqual(self.lock_path.read_text(encoding="utf-8"), before)
        self.assertEqual(sorted(p.name for p in self.lock_path.parent.iterdir()), ["model.lock"])


class QwenStaleLockTests(QwenHandlerCase):
    """Three branches of the contract's stale-lock rule."""

    def _write_lock(self, pid: int, age_sec: float) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(json.dumps({"pid": pid, "started_at": time.time() - age_sec}), encoding="utf-8")

    def _acquire(self, job_id: str) -> bool:
        acquired = qwen._acquire_model_lock(job_id, wait_ceiling_sec=1)
        if acquired:
            qwen._release_model_lock(job_id)
        return acquired

    def test_dead_holder_pid_is_reclaimed(self) -> None:
        self._write_lock(pid=999999, age_sec=5)

        with mock.patch("worker.qwen._pid_alive", return_value=False):
            self.assertTrue(self._acquire("job-dead-holder"), "a lock held by a dead PID must be reclaimed")

    def test_alive_holder_within_stale_ceiling_is_not_reclaimed(self) -> None:
        self._write_lock(pid=1, age_sec=10)

        with mock.patch("worker.qwen._pid_alive", return_value=True):
            self.assertFalse(self._acquire("job-active-holder"), "an active, fresh lock must not be reclaimed")

    def test_alive_holder_older_than_ceiling_with_nonempty_lane_is_not_reclaimed(self) -> None:
        """SUSPECT: alive + past the ceiling, a worker process, non-empty lane."""
        self._write_lock(pid=1, age_sec=2000)

        with (
            mock.patch("worker.qwen._pid_alive", return_value=True),
            mock.patch("worker.qwen._pid_is_worker", return_value=True),
            mock.patch("worker.qwen._lane_depth", return_value=1),
        ):
            self.assertFalse(self._acquire("job-suspect-holder"))

    def test_alive_holder_older_than_ceiling_not_a_worker_process_is_reclaimed(self) -> None:
        self._write_lock(pid=1, age_sec=2000)

        with (
            mock.patch("worker.qwen._pid_alive", return_value=True),
            mock.patch("worker.qwen._pid_is_worker", return_value=False),
            mock.patch("worker.qwen._lane_depth", return_value=3),
        ):
            self.assertTrue(self._acquire("job-reclaim-non-worker"))

    def test_alive_holder_older_than_ceiling_empty_lane_is_reclaimed(self) -> None:
        self._write_lock(pid=1, age_sec=2000)

        with (
            mock.patch("worker.qwen._pid_alive", return_value=True),
            mock.patch("worker.qwen._pid_is_worker", return_value=True),
            mock.patch("worker.qwen._lane_depth", return_value=0),
        ):
            self.assertTrue(self._acquire("job-reclaim-empty-lane"))


if __name__ == "__main__":
    unittest.main()
