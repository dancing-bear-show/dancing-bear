"""Tests for worker/queue.py — covering gaps to reach 80%+ line coverage."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.worker_tests.helpers import QueueRootIsolationMixin, _make_root


# ---------------------------------------------------------------------------
# Job dataclass
# ---------------------------------------------------------------------------

class TestJobDataclass(unittest.TestCase):
    """Job.to_dict must populate timestamps and return correct structure."""

    def test_to_dict_returns_expected_keys(self):
        from worker.queue import Job
        job = Job(id="abc", type="run_cli", payload={"cmd": ["echo"]})
        d = job.to_dict()
        self.assertEqual(d["id"], "abc")
        self.assertEqual(d["type"], "run_cli")
        self.assertIn("enqueued_at", d)
        self.assertIn("updated_at", d)

    def test_to_dict_fills_enqueued_at_when_empty(self):
        from worker.queue import Job
        job = Job(id="x", type="noop", payload={}, enqueued_at="")
        d = job.to_dict()
        self.assertTrue(d["enqueued_at"])

    def test_to_dict_preserves_existing_enqueued_at(self):
        from worker.queue import Job
        ts = "2025-01-01T00:00:00Z"
        job = Job(id="x", type="noop", payload={}, enqueued_at=ts)
        d = job.to_dict()
        self.assertEqual(d["enqueued_at"], ts)

    def test_to_dict_sets_updated_at(self):
        from worker.queue import Job
        job = Job(id="x", type="noop", payload={})
        d = job.to_dict()
        self.assertRegex(d["updated_at"], r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

    def test_to_dict_includes_priority(self):
        from worker.queue import Job
        job = Job(id="x", type="noop", payload={}, priority=1)
        d = job.to_dict()
        self.assertEqual(d["priority"], 1)


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------

class TestEnqueue(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_enqueue_creates_pending_file(self):
        from worker.queue import Job, enqueue
        job = Job(id="j1", type="noop", payload={})
        path = enqueue(job, root=self.root)
        self.assertTrue(path.exists())
        self.assertEqual(path.parent.name, "pending")

    def test_enqueue_sets_not_before_when_empty(self):
        from worker.queue import Job, enqueue
        job = Job(id="j2", type="noop", payload={}, not_before="")
        enqueue(job, root=self.root)
        p = self.root / "pending" / "j2.json"
        data = json.loads(p.read_text())
        self.assertTrue(data["not_before"])

    def test_enqueue_preserves_not_before_when_set(self):
        from worker.queue import Job, enqueue
        ts = "2099-01-01T00:00:00Z"
        job = Job(id="j3", type="noop", payload={}, not_before=ts)
        enqueue(job, root=self.root)
        p = self.root / "pending" / "j3.json"
        data = json.loads(p.read_text())
        self.assertEqual(data["not_before"], ts)

    def test_enqueue_writes_valid_json(self):
        from worker.queue import Job, enqueue
        job = Job(id="j4", type="noop", payload={"key": "val"})
        path = enqueue(job, root=self.root)
        data = json.loads(path.read_text())
        self.assertEqual(data["type"], "noop")
        self.assertEqual(data["payload"]["key"], "val")

    def test_enqueue_returns_path_object(self):
        from worker.queue import Job, enqueue
        job = Job(id="j5", type="noop", payload={})
        result = enqueue(job, root=self.root)
        self.assertIsInstance(result, Path)


# ---------------------------------------------------------------------------
# _ensure_dirs
# ---------------------------------------------------------------------------

class TestEnsureDirs(unittest.TestCase):
    def test_creates_all_subdirs(self):
        from worker.queue import _ensure_dirs
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "q"
            paths = _ensure_dirs(root)
            for name in ("pending", "processing", "done", "error"):
                self.assertTrue(paths[name].is_dir())


# ---------------------------------------------------------------------------
# list_pending
# ---------------------------------------------------------------------------

class TestListPending(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_empty_queue_returns_empty_list(self):
        from worker.queue import list_pending
        result = list_pending(self.root)
        self.assertEqual(result, [])

    def test_eligible_job_returned(self):
        from worker.queue import Job, enqueue, list_pending
        job = Job(id="p1", type="noop", payload={})
        enqueue(job, root=self.root)
        result = list_pending(self.root)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1]["id"], "p1")

    def test_future_job_excluded(self):
        from worker.queue import Job, enqueue, list_pending
        future_ts = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        job = Job(id="p2", type="noop", payload={}, not_before=future_ts)
        enqueue(job, root=self.root)
        result = list_pending(self.root)
        self.assertEqual(result, [])

    def test_sorted_by_priority_then_enqueued_at(self):
        from worker.queue import Job, enqueue, list_pending
        job_hi = Job(id="hi_pri", type="noop", payload={}, priority=1,
                     enqueued_at="2025-01-01T00:00:00Z")
        job_lo = Job(id="lo_pri", type="noop", payload={}, priority=9,
                     enqueued_at="2025-01-01T00:00:00Z")
        enqueue(job_lo, root=self.root)
        enqueue(job_hi, root=self.root)
        result = list_pending(self.root)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][1]["id"], "hi_pri")

    def test_invalid_not_before_treated_as_eligible(self):
        from worker.queue import _ensure_dirs, list_pending
        _ensure_dirs(self.root)
        p = self.root / "pending" / "bad.json"
        p.write_text(json.dumps({"id": "bad", "type": "noop", "not_before": "not-a-date"}), encoding="utf-8")
        result = list_pending(self.root)
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# start_processing
# ---------------------------------------------------------------------------

class TestStartProcessing(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_moves_to_processing(self):
        from worker.queue import Job, enqueue, start_processing
        job = Job(id="s1", type="noop", payload={})
        pending_path = enqueue(job, root=self.root)
        proc_path = start_processing(pending_path, self.root)
        self.assertIsNotNone(proc_path)
        self.assertIsInstance(proc_path, Path)
        self.assertEqual(proc_path.parent.name, "processing")

    def test_returns_none_when_file_missing(self):
        from worker.queue import _ensure_dirs, start_processing
        _ensure_dirs(self.root)
        nonexistent = self.root / "pending" / "ghost.json"
        result = start_processing(nonexistent, self.root)
        self.assertIsNone(result)

    def test_updates_status_to_processing(self):
        from worker.queue import Job, enqueue, start_processing
        job = Job(id="s2", type="noop", payload={})
        pending_path = enqueue(job, root=self.root)
        proc_path = start_processing(pending_path, self.root)
        self.assertIsNotNone(proc_path)
        data = json.loads(proc_path.read_text())
        self.assertEqual(data["status"], "processing")

    def test_sets_processing_started_at(self):
        from worker.queue import Job, enqueue, start_processing
        job = Job(id="s3", type="noop", payload={})
        pending_path = enqueue(job, root=self.root)
        proc_path = start_processing(pending_path, self.root)
        self.assertIsNotNone(proc_path)
        data = json.loads(proc_path.read_text())
        self.assertIn("processing_started_at", data)


# ---------------------------------------------------------------------------
# finish
# ---------------------------------------------------------------------------

class TestFinish(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def _enqueue_and_start(self, job_id: str):
        from worker.queue import Job, enqueue, start_processing
        job = Job(id=job_id, type="noop", payload={})
        pending_path = enqueue(job, root=self.root)
        return start_processing(pending_path, self.root)

    def test_success_moves_to_done(self):
        from worker.queue import finish
        proc_path = self._enqueue_and_start("f1")
        done_path = finish(proc_path, success=True, root=self.root)
        self.assertEqual(done_path.parent.name, "done")
        self.assertTrue(done_path.exists())

    def test_failure_moves_to_error(self):
        from worker.queue import finish
        proc_path = self._enqueue_and_start("f2")
        err_path = finish(proc_path, success=False, error_msg="oops", root=self.root)
        self.assertEqual(err_path.parent.name, "error")
        self.assertTrue(err_path.exists())

    def test_success_sets_status_done(self):
        from worker.queue import finish
        proc_path = self._enqueue_and_start("f3")
        done_path = finish(proc_path, success=True, root=self.root)
        data = json.loads(done_path.read_text())
        self.assertEqual(data["status"], "done")

    def test_failure_sets_status_error(self):
        from worker.queue import finish
        proc_path = self._enqueue_and_start("f4")
        err_path = finish(proc_path, success=False, error_msg="bad", root=self.root)
        data = json.loads(err_path.read_text())
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["error"], "bad")

    def test_result_stored_on_success(self):
        from worker.queue import finish
        proc_path = self._enqueue_and_start("f5")
        done_path = finish(proc_path, success=True, root=self.root, result={"out": 42})
        data = json.loads(done_path.read_text())
        self.assertEqual(data["result"]["out"], 42)

    def test_non_serializable_result_stored_as_string(self):
        from worker.queue import finish

        class _Unser:
            def __str__(self):
                return "custom"

        proc_path = self._enqueue_and_start("f6")
        done_path = finish(proc_path, success=True, root=self.root, result=_Unser())
        data = json.loads(done_path.read_text())
        self.assertIsInstance(data["result"], str)

    def test_processing_file_removed_after_finish(self):
        from worker.queue import finish
        proc_path = self._enqueue_and_start("f7")
        finish(proc_path, success=True, root=self.root)
        self.assertFalse(proc_path.exists())


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------

class TestRetry(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def _enqueue_and_start(self, job_id: str):
        from worker.queue import Job, enqueue, start_processing
        job = Job(id=job_id, type="noop", payload={})
        pending_path = enqueue(job, root=self.root)
        return start_processing(pending_path, self.root)

    def test_retry_moves_back_to_pending(self):
        from worker.queue import retry
        proc_path = self._enqueue_and_start("r1")
        new_path = retry(proc_path, delay_sec=0, root=self.root)
        self.assertEqual(new_path.parent.name, "pending")

    def test_retry_increments_attempts(self):
        from worker.queue import retry
        proc_path = self._enqueue_and_start("r2")
        new_path = retry(proc_path, delay_sec=0, root=self.root)
        data = json.loads(new_path.read_text())
        self.assertEqual(data["attempts"], 1)

    def test_retry_sets_not_before_in_future_with_delay(self):
        from worker.queue import retry
        proc_path = self._enqueue_and_start("r3")
        new_path = retry(proc_path, delay_sec=30, root=self.root)
        data = json.loads(new_path.read_text())
        nb = datetime.fromisoformat(data["not_before"].replace("Z", "+00:00"))
        self.assertGreater(nb, datetime.now(UTC))

    def test_retry_sets_last_error_reason(self):
        from worker.queue import retry
        proc_path = self._enqueue_and_start("r4")
        new_path = retry(proc_path, delay_sec=0, root=self.root, reason="timed out")
        data = json.loads(new_path.read_text())
        self.assertEqual(data["last_error"], "timed out")

    def test_retry_removes_processing_file(self):
        from worker.queue import retry
        proc_path = self._enqueue_and_start("r5")
        retry(proc_path, delay_sec=0, root=self.root)
        self.assertFalse(proc_path.exists())


# ---------------------------------------------------------------------------
# counts
# ---------------------------------------------------------------------------

class TestCounts(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_counts_empty_queue(self):
        from worker.queue import counts
        c = counts(self.root)
        for k in ("pending", "processing", "done", "error"):
            self.assertEqual(c.get(k), 0)

    def test_counts_after_enqueue(self):
        from worker.queue import Job, counts, enqueue
        enqueue(Job(id="c1", type="noop", payload={}), root=self.root)
        c = counts(self.root)
        self.assertEqual(c["pending"], 1)

    def test_counts_return_dict(self):
        from worker.queue import counts
        c = counts(self.root)
        self.assertIsInstance(c, dict)


# ---------------------------------------------------------------------------
# list_processing and list_error
# ---------------------------------------------------------------------------

class TestListProcessingAndError(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_list_processing_empty(self):
        from worker.queue import list_processing
        self.assertEqual(list_processing(self.root), [])

    def test_list_processing_returns_jobs_in_processing(self):
        from worker.queue import Job, enqueue, list_processing, start_processing
        job = Job(id="lp1", type="noop", payload={})
        pending = enqueue(job, root=self.root)
        start_processing(pending, self.root)
        result = list_processing(self.root)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1]["id"], "lp1")

    def test_list_error_empty(self):
        from worker.queue import list_error
        self.assertEqual(list_error(self.root), [])

    def test_list_error_returns_failed_jobs(self):
        from worker.queue import Job, enqueue, finish, list_error, start_processing
        job = Job(id="le1", type="noop", payload={})
        pending = enqueue(job, root=self.root)
        proc = start_processing(pending, self.root)
        finish(proc, success=False, error_msg="fail", root=self.root)
        result = list_error(self.root)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1]["id"], "le1")


# ---------------------------------------------------------------------------
# requeue_error
# ---------------------------------------------------------------------------

class TestRequeueError(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def _make_error_job(self, job_id: str) -> Path:
        from worker.queue import Job, enqueue, finish, start_processing
        job = Job(id=job_id, type="noop", payload={})
        p = enqueue(job, root=self.root)
        proc = start_processing(p, self.root)
        return finish(proc, success=False, error_msg="boom", root=self.root)

    def test_requeue_error_moves_to_pending(self):
        from worker.queue import requeue_error
        err_path = self._make_error_job("re1")
        new_path = requeue_error(err_path, root=self.root)
        self.assertEqual(new_path.parent.name, "pending")

    def test_requeue_error_resets_status_to_pending(self):
        from worker.queue import requeue_error
        err_path = self._make_error_job("re2")
        new_path = requeue_error(err_path, root=self.root)
        data = json.loads(new_path.read_text())
        self.assertEqual(data["status"], "pending")

    def test_requeue_error_reset_attempts(self):
        from worker.queue import requeue_error
        err_path = self._make_error_job("re3")
        new_path = requeue_error(err_path, root=self.root, reset_attempts=True)
        data = json.loads(new_path.read_text())
        self.assertEqual(data["attempts"], 0)

    def test_requeue_error_preserves_attempts_without_reset(self):
        from worker.queue import requeue_error
        err_path = self._make_error_job("re4")
        data = json.loads(err_path.read_text())
        data["attempts"] = 2
        err_path.write_text(json.dumps(data), encoding="utf-8")
        new_path = requeue_error(err_path, root=self.root, reset_attempts=False)
        result = json.loads(new_path.read_text())
        self.assertEqual(result["attempts"], 2)

    def test_requeue_error_sets_new_max_attempts(self):
        from worker.queue import requeue_error
        err_path = self._make_error_job("re5")
        new_path = requeue_error(err_path, root=self.root, new_max_attempts=10)
        data = json.loads(new_path.read_text())
        self.assertEqual(data["max_attempts"], 10)

    def test_requeue_error_strips_error_field(self):
        from worker.queue import requeue_error
        err_path = self._make_error_job("re6")
        new_path = requeue_error(err_path, root=self.root)
        data = json.loads(new_path.read_text())
        self.assertNotIn("error", data)
        self.assertIn("last_error", data)

    def test_requeue_error_removes_old_file(self):
        from worker.queue import requeue_error
        err_path = self._make_error_job("re7")
        requeue_error(err_path, root=self.root)
        self.assertFalse(err_path.exists())

    def test_requeue_error_with_delay(self):
        from worker.queue import requeue_error
        err_path = self._make_error_job("re8")
        new_path = requeue_error(err_path, delay_sec=60, root=self.root)
        data = json.loads(new_path.read_text())
        nb = datetime.fromisoformat(data["not_before"].replace("Z", "+00:00"))
        self.assertGreater(nb, datetime.now(UTC))


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

class TestStatus(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_status_returns_expected_keys(self):
        from worker.queue import status
        s = status(self.root)
        for key in ("counts", "pending_by_priority", "oldest_pending_wait_sec",
                    "next_scheduled_in_sec", "processing_oldest_age_sec",
                    "recent_error_ids", "root"):
            self.assertIn(key, s)

    def test_status_empty_queue(self):
        from worker.queue import status
        s = status(self.root)
        self.assertEqual(s["oldest_pending_wait_sec"], 0)
        self.assertIsNone(s["next_scheduled_in_sec"])
        self.assertEqual(s["recent_error_ids"], [])

    def test_status_counts_jobs(self):
        from worker.queue import Job, enqueue, status
        enqueue(Job(id="st1", type="noop", payload={}), root=self.root)
        s = status(self.root)
        self.assertEqual(s["counts"]["pending"], 1)

    def test_status_recent_error_ids(self):
        from worker.queue import Job, enqueue, finish, start_processing, status
        job = Job(id="sterr1", type="noop", payload={})
        p = enqueue(job, root=self.root)
        proc = start_processing(p, self.root)
        finish(proc, success=False, error_msg="fail", root=self.root)
        s = status(self.root)
        self.assertIn("sterr1", s["recent_error_ids"])

    def test_status_root_matches(self):
        from worker.queue import status
        s = status(self.root)
        self.assertEqual(s["root"], str(self.root))

    def test_status_pending_by_priority(self):
        from worker.queue import Job, enqueue, status
        enqueue(Job(id="spri1", type="noop", payload={}, priority=1), root=self.root)
        enqueue(Job(id="spri2", type="noop", payload={}, priority=1), root=self.root)
        s = status(self.root)
        by_pri = s["pending_by_priority"]
        self.assertEqual(by_pri.get("1"), 2)

    def test_status_next_scheduled_in_sec_for_future_job(self):
        from worker.queue import Job, enqueue, status
        future_ts = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        enqueue(Job(id="sfut", type="noop", payload={}, not_before=future_ts), root=self.root)
        s = status(self.root)
        self.assertIsNotNone(s["next_scheduled_in_sec"])
        self.assertGreater(s["next_scheduled_in_sec"], 0)

    def test_status_oldest_pending_wait_populated(self):
        from worker.queue import _ensure_dirs, status
        _ensure_dirs(self.root)
        # Write a job with a past not_before to force wait > 0
        p = self.root / "pending" / "past_job.json"
        past_ts = (datetime.now(UTC) - timedelta(seconds=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
        p.write_text(json.dumps({
            "id": "past_job", "type": "noop", "priority": 5,
            "not_before": past_ts, "enqueued_at": past_ts
        }), encoding="utf-8")
        s = status(self.root)
        self.assertGreater(s["oldest_pending_wait_sec"], 0)


# ---------------------------------------------------------------------------
# find_job_path_by_id
# ---------------------------------------------------------------------------

class TestFindJobPathById(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_finds_pending_job(self):
        from worker.queue import Job, enqueue, find_job_path_by_id
        enqueue(Job(id="fj1", type="noop", payload={}), root=self.root)
        p = find_job_path_by_id("fj1", root=self.root)
        self.assertIsNotNone(p)
        self.assertEqual(p.parent.name, "pending")

    def test_finds_done_job(self):
        from worker.queue import Job, enqueue, finish, find_job_path_by_id, start_processing
        job = Job(id="fj2", type="noop", payload={})
        pending = enqueue(job, root=self.root)
        proc = start_processing(pending, self.root)
        finish(proc, success=True, root=self.root)
        p = find_job_path_by_id("fj2", root=self.root)
        self.assertIsNotNone(p)
        self.assertEqual(p.parent.name, "done")

    def test_finds_error_job(self):
        from worker.queue import Job, enqueue, finish, find_job_path_by_id, start_processing
        job = Job(id="fj3", type="noop", payload={})
        pending = enqueue(job, root=self.root)
        proc = start_processing(pending, self.root)
        finish(proc, success=False, error_msg="fail", root=self.root)
        p = find_job_path_by_id("fj3", root=self.root)
        self.assertIsNotNone(p)
        self.assertEqual(p.parent.name, "error")

    def test_returns_none_for_missing_job(self):
        from worker.queue import find_job_path_by_id, _ensure_dirs
        _ensure_dirs(self.root)
        p = find_job_path_by_id("no-such-id", root=self.root)
        self.assertIsNone(p)


# ---------------------------------------------------------------------------
# purge
# ---------------------------------------------------------------------------

class TestPurge(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def _make_old_file(self, folder: str, job_id: str, age_sec: int = 3600) -> Path:
        from worker.queue import _ensure_dirs
        paths = _ensure_dirs(self.root)
        p = paths[folder] / f"{job_id}.json"
        p.write_text(json.dumps({"id": job_id, "type": "noop"}), encoding="utf-8")
        past = time.time() - age_sec
        os.utime(p, (past, past))
        return p

    def test_purge_removes_old_done_jobs(self):
        from worker.queue import purge
        p = self._make_old_file("done", "old1", age_sec=3600)
        result = purge(1800, root=self.root, folders=["done"])
        self.assertEqual(result["done"], 1)
        self.assertFalse(p.exists())

    def test_purge_removes_old_error_jobs(self):
        from worker.queue import purge
        p = self._make_old_file("error", "olderr1", age_sec=3600)
        result = purge(1800, root=self.root, folders=["error"])
        self.assertEqual(result["error"], 1)
        self.assertFalse(p.exists())

    def test_purge_skips_recent_files(self):
        from worker.queue import purge
        p = self._make_old_file("done", "recent1", age_sec=10)
        result = purge(3600, root=self.root, folders=["done"])
        self.assertEqual(result["done"], 0)
        self.assertTrue(p.exists())

    def test_purge_defaults_to_done_and_error(self):
        from worker.queue import purge, _ensure_dirs
        _ensure_dirs(self.root)
        result = purge(1800, root=self.root)
        self.assertIn("done", result)
        self.assertIn("error", result)

    def test_purge_returns_zero_for_empty_folder(self):
        from worker.queue import purge
        result = purge(1800, root=self.root, folders=["done"])
        self.assertEqual(result["done"], 0)

    def test_purge_multiple_old_files(self):
        from worker.queue import purge
        p1 = self._make_old_file("done", "multi1", age_sec=7200)
        p2 = self._make_old_file("done", "multi2", age_sec=7200)
        result = purge(3600, root=self.root, folders=["done"])
        self.assertEqual(result["done"], 2)
        self.assertFalse(p1.exists())
        self.assertFalse(p2.exists())


# ---------------------------------------------------------------------------
# reap_stale_processing_jobs
# ---------------------------------------------------------------------------

class TestReapStaleProcessingJobs(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_reap_moves_stale_job_to_pending(self):
        from worker.queue import Job, enqueue, start_processing, reap_stale_processing_jobs
        job = Job(id="reap1", type="noop", payload={})
        pending = enqueue(job, root=self.root)
        proc_path = start_processing(pending, self.root)
        old_ts = (datetime.now(UTC) - timedelta(seconds=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = json.loads(proc_path.read_text())
        data["processing_started_at"] = old_ts
        proc_path.write_text(json.dumps(data), encoding="utf-8")
        past = time.time() - 200
        os.utime(proc_path, (past, past))

        reaped = reap_stale_processing_jobs(100, root=self.root)
        self.assertIn("reap1", reaped)
        self.assertTrue((self.root / "pending" / "reap1.json").exists())

    def test_reap_skips_job_within_timeout(self):
        from worker.queue import Job, enqueue, start_processing, reap_stale_processing_jobs
        job = Job(id="norap1", type="noop", payload={})
        pending = enqueue(job, root=self.root)
        proc_path = start_processing(pending, self.root)
        past = time.time() - 5
        os.utime(proc_path, (past, past))
        reaped = reap_stale_processing_jobs(300, root=self.root)
        self.assertNotIn("norap1", reaped)

    def test_reap_skips_when_timeout_zero(self):
        from worker.queue import Job, enqueue, start_processing, reap_stale_processing_jobs
        job = Job(id="norap2", type="noop", payload={})
        pending = enqueue(job, root=self.root)
        proc_path = start_processing(pending, self.root)
        past = time.time() - 10000
        os.utime(proc_path, (past, past))
        reaped = reap_stale_processing_jobs(0, root=self.root)
        self.assertNotIn("norap2", reaped)

    def test_reap_uses_per_job_timeout_override(self):
        from worker.queue import Job, enqueue, start_processing, reap_stale_processing_jobs
        job = Job(id="pertob", type="noop", payload={}, timeout_sec=30)
        pending = enqueue(job, root=self.root)
        proc_path = start_processing(pending, self.root)
        old_ts = (datetime.now(UTC) - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = json.loads(proc_path.read_text())
        data["processing_started_at"] = old_ts
        data["timeout_sec"] = 30
        proc_path.write_text(json.dumps(data), encoding="utf-8")
        # daemon-level timeout=0 but per-job=30; age=60 > 30 so should be reaped
        reaped = reap_stale_processing_jobs(0, root=self.root)
        self.assertIn("pertob", reaped)

    def test_reap_job_with_no_start_time_uses_mtime(self):
        from worker.queue import _ensure_dirs, reap_stale_processing_jobs
        _ensure_dirs(self.root)
        p = self.root / "processing" / "mtime_job.json"
        data = {"id": "mtime_job", "type": "noop", "status": "processing"}
        p.write_text(json.dumps(data), encoding="utf-8")
        # No processing_started_at — only mtime matters
        past = time.time() - 500
        os.utime(p, (past, past))
        reaped = reap_stale_processing_jobs(200, root=self.root)
        self.assertIn("mtime_job", reaped)

    def test_reap_returns_empty_when_no_processing_jobs(self):
        from worker.queue import reap_stale_processing_jobs, _ensure_dirs
        _ensure_dirs(self.root)
        reaped = reap_stale_processing_jobs(60, root=self.root)
        self.assertEqual(reaped, [])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class TestParseTimestampSafe(unittest.TestCase):
    def test_valid_timestamp(self):
        from worker.queue import _parse_timestamp_safe
        dummy_path = Path("/tmp/x.json")  # nosec B108 - test only
        result = _parse_timestamp_safe("2025-01-01T00:00:00Z", dummy_path, "updated_at")
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2025)

    def test_empty_string_returns_none(self):
        from worker.queue import _parse_timestamp_safe
        dummy_path = Path("/tmp/x.json")  # nosec B108 - test only
        result = _parse_timestamp_safe("", dummy_path, "updated_at")
        self.assertIsNone(result)

    def test_invalid_timestamp_returns_none(self):
        from worker.queue import _parse_timestamp_safe
        dummy_path = Path("/tmp/x.json")  # nosec B108 - test only
        result = _parse_timestamp_safe("not-a-date", dummy_path, "updated_at")
        self.assertIsNone(result)


class TestGetFileMtime(unittest.TestCase):
    def test_existing_file_returns_datetime(self):
        from worker.queue import _get_file_mtime
        with tempfile.NamedTemporaryFile() as f:
            result = _get_file_mtime(Path(f.name))
        self.assertIsNotNone(result)
        self.assertIsInstance(result, datetime)

    def test_missing_file_returns_none(self):
        from worker.queue import _get_file_mtime
        result = _get_file_mtime(Path("/tmp/no-such-file-xyz.json"))  # nosec B108 - test only
        self.assertIsNone(result)


class TestUpdateWaitMetrics(unittest.TestCase):
    def test_eligible_job_increases_oldest_wait(self):
        from worker.queue import _update_wait_metrics
        now = datetime.now(UTC)
        nb = now - timedelta(seconds=100)
        oldest_wait, _ = _update_wait_metrics(nb, None, now, 0, None)
        self.assertGreaterEqual(oldest_wait, 99)

    def test_future_job_sets_next_in(self):
        from worker.queue import _update_wait_metrics
        now = datetime.now(UTC)
        nb = now + timedelta(seconds=120)
        _, next_in = _update_wait_metrics(nb, None, now, 0, None)
        self.assertIsNotNone(next_in)
        self.assertGreater(next_in, 0)

    def test_next_in_takes_minimum_of_existing(self):
        from worker.queue import _update_wait_metrics
        now = datetime.now(UTC)
        nb = now + timedelta(seconds=60)
        # Existing next_in=300 (larger); new delta ~60 should win (be smaller)
        _, next_in = _update_wait_metrics(nb, None, now, 0, 300)
        self.assertLessEqual(next_in, 300)

    def test_next_in_not_overridden_when_larger(self):
        from worker.queue import _update_wait_metrics
        now = datetime.now(UTC)
        nb = now + timedelta(seconds=600)
        # Existing next_in=30 is smaller; must not be replaced by 600
        _, next_in = _update_wait_metrics(nb, None, now, 0, 30)
        self.assertEqual(next_in, 30)

    def test_uses_enq_when_nb_is_none(self):
        from worker.queue import _update_wait_metrics
        now = datetime.now(UTC)
        enq = now - timedelta(seconds=50)
        oldest_wait, _ = _update_wait_metrics(None, enq, now, 0, None)
        self.assertGreaterEqual(oldest_wait, 49)


class TestApplyMaxAttempts(unittest.TestCase):
    def test_sets_max_attempts_on_data(self):
        from worker.queue import _apply_max_attempts
        data = {}
        _apply_max_attempts(data, 7)
        self.assertEqual(data["max_attempts"], 7)

    def test_invalid_value_does_not_raise(self):
        from worker.queue import _apply_max_attempts
        data = {}
        # Should not raise — logs debug instead
        _apply_max_attempts(data, "not-a-number")


class TestStripErrorField(unittest.TestCase):
    def test_moves_error_to_last_error(self):
        from worker.queue import _strip_error_field
        data = {"error": "boom"}
        _strip_error_field(data, Path("/tmp/x.json"))  # nosec B108 - test only
        self.assertNotIn("error", data)
        self.assertEqual(data["last_error"], "boom")

    def test_last_error_set_when_no_error_key(self):
        from worker.queue import _strip_error_field
        data = {}
        _strip_error_field(data, Path("/tmp/x.json"))  # nosec B108 - test only
        self.assertIn("last_error", data)


class TestRemoveJobFile(unittest.TestCase):
    def test_removes_existing_file(self):
        from worker.queue import _remove_job_file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            tmp = Path(f.name)
        _remove_job_file(tmp)
        self.assertFalse(tmp.exists())

    def test_missing_file_does_not_raise(self):
        from worker.queue import _remove_job_file
        _remove_job_file(Path("/tmp/no-such-file-remove.json"))  # nosec B108 - test only


class TestComputePendingInsights(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_empty_folder_returns_zeros(self):
        from worker.queue import _compute_pending_insights, _ensure_dirs
        paths = _ensure_dirs(self.root)
        now = datetime.now(UTC)
        oldest, next_in, by_pri = _compute_pending_insights(paths["pending"], now)
        self.assertEqual(oldest, 0)
        self.assertIsNone(next_in)
        self.assertEqual(by_pri, {})

    def test_counts_by_priority(self):
        from worker.queue import Job, enqueue, _compute_pending_insights, _ensure_dirs
        enqueue(Job(id="ci1", type="noop", payload={}, priority=2), root=self.root)
        enqueue(Job(id="ci2", type="noop", payload={}, priority=2), root=self.root)
        paths = _ensure_dirs(self.root)
        now = datetime.now(UTC)
        _, _, by_pri = _compute_pending_insights(paths["pending"], now)
        self.assertEqual(by_pri.get("2"), 2)


class TestComputeProcessingOldestAge(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_no_processing_returns_zero(self):
        from worker.queue import _compute_processing_oldest_age
        now = datetime.now(UTC)
        result = _compute_processing_oldest_age([], now)
        self.assertEqual(result, 0)

    def test_with_processing_job_returns_age(self):
        from worker.queue import Job, enqueue, start_processing, _compute_processing_oldest_age, list_processing
        job = Job(id="age1", type="noop", payload={})
        pending = enqueue(job, root=self.root)
        proc_path = start_processing(pending, self.root)
        data = json.loads(proc_path.read_text())
        old_ts = (datetime.now(UTC) - timedelta(seconds=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data["processing_started_at"] = old_ts
        proc_path.write_text(json.dumps(data), encoding="utf-8")
        items = list_processing(self.root)
        now = datetime.now(UTC)
        result = _compute_processing_oldest_age(items, now)
        self.assertGreaterEqual(result, 49)


class TestListJobPaths(unittest.TestCase):
    def test_nonexistent_folder_returns_empty(self):
        from worker.queue import _list_job_paths
        result = _list_job_paths(Path("/tmp/no-such-folder-xyz"))  # nosec B108 - test only
        self.assertEqual(result, [])

    def test_only_json_files_returned(self):
        from worker.queue import _list_job_paths
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            (folder / "job.json").write_text("{}")
            (folder / "notes.txt").write_text("ignore me")
            result = _list_job_paths(folder)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].name, "job.json")


class TestReapResolveFallbackToUpdatedAt(unittest.TestCase, QueueRootIsolationMixin):
    """_reap_resolve_start_time falls back to updated_at then mtime."""

    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_falls_back_to_updated_at_when_no_processing_started_at(self):
        from worker.queue import _ensure_dirs, reap_stale_processing_jobs
        _ensure_dirs(self.root)
        old_ts = (datetime.now(UTC) - timedelta(seconds=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
        p = self.root / "processing" / "fallback_job.json"
        # Use updated_at but no processing_started_at
        data = {"id": "fallback_job", "type": "noop", "status": "processing",
                "updated_at": old_ts}
        p.write_text(json.dumps(data), encoding="utf-8")
        reaped = reap_stale_processing_jobs(100, root=self.root)
        self.assertIn("fallback_job", reaped)


if __name__ == "__main__":
    unittest.main()
