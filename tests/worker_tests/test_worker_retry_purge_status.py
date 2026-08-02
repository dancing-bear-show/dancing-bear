"""Tests for worker retry, purge, and status commands."""

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _capture_stdout(func, *args, **kwargs):
    """Run func and capture stdout, returning (result, text)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = func(*args, **kwargs)
    return result, buf.getvalue()


def _parse_json(text):
    return json.loads(text.strip())


from tests.worker_tests.helpers import QueueRootIsolationMixin


class TestWorkerRetryPurgeStatus(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.isolate_queue_root()
        # ensure _data/logs exists for status throughput
        (self.root / "_data" / "logs").mkdir(parents=True, exist_ok=True)

    def _mk_error_job(self, jid="e1", *, updated_at=None, err="boom"):
        from worker import queue as q
        q.QUEUE_ROOT = self.root / "queue"
        q._ensure_dirs(q.QUEUE_ROOT)
        p = q.QUEUE_ROOT / "error" / f"{jid}.json"
        payload = {
            "id": jid,
            "type": "noop",
            "payload": {},
            "status": "error",
            "updated_at": updated_at or "2025-01-01T00:00:00Z",
            "error": err,
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_retry_single_job(self):
        from worker import queue as q
        from worker.cli import main
        q.QUEUE_ROOT = self.root / "queue"
        self._mk_error_job("r1")
        rc, _ = _capture_stdout(main, ["retry", "r1", "--reset-attempts", "--delay", "1"])
        self.assertEqual(rc, 0)
        # moved from error to pending
        c = q.counts(root=q.QUEUE_ROOT)
        self.assertEqual(c.get("pending"), 1)
        self.assertEqual(c.get("error"), 0)

    def test_requeue_errors_since_and_match(self):
        from worker import queue as q
        from worker.cli import main
        q.QUEUE_ROOT = self.root / "queue"
        now = datetime.now(UTC)
        old_ts = (now - timedelta(minutes=10, seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent_ts = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._mk_error_job("e_old", updated_at=old_ts, err="timeout error")
        self._mk_error_job("e_new", updated_at=recent_ts, err="timeout error")
        rc, out = _capture_stdout(main, ["requeue-errors", "--since", "9m", "--match", "timeout"])
        self.assertEqual(rc, 0)
        payload = _parse_json(out)
        self.assertEqual(payload.get("requeued"), 1)
        c = q.counts(root=q.QUEUE_ROOT)
        # one pending, one still error
        self.assertEqual(c.get("pending"), 1)
        self.assertEqual(c.get("error"), 1)

    def test_purge_done_error(self):
        from worker import queue as q
        from worker.cli import main
        q.QUEUE_ROOT = self.root / "queue"
        q._ensure_dirs(q.QUEUE_ROOT)
        done = q.QUEUE_ROOT / "done" / "d1.json"
        err = q.QUEUE_ROOT / "error" / "e1.json"
        for p in (done, err):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"id": p.stem, "type": "noop"}), encoding="utf-8")
            past = time.time() - 3600
            os.utime(p, (past, past))
        rc, out = _capture_stdout(main, ["purge", "--older-than", "30m", "--folders", "done,error"])
        self.assertEqual(rc, 0)
        res = _parse_json(out)
        self.assertGreaterEqual(res.get("done", 0), 1)
        self.assertGreaterEqual(res.get("error", 0), 1)

    def test_status_with_throughput(self):
        from worker.cli import main
        from worker._helpers import DATE_FORMAT_YMD
        cwd = os.getcwd()
        try:
            os.chdir(self.root)
            ymd = datetime.now(UTC).strftime(DATE_FORMAT_YMD)
            p = self.root / "_data" / "logs" / f"perf-worker-{ymd}.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            entries = [
                {"ts": "2025-01-01T00:00:00Z", "prog": "worker", "args": ["daemon", "run_cli", "ok"], "exit_code": 0, "duration_ms": 1000},
                {"ts": "2025-01-01T00:01:00Z", "prog": "worker", "args": ["daemon", "run_cli", "ok"], "exit_code": 0, "duration_ms": 2000},
            ]
            with p.open("a", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e) + "\n")
            rc, out = _capture_stdout(main, ["status", "--text", "--with-throughput"])
            self.assertEqual(rc, 0)
            self.assertIn("Throughput", out)
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
