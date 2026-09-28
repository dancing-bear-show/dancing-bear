"""Class-level regression tests for PR #421's worker shutdown/recovery code.

Class 1 -- one error aborts a best-effort loop: every loop over markers,
staged files, registered stems, processing/ or pending/ records isolates a
failure to its own entry (logged with the stem) and keeps going; a claim this
worker gives up without running is never left untracked when its requeue
raises.

Class 2 -- drain probes every registered claim whatever its thread's state,
and no lock wait in the drain outlasts the shutdown deadline; a claim not
requeued in time keeps a marker startup recovery consumes.
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
from tests.worker_tests.test_daemon_nonblocking import _make_runner, _patch_queue_root
from worker import queue_ops as q
from worker.queue_ops import Job, enqueue

_TOK_A = "a" * 32
_TOK_B = "b" * 32
_REAL_UNLINK = Path.unlink
_REAL_REQUEUE = q.requeue_processing
_REAL_LIST_PENDING = q.list_pending


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _unlink_failing_for(name: str):
    """Patch Path.unlink so only the file called ``name`` cannot be deleted."""

    def _unlink(self_path: Path, missing_ok: bool = False) -> None:
        if self_path.name == name:
            raise PermissionError(f"simulated: cannot unlink {name}")
        _REAL_UNLINK(self_path, missing_ok=missing_ok)

    return patch.object(Path, "unlink", _unlink)


class _Base(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()
        self.stack = _patch_queue_root(self.root)
        self.addCleanup(self.stack.close)
        self.paths = q._ensure_dirs(self.root)

    def _plant_processing(self, job_id: str, token: str | None, **extra: Any) -> Path:
        record: dict[str, Any] = {"id": job_id, "type": "noop", "payload": {}, "status": "processing"}
        if token is not None:
            record[q.CLAIM_TOKEN_FIELD] = token
        record.update(extra)
        path = self.paths["processing"] / f"{job_id}.json"
        _write(path, record)
        return path

    def _marker(self, job_id: str, token: str | None) -> Path:
        return self.paths["processing"] / f"{job_id}.json.shutdown-timeout.{token or ''}"


# ---------------------------------------------------------------------------
# Class 1 -- queue_ops loops
# ---------------------------------------------------------------------------


class TestMarkerRecoveryIsolatesUnlinkFailures(_Base):
    def test_stale_marker_unlink_failure_does_not_stop_the_scan(self) -> None:
        """PRRT_kwDOQr1kjM6msDoS: the stale-marker branch."""
        stuck = self._marker("gone1", _TOK_A)
        stuck.touch()
        self._plant_processing("live1", _TOK_B)
        self._marker("live1", _TOK_B).touch()

        with _unlink_failing_for(stuck.name), self.assertLogs("worker.queue_ops", "WARNING") as logs:
            recovered = q.recover_shutdown_timeout_markers(root=self.root)

        self.assertEqual(recovered, ["live1"])
        self.assertEqual(_names(self.paths["pending"]), ["live1.json"])
        self.assertTrue(stuck.exists(), "the undeletable marker stays for the next start")
        self.assertTrue(any("gone1" in line for line in logs.output))

    def test_post_requeue_unlink_failure_does_not_stop_the_scan(self) -> None:
        """PRRT_kwDOQr1kjM6msDov: the unlink after a requeue attempt."""
        self._plant_processing("first", _TOK_A)
        first_marker = self._marker("first", _TOK_A)
        first_marker.touch()
        self._plant_processing("second", _TOK_B)
        self._marker("second", _TOK_B).touch()

        with _unlink_failing_for(first_marker.name), self.assertLogs("worker.queue_ops", "WARNING") as logs:
            recovered = q.recover_shutdown_timeout_markers(root=self.root)

        self.assertEqual(sorted(recovered), ["first", "second"])
        self.assertEqual(_names(self.paths["pending"]), ["first.json", "second.json"])
        self.assertTrue(any("first" in line for line in logs.output))
        # The leftover marker is harmless: the record is gone, so the next
        # pass discards it without requeueing anything.
        self.assertEqual(q.recover_shutdown_timeout_markers(root=self.root), [])
        self.assertFalse(first_marker.exists())


class TestStagedRecoveryLogsAndContinues(_Base):
    def test_one_failing_staged_file_is_logged_and_the_rest_publish(self) -> None:
        for job_id in ("s1", "s2"):
            _write(self.paths["processing"] / f"{job_id}.json.requeue", {"id": job_id, "status": "pending"})
        real_publish = q._publish_no_clobber

        def _publish(staged: Path, dest: Path) -> bool:
            if dest.stem == "s1":
                raise OSError("simulated publish failure")
            return real_publish(staged, dest)

        with (
            patch.object(q, "_publish_no_clobber", side_effect=_publish),
            self.assertLogs("worker.queue_ops", "WARNING") as logs,
        ):
            recovered = q.recover_staged_requeues(root=self.root)

        self.assertEqual(recovered, ["s2"])
        self.assertIn("s1.json.requeue", _names(self.paths["processing"]))
        self.assertTrue(any("s1" in line for line in logs.output))


class TestReapLoopsSkipMalformedRecords(_Base):
    _OLD = "2000-01-01T00:00:00Z"

    def _plant_malformed_and_stale(self) -> None:
        _write(self.paths["processing"] / "bad.json", ["not", "an", "object"])
        self._plant_processing("stale1", _TOK_A, processing_started_at=self._OLD)

    def test_queue_reaper(self) -> None:
        self._plant_malformed_and_stale()
        with self.assertLogs("worker.queue_ops", "WARNING") as logs:
            reaped = q.reap_stale_processing_jobs(1, root=self.root)
        self.assertEqual(reaped, ["stale1"])
        self.assertTrue(any("bad.json" in line for line in logs.output))
        self.assertIn("bad.json", _names(self.paths["processing"]))

    def test_daemon_reaper(self) -> None:
        from worker.job_runtime import _reap_stale_unowned

        self._plant_malformed_and_stale()
        with self.assertLogs("worker.queue_ops", "WARNING"):
            reaped = _reap_stale_unowned(1, self.root, owned=set())
        self.assertEqual(reaped, ["stale1"])


class TestListPendingSkipsMalformedRecords(_Base):
    def test_non_object_record_and_bad_priority_do_not_hide_other_jobs(self) -> None:
        enqueue(Job(id="ok1", type="noop", payload={}), root=self.root)
        enqueue(Job(id="ok2", type="noop", payload={}), root=self.root)
        _write(self.paths["pending"] / "arr.json", [1, 2])
        bad_pri = self.paths["pending"] / "ok2.json"
        data = json.loads(bad_pri.read_text(encoding="utf-8"))
        data["priority"] = "high"
        _write(bad_pri, data)

        with self.assertLogs("worker.queue_ops", "WARNING") as logs:
            listed = _REAL_LIST_PENDING(root=self.root)

        self.assertEqual(sorted(p.stem for p, _ in listed), ["ok1", "ok2"])
        self.assertTrue(any("arr.json" in line for line in logs.output))


# ---------------------------------------------------------------------------
# Class 1 -- job_runtime loops and startup
# ---------------------------------------------------------------------------


class TestStartupRecoveryIsIsolated(_Base):
    def test_run_once_still_recovers_markers_when_staged_recovery_raises(self) -> None:
        self._plant_processing("m1", _TOK_A)
        self._marker("m1", _TOK_A).touch()
        runner = _make_runner(self.root, max_per_tick=0)
        with (
            patch.object(q, "recover_staged_requeues", side_effect=OSError("lock dir unreadable")),
            self.assertLogs("worker.job_runtime", "ERROR") as logs,
        ):
            self.assertEqual(runner.run_once(), 0)
        self.assertEqual(_names(self.paths["pending"]), ["m1.json"])
        self.assertTrue(any("staged requeues" in line for line in logs.output))

    def test_run_daemon_starts_and_drains_when_marker_recovery_raises(self) -> None:
        from worker import job_runtime as jr

        runner = _make_runner(self.root, interval=0.01, shutdown_grace=0.0)
        runner.stop_event.set()
        drained = threading.Event()

        def _drain(_self: Any, _grace: float) -> list[str]:
            drained.set()
            return []

        with (
            patch.object(q, "recover_shutdown_timeout_markers", side_effect=OSError("boom")),
            patch.object(jr.DaemonRunner, "drain_live_threads", _drain),
            patch("worker.job_runtime.os.chdir"),
            self.assertLogs("worker.job_runtime", "ERROR"),
        ):
            self.assertEqual(runner.run_daemon(), 0)
        self.assertTrue(drained.is_set())


class TestDaemonLoopSurvivesTickFailure(_Base):
    def test_tick_error_is_logged_and_the_loop_still_drains(self) -> None:
        from worker import job_runtime as jr

        runner = _make_runner(self.root, interval=0.01, shutdown_grace=0.0)
        ticks = {"n": 0}

        def _tick() -> int:
            ticks["n"] += 1
            if ticks["n"] == 1:
                raise OSError("pending/ unreadable")
            runner.stop_event.set()
            return 0

        drained = threading.Event()

        def _drain(_self: Any, _grace: float) -> list[str]:
            drained.set()
            return []

        with (
            patch.object(runner, "tick", side_effect=_tick),
            patch.object(jr.DaemonRunner, "drain_live_threads", _drain),
            patch("worker.job_runtime.os.chdir"),
            self.assertLogs("worker.job_runtime", "ERROR"),
        ):
            self.assertEqual(runner.run_daemon(), 0)
        self.assertEqual(ticks["n"], 2, "the loop did not survive the failed tick")
        self.assertTrue(drained.is_set())


class TestUnrunClaimPolicy(_Base):
    """A requeue failure for a claim nobody will run leaves a recovery marker."""

    def _tokenless_claim(self, job_id: str) -> Path:
        pending = enqueue(Job(id=job_id, type="noop", payload={}), root=self.root)
        pending.unlink()
        return self._plant_processing(job_id, None)

    def _assert_marker_recovers(self, job_id: str, token: str | None) -> None:
        self.assertTrue(self._marker(job_id, token).exists(), "no recovery marker was written")
        self.assertEqual(q.recover_shutdown_timeout_markers(root=self.root), [job_id])
        self.assertEqual(_names(self.paths["pending"]), [f"{job_id}.json"])

    def test_process_one_tokenless_requeue_failure(self) -> None:
        proc = self._tokenless_claim("t1")
        runner = _make_runner(self.root)
        with (
            patch.object(q, "start_processing", return_value=(proc, "")),
            patch.object(q, "requeue_processing", side_effect=OSError("disk full")),
            self.assertLogs("worker.job_runtime", "ERROR") as logs,
        ):
            self.assertEqual(runner.processor.process_one(proc, {"id": "t1"}), 0)
        self.assertTrue(any("t1" in line for line in logs.output))
        self._assert_marker_recovers("t1", None)

    def test_start_batch_tokenless_requeue_failure_is_retried_by_prune(self) -> None:
        proc = self._tokenless_claim("t2")
        runner = _make_runner(self.root, max_per_tick=1)
        with (
            patch.object(q, "start_processing", return_value=(proc, "")),
            patch.object(q, "requeue_processing", side_effect=OSError("disk full")),
            self.assertLogs("worker.job_runtime", "ERROR"),
        ):
            runner._start_batch([(proc, {"id": "t2"})])
        self.assertIn("t2", runner._live_threads, "the failed claim is not tracked")
        self.assertTrue(self._marker("t2", None).exists())

        runner._prune_live_threads()
        self.assertNotIn("t2", runner._live_threads)
        self.assertEqual(_names(self.paths["pending"]), ["t2.json"])

    def test_abandon_claim_requeue_failure_writes_a_marker(self) -> None:
        self._plant_processing("t3", _TOK_A)
        runner = _make_runner(self.root)
        runner._register_unrun("t3", _TOK_A)
        with (
            patch.object(q, "requeue_processing", side_effect=OSError("disk full")),
            self.assertLogs("worker.job_runtime", "ERROR"),
        ):
            runner._abandon_claim("t3", _TOK_A)
        self.assertIn("t3", runner._live_threads)
        self._assert_marker_recovers("t3", _TOK_A)


class TestDrainIsolatesPerStemFailures(_Base):
    """job_runtime.py:806 -- one failing stem does not stop the drain."""

    def test_first_stem_raises_second_is_still_requeued(self) -> None:
        runner = _make_runner(self.root)
        for job_id, token in (("d1", _TOK_A), ("d2", _TOK_B)):
            self._plant_processing(job_id, token)
            runner._register_unrun(job_id, token)

        def _requeue(job_id: str, **kw: Any) -> Path | None:
            if job_id == "d1":
                raise OSError("simulated publish failure")
            return _REAL_REQUEUE(job_id, **kw)

        with (
            patch.object(q, "requeue_processing", side_effect=_requeue),
            self.assertLogs("worker.job_runtime", "ERROR") as logs,
        ):
            requeued = runner.drain_live_threads(grace=0.0)

        self.assertEqual(requeued, ["d2"])
        self.assertTrue(any("d1" in line for line in logs.output))
        self.assertTrue(self._marker("d1", _TOK_A).exists())


# ---------------------------------------------------------------------------
# Class 2 -- drain probes every registered claim, bounded by the deadline
# ---------------------------------------------------------------------------


class TestDrainProbesEveryClaimWithinTheDeadline(_Base):
    _GRACE = 0.2
    _EPSILON = 0.5

    def _dead_thread_claim(self, runner: Any, job_id: str) -> Path:
        pending = enqueue(Job(id=job_id, type="noop", payload={}), root=self.root)
        claim = q.start_processing(pending, self.root)
        if claim is None or not claim[1]:
            self.fail(f"could not claim {job_id}")
        dead = threading.Thread(target=lambda: None, daemon=True)
        dead.start()
        dead.join()
        runner._live_threads[job_id] = (dead, claim[1])
        return claim[0]

    def test_dead_thread_with_record_left_behind_is_requeued(self) -> None:
        """job_runtime.py:731/734: thread state never decides whether to probe."""
        runner = _make_runner(self.root)
        proc = self._dead_thread_claim(runner, "died1")
        self.assertEqual(runner.drain_live_threads(grace=self._GRACE), ["died1"])
        self.assertFalse(proc.exists())
        self.assertEqual(_names(self.paths["pending"]), ["died1.json"])

    def test_lock_held_past_the_deadline_bounds_the_drain(self) -> None:
        """job_runtime.py:825: a held transition lock cannot stretch the drain."""
        runner = _make_runner(self.root)
        proc = self._dead_thread_claim(runner, "held1")
        with q._transition_lock(self.root), self.assertLogs("worker.job_runtime", "ERROR"):
            started = time.monotonic()
            requeued = runner.drain_live_threads(grace=self._GRACE)
            elapsed = time.monotonic() - started
        self.assertEqual(requeued, [])
        self.assertLess(elapsed, self._GRACE + self._EPSILON)
        self.assertTrue(proc.exists(), "the record must stay for recovery")
        self.assertEqual(q.recover_shutdown_timeout_markers(root=self.root), ["held1"])
        self.assertEqual(_names(self.paths["pending"]), ["held1.json"])

    def test_stalled_marker_write_does_not_extend_the_lock_wait(self) -> None:
        """The lock budget is measured after the marker write, not before it."""
        from worker import job_runtime as jr

        runner = _make_runner(self.root)
        self._dead_thread_claim(runner, "slowfs1")
        real_write = jr._write_shutdown_timeout_marker
        budgets: list[float | None] = []

        def _slow_write(job_id: str, token: str | None, root: Path, **kw: Any) -> None:
            time.sleep(self._GRACE)
            real_write(job_id, token, root, **kw)

        def _capture(job_id: str, **kw: Any) -> Path | None:
            budgets.append(kw.get("lock_timeout"))
            return _REAL_REQUEUE(job_id, **kw)

        with (
            patch.object(jr, "_write_shutdown_timeout_marker", side_effect=_slow_write),
            patch.object(q, "requeue_processing", side_effect=_capture),
        ):
            runner._drain_one_stem("slowfs1", runner._live_threads["slowfs1"][1], time.monotonic() + self._GRACE / 2)
        self.assertEqual(budgets, [0.0])


if __name__ == "__main__":
    unittest.main()
