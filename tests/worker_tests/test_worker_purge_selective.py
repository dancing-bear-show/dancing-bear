"""Tests for selective worker purge functionality."""

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from tests.worker_tests.helpers import QueueRootIsolationMixin


def _capture_stdout(func, *args, **kwargs):
    """Run func and capture stdout, returning (result, text)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = func(*args, **kwargs)
    return result, buf.getvalue()


def _parse_json(text):
    return json.loads(text.strip())


class TestWorkerPurgeSelective(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.isolate_queue_root()

    def test_purge_done_only(self):
        from worker import queue_ops as q
        from worker.cli import main
        q.QUEUE_ROOT = self.root / "queue"
        q._ensure_dirs(q.QUEUE_ROOT)
        # create done and error with old mtime
        done = q.QUEUE_ROOT / "done" / "d2.json"
        err = q.QUEUE_ROOT / "error" / "e2.json"
        for p in (done, err):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"id": p.stem, "type": "noop"}), encoding="utf-8")
            past = time.time() - 3600
            os.utime(p, (past, past))
        # purge only done
        rc, out = _capture_stdout(main, ["purge", "--older-than", "30m", "--folders", "done"])
        self.assertEqual(rc, 0)
        res = _parse_json(out)
        self.assertGreaterEqual(res.get("done", 0), 1)
        # error should not be purged
        self.assertFalse(res.get("error", 0))
        self.assertTrue(err.exists())

    def test_purge_error_only(self):
        from worker import queue_ops as q
        from worker.cli import main
        q.QUEUE_ROOT = self.root / "queue"
        q._ensure_dirs(q.QUEUE_ROOT)
        err = q.QUEUE_ROOT / "error" / "e3.json"
        err.parent.mkdir(parents=True, exist_ok=True)
        err.write_text(json.dumps({"id": "e3", "type": "noop"}), encoding="utf-8")
        past = time.time() - 3600
        os.utime(err, (past, past))
        rc, out = _capture_stdout(main, ["purge", "--older-than", "30m", "--folders", "error"])
        self.assertEqual(rc, 0)
        res = _parse_json(out)
        self.assertGreaterEqual(res.get("error", 0), 1)


if __name__ == "__main__":
    unittest.main()
