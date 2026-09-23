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
      _pid_is_worker(pid) is False OR the lane is empty; never when
      _pid_is_worker(pid) is None (ps could not answer)

Every removal - reclaim and release alike - is compare-and-delete: the lock
is renamed aside and removed only if it still records the expected holder.

QwenHandlerCase points _lock_path at the test temp dir, so no test here
touches the real worker state dir.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
import json
import os
import time
import unittest
import urllib.error
from pathlib import Path
import unittest.mock as mock

from worker import qwen
from tests.worker_tests.qwen_fixtures import QwenHandlerCase, require


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
            qwen._release_model_lock("job-2", acquired)
        self.assertIsNotNone(acquired, message)

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
            qwen._release_model_lock(job_id, acquired)
        return acquired is not None

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

    def test_suspect_holder_is_kept_when_ps_cannot_say_whether_it_is_a_worker(self) -> None:
        """Unknown is not "not a worker": the lock stays, lane full or empty."""
        for lane in (3, 0):
            with self.subTest(lane=lane):
                self._write_lock(pid=1, age_sec=2000)
                with (
                    mock.patch("worker.qwen.THRESHOLDS", qwen.QwenThresholds(lock_poll_interval_sec=0.01)),
                    mock.patch("worker.qwen._pid_alive", return_value=True),
                    mock.patch("worker.qwen._pid_is_worker", return_value=None),
                    mock.patch("worker.qwen._lane_depth", return_value=lane),
                ):
                    self.assertFalse(self._acquire("job-unknown-holder"))
                self.assertEqual(json.loads(self.lock_path.read_text(encoding="utf-8"))["pid"], 1)


class QwenLockCompareAndDeleteTests(QwenHandlerCase):
    """Reclaim and release remove a lock only if it is still the one inspected."""

    def _write_lock(self, holder: Mapping[str, object]) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(json.dumps(holder), encoding="utf-8")

    def _lock_dir_names(self) -> list[str]:
        return sorted(p.name for p in self.lock_path.parent.iterdir())

    def test_lock_reacquired_between_inspect_and_reclaim_survives(self) -> None:
        """Worker A reads a stale lock; before A reclaims it, worker B reclaims
        it and acquires its own. A must not delete B's lock or acquire."""
        self._write_lock({"pid": 999999, "started_at": time.time() - 5})
        new_holder = {"pid": os.getpid(), "started_at": time.time()}
        real_read = qwen._read_lock_holder
        swapped: list[bool] = []

        def read_then_swap(path: Path) -> qwen._LockHolder | None:
            holder = real_read(path)
            if not swapped:
                swapped.append(True)
                self.lock_path.unlink()
                self._write_lock(new_holder)
            return holder

        with (
            mock.patch("worker.qwen._read_lock_holder", side_effect=read_then_swap),
            mock.patch("worker.qwen._pid_alive", return_value=False),
        ):
            acquired = qwen._handle_existing_lock(self.lock_path)

        self.assertTrue(swapped, "the interleaving never happened")
        self.assertIsNone(acquired, "this worker acquired a lock another worker holds")
        self.assertEqual(json.loads(self.lock_path.read_text(encoding="utf-8")), new_holder)
        self.assertEqual(self._lock_dir_names(), ["model.lock"], "a reclaim tombstone was left behind")

    def test_unchanged_stale_lock_is_still_reclaimed(self) -> None:
        self._write_lock({"pid": 999999, "started_at": time.time() - 5})

        with mock.patch("worker.qwen._pid_alive", return_value=False):
            acquired = qwen._handle_existing_lock(self.lock_path)

        self.assertIsNotNone(acquired)
        self.assertEqual(json.loads(self.lock_path.read_text(encoding="utf-8"))["pid"], os.getpid())
        qwen._release_model_lock("job", require(acquired))
        self.assertFalse(self.lock_path.exists())
        self.assertEqual(self._lock_dir_names(), [])

    def test_release_leaves_a_lock_that_is_no_longer_ours(self) -> None:
        """Our lock was reclaimed and another job acquired: release must not delete theirs."""
        mine = require(qwen._try_acquire_lock(self.lock_path))
        other = {"pid": os.getpid() + 1, "started_at": time.time() + 1}
        self.lock_path.unlink()
        self._write_lock(other)

        qwen._release_lock(self.lock_path, mine)

        self.assertEqual(json.loads(self.lock_path.read_text(encoding="utf-8")), other)
        self.assertEqual(self._lock_dir_names(), ["model.lock"])

    def test_release_after_a_same_process_reclaim_leaves_the_new_acquisitions_lock(self) -> None:
        """Two handler threads share one pid. Thread 1's lock is reclaimed and
        thread 2 acquires before thread 1's finally runs: thread 1's release
        must not remove thread 2's lock."""
        first = require(qwen._try_acquire_lock(self.lock_path))
        with mock.patch("worker.qwen._lock_verdict", return_value="STALE"):
            second = require(qwen._handle_existing_lock(self.lock_path))
        self.assertEqual(first.pid, second.pid)

        qwen._release_lock(self.lock_path, first)

        self.assertEqual(qwen._read_lock_holder(self.lock_path), second, "the new acquisition's lock was removed")
        qwen._release_lock(self.lock_path, second)
        self.assertEqual(self._lock_dir_names(), [])

    def test_token_distinguishes_acquisitions_with_the_same_pid_and_start_time(self) -> None:
        """pid + started_at cannot tell two same-process acquisitions apart on
        a coarse clock; only the per-acquisition token can."""
        with mock.patch("worker.qwen.time") as clock:
            clock.time.return_value = 1_000.0
            first = require(qwen._try_acquire_lock(self.lock_path))
            self.assertTrue(qwen._remove_lock_if_held_by(self.lock_path, first))
            second = require(qwen._try_acquire_lock(self.lock_path))
        self.assertEqual((first.pid, first.started_at), (second.pid, second.started_at))

        qwen._release_lock(self.lock_path, first)

        self.assertEqual(qwen._read_lock_holder(self.lock_path), second)

    def test_lock_file_keeps_the_fields_qwen_admin_reads_and_adds_the_token(self) -> None:
        holder = require(qwen._try_acquire_lock(self.lock_path))

        raw = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.assertEqual(raw, {"pid": os.getpid(), "started_at": holder.started_at, "token": holder.token})

    def test_lock_without_a_token_is_read_and_reclaimed(self) -> None:
        """A lock written before the token existed still parses and still reclaims."""
        legacy = {"pid": 999999, "started_at": time.time() - 5}
        self._write_lock(legacy)
        self.assertEqual(qwen._read_lock_holder(self.lock_path), qwen._LockHolder(999999, legacy["started_at"]))

        with mock.patch("worker.qwen._pid_alive", return_value=False):
            self.assertIsNotNone(qwen._handle_existing_lock(self.lock_path))

    def test_restore_never_overwrites_a_lock_acquired_meanwhile(self) -> None:
        tombstone = self.lock_path.with_name(".model.lock.reclaim.test")
        self._write_lock({"pid": 2, "started_at": 2.0})
        tombstone.write_text(json.dumps({"pid": 1, "started_at": 1.0}), encoding="utf-8")

        qwen._restore_lock(tombstone, self.lock_path)

        self.assertEqual(json.loads(self.lock_path.read_text(encoding="utf-8"))["pid"], 2)
        self.assertFalse(tombstone.exists())


if __name__ == "__main__":
    unittest.main()
