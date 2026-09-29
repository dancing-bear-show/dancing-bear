"""Regression tests for six PR #421 review threads on queue ownership.

- Drain file work outlives the deadline (4118781347, 4118945181): the
  shutdown-timeout marker is written before every drain requeue attempt, not
  only once the deadline has already passed, so a process killed while the
  requeue is stalled inside its filesystem work still leaves recovery intent.
- Publish failure after staging (4118781432): a staged ``*.json.requeue``
  file left by a failed publish is recovered by the next daemon tick instead
  of waiting for the next process start.
- Dead-thread cleanup after a terminal record (4118945097): ``finish`` moves
  the processing/ record itself into done/ or error/, so a thread that dies
  after finishing never leaves a claim-bearing processing/ record behind to be
  requeued and re-run; a record left mid-finish is completed, never requeued.
- Marker parsing (4118945153): only ``<id>.json.shutdown-timeout.<token>``
  names whose token is empty or a 32-character hex claim token are markers;
  a staged requeue of a job whose id embeds the marker text is not deleted.
- Deferred retries (4119055886): ``retry(count_attempt=False)`` leaves
  ``attempts`` untouched inside the transition, so no post-publish rewrite can
  reset a newer generation's counter.
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

_REAL_RETRY = q.retry
_REAL_PUBLISH = q._publish_no_clobber
_REAL_PATH_REPLACE = Path.replace


# Stands in for SIGKILL mid-call: SystemExit escapes every ``except Exception``
# handler, so nothing after the injection point runs.
_KILLED = SystemExit


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def _markers(root: Path) -> list[str]:
    return [n for n in _names(root / "processing") if ".shutdown-timeout" in n]


class _Base(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()
        self.join_new_threads_before_restore()
        self.stack = _patch_queue_root(self.root)
        self.addCleanup(self.stack.close)

    def _claimed(self, job_id: str, **job_kwargs: Any) -> tuple[Path, str]:
        pending = enqueue(Job(id=job_id, type="noop", payload={}, **job_kwargs), root=self.root)
        claim = q.start_processing(pending, self.root)
        if claim is None or not claim[1]:
            self.fail(f"could not claim {job_id}")
        return claim

    def _register_dead_thread(self, runner: Any, stem: str, token: str) -> None:
        # A never-started Thread reports is_alive() False: the prune treats it
        # exactly like a thread that has already exited.
        runner._live_threads[stem] = (threading.Thread(target=lambda: None), token)


# ---------------------------------------------------------------------------
# 4118781347 / 4118945181 -- marker before every drain requeue attempt
# ---------------------------------------------------------------------------


class TestDrainMarkerPrecedesEveryAttempt(_Base):
    def _startup_recovery(self) -> None:
        q.recover_staged_requeues(root=self.root)
        q.recover_shutdown_timeout_markers(root=self.root)

    def test_kill_during_file_work_under_the_lock_leaves_a_marker(self) -> None:
        """4118781347: lock_timeout bounds acquisition only; a stall in the file
        work after acquisition (here, the stage rename) must not strand the job
        when the process is killed mid-call, even well before the deadline."""
        proc, token = self._claimed("stall1")
        runner = _make_runner(self.root)
        with patch.object(q, "_stage", side_effect=_KILLED), self.assertRaises(_KILLED):
            runner._drain_one_stem("stall1", token, time.monotonic() + 60)

        self.assertTrue(proc.exists(), "the stalled call never moved the record")
        self.assertEqual(_markers(self.root), [f"stall1.json.shutdown-timeout.{token}"])
        self._startup_recovery()
        self.assertEqual(_names(self.root / "pending"), ["stall1.json"])
        self.assertEqual(_names(self.root / "processing"), [])

    def test_requeue_started_before_the_deadline_that_overruns_it_leaves_a_marker(self) -> None:
        """4118945181: remaining > 0 when the call starts; the call is killed
        after the deadline has passed. A marker must already be on disk."""
        proc, token = self._claimed("overrun1")
        runner = _make_runner(self.root)
        deadline = time.monotonic() + 0.5
        with patch.object(q, "requeue_processing", side_effect=_KILLED), self.assertRaises(_KILLED):
            runner._drain_one_stem("overrun1", token, deadline)

        self.assertTrue(proc.exists())
        self.assertEqual(_markers(self.root), [f"overrun1.json.shutdown-timeout.{token}"])

    def test_normal_return_before_the_deadline_removes_the_marker(self) -> None:
        _proc, token = self._claimed("ok1")
        runner = _make_runner(self.root)
        self.assertTrue(runner._drain_one_stem("ok1", token, time.monotonic() + 60))
        self.assertEqual(_markers(self.root), [])
        self.assertEqual(_names(self.root / "pending"), ["ok1.json"])

    def test_normal_none_return_removes_the_marker(self) -> None:
        """A finished job (record already gone) is not requeued and leaves no marker."""
        runner = _make_runner(self.root)
        q._ensure_dirs(self.root)
        self.assertFalse(runner._drain_one_stem("gone1", "a" * 32, time.monotonic() + 60))
        self.assertEqual(_markers(self.root), [])
        self.assertEqual(_names(self.root / "pending"), [])


# ---------------------------------------------------------------------------
# 4118781432 -- staged file left by a failed publish is recovered in-process
# ---------------------------------------------------------------------------


class TestTickRecoversStagedFileFromFailedPublish(_Base):
    def test_publish_failure_does_not_strand_the_staged_record(self) -> None:
        _proc, token = self._claimed("pub1")
        # max_per_tick=0: the tick never claims the recovered job itself, so
        # the assertion sees exactly what the recovery published.
        runner = _make_runner(self.root, max_per_tick=0)
        self._register_dead_thread(runner, "pub1", token)
        calls = {"n": 0}

        def _flaky_publish(staged: Path, dest: Path) -> bool:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("transient publish failure")
            return _REAL_PUBLISH(staged, dest)

        with patch.object(q, "_publish_no_clobber", side_effect=_flaky_publish):
            runner.tick()
            runner.tick()

        self.assertEqual(_names(self.root / "processing"), [], "staged record left behind")
        self.assertEqual(_names(self.root / "pending"), ["pub1.json"])
        self.assertNotIn(q.CLAIM_TOKEN_FIELD, _read(self.root / "pending" / "pub1.json"))

    def test_retry_failure_after_staging_is_recovered_by_the_next_tick(self) -> None:
        """Same shape in retry(): the staged rewrite fails after the rename."""
        proc, token = self._claimed("pub2")
        runner = _make_runner(self.root, max_per_tick=0)
        with (
            patch.object(q, "atomic_write_json", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            q.retry(proc, claim_token=token, reason="x")
        self.assertEqual(_names(self.root / "processing"), ["pub2.json.requeue"])
        runner.tick()
        self.assertEqual(_names(self.root / "processing"), [])
        self.assertEqual(_names(self.root / "pending"), ["pub2.json"])


# ---------------------------------------------------------------------------
# 4118945097 -- a finished job is never requeued by dead-thread cleanup
# ---------------------------------------------------------------------------


class TestFinishedJobIsNotRequeued(_Base):
    def test_processing_unlink_failure_after_done_does_not_rerun(self) -> None:
        """The reviewer's scenario: done/ published, processing/ unlink fails."""
        proc, token = self._claimed("fin1")
        runner = _make_runner(self.root, max_per_tick=0)
        with patch.object(q, "_remove_job_file"):
            q.finish(proc, True, claim_token=token)
        self._register_dead_thread(runner, "fin1", token)
        runner._prune_live_threads()

        self.assertEqual(_names(self.root / "pending"), [], "finished job was requeued")
        self.assertEqual(_names(self.root / "done"), ["fin1.json"])

    def _fail_move_into(self, folder: str):
        def _replace(src: Path, dst: Any) -> Path:
            if Path(dst).parent.name == folder:
                raise OSError("simulated move failure")
            return _REAL_PATH_REPLACE(src, dst)

        return patch.object(Path, "replace", _replace)

    def test_move_failure_leaves_a_record_no_owner_can_requeue(self) -> None:
        proc, token = self._claimed("fin2")
        runner = _make_runner(self.root, max_per_tick=0)
        with self._fail_move_into("error"), self.assertRaises(OSError):
            q.finish(proc, False, claim_token=token, error_msg="boom")
        left = _read(proc)
        self.assertEqual(left["status"], "error")
        self.assertNotIn(q.CLAIM_TOKEN_FIELD, left)

        self._register_dead_thread(runner, "fin2", token)
        runner._prune_live_threads()

        self.assertEqual(_names(self.root / "pending"), [])
        self.assertEqual(_names(self.root / "processing"), [])
        self.assertEqual(_read(self.root / "error" / "fin2.json")["error"], "boom")

    def test_reaper_completes_an_interrupted_finish_instead_of_requeueing(self) -> None:
        proc, token = self._claimed("fin3")
        with self._fail_move_into("done"), self.assertRaises(OSError):
            q.finish(proc, True, claim_token=token, result={"r": 1})
        data = _read(proc)
        data["processing_started_at"] = "2000-01-01T00:00:00Z"
        proc.write_text(json.dumps(data), encoding="utf-8")

        self.assertEqual(q.reap_stale_processing_jobs(1, root=self.root), [])
        self.assertEqual(_names(self.root / "pending"), [])
        self.assertEqual(_read(self.root / "done" / "fin3.json")["result"], {"r": 1})


# ---------------------------------------------------------------------------
# 4118945153 -- marker names are validated, not substring-matched
# ---------------------------------------------------------------------------


class TestMarkerParserValidatesToken(_Base):
    def test_staged_requeue_of_marker_like_job_id_is_not_deleted(self) -> None:
        job_id = "foo.json.shutdown-timeout"
        paths = q._ensure_dirs(self.root)
        staged = paths["processing"] / f"{job_id}.json.requeue"
        staged.write_text(json.dumps({"id": job_id, "status": "pending"}), encoding="utf-8")
        # A pending/ copy already exists, so staged recovery keeps the file.
        (paths["pending"] / f"{job_id}.json").write_text(json.dumps({"id": job_id}), encoding="utf-8")
        q.recover_staged_requeues(root=self.root)
        self.assertTrue(staged.exists())

        self.assertEqual(q.recover_shutdown_timeout_markers(root=self.root), [])
        self.assertTrue(staged.exists(), "a staged requeue was deleted as a stale marker")

    def test_marker_with_non_token_suffix_is_ignored(self) -> None:
        proc, _token = self._claimed("foo")
        bogus = proc.parent / "foo.json.shutdown-timeout.not-a-token"
        bogus.touch()
        self.assertEqual(q.recover_shutdown_timeout_markers(root=self.root), [])
        self.assertTrue(proc.exists(), "a non-marker file triggered a requeue")
        self.assertTrue(bogus.exists())

    def test_valid_token_and_empty_token_markers_still_parse(self) -> None:
        _proc, token = self._claimed("good1")
        q.write_shutdown_timeout_marker("good1", token, root=self.root)
        q.write_shutdown_timeout_marker("gone2", None, root=self.root)
        self.assertEqual(q.recover_shutdown_timeout_markers(root=self.root), ["good1"])
        self.assertEqual(_markers(self.root), [])


# ---------------------------------------------------------------------------
# 4119055886 -- deferral does not consume an attempt, atomically
# ---------------------------------------------------------------------------


class TestDeferredRetryIsAtomic(_Base):
    def test_rival_generation_attempts_are_not_reset(self) -> None:
        from worker.job_runtime import JobContext, OutcomeContext, WorkerConfig, _handle_outcome

        proc, token = self._claimed("def1")
        pending = self.root / "pending" / "def1.json"

        def _retry_then_rival_runs(job_path: Path, **kw: Any) -> Path | None:
            out = _REAL_RETRY(job_path, **kw)
            # Another worker claims the published copy and fails it, producing
            # a newer pending/ generation before the deferring worker resumes.
            rival = q.start_processing(pending, self.root)
            if rival is None:
                self.fail("rival could not claim")
            _REAL_RETRY(rival[0], root=self.root, claim_token=rival[1], delay_sec=0, reason="rival")
            return out

        ctx = JobContext.from_item(proc, _read(proc), claim_token=token)
        octx = OutcomeContext(proc, ctx, 0, "daemon", WorkerConfig(backoff=0))
        with patch.object(q, "retry", side_effect=_retry_then_rival_runs):
            _handle_outcome(octx, False, "deferred-busy")

        data = _read(pending)
        self.assertEqual(data["last_error"], "rival")
        self.assertEqual(data["attempts"], 1, "the rival's attempt was reset")

    def test_deferral_keeps_attempts(self) -> None:
        proc, token = self._claimed("def2", attempts=2)
        out = q.retry(proc, claim_token=token, delay_sec=0, count_attempt=False)
        self.assertIsNotNone(out)
        self.assertEqual(_read(self.root / "pending" / "def2.json")["attempts"], 2)


if __name__ == "__main__":
    unittest.main()
