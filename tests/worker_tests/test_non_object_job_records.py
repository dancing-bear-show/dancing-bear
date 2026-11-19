"""Queue records that hold valid JSON of a non-object type (null, [], a scalar)."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tests.worker_tests.helpers import QueueRootIsolationMixin

NON_OBJECTS = ("null", "[]", "[1]", "3")


class _QueueCase(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()
        from worker.queue_ops import _ensure_dirs

        self.paths = _ensure_dirs(self.root)

    def _write(self, folder: str, job_id: str, text: str) -> Path:
        p = self.paths[folder] / f"{job_id}.json"
        p.write_text(text, encoding="utf-8")
        return p


class TestStartProcessingNonObject(_QueueCase):
    def test_non_object_record_is_claimed_with_a_fresh_record(self) -> None:
        from worker.queue_ops import CLAIM_TOKEN_FIELD, start_processing

        for i, text in enumerate((*NON_OBJECTS, "{garbage")):
            with self.subTest(text=text):
                pending = self._write("pending", f"bad{i}", text)
                claim = start_processing(pending, self.root)
                assert claim is not None  # nosec B101 - narrows Optional for mypy
                proc, token = claim
                self.assertTrue(token)
                data = json.loads(proc.read_text())
                self.assertEqual(data["status"], "processing")
                self.assertEqual(data[CLAIM_TOKEN_FIELD], token)

    def test_object_record_keeps_its_fields(self) -> None:
        from worker.queue_ops import start_processing

        pending = self._write("pending", "good", json.dumps({"id": "good", "type": "noop"}))
        claim = start_processing(pending, self.root)
        assert claim is not None  # nosec B101 - narrows Optional for mypy
        data = json.loads(claim[0].read_text())
        self.assertEqual((data["id"], data["type"]), ("good", "noop"))


class TestListingsNonObject(_QueueCase):
    def test_list_processing_and_list_error_yield_empty_dicts(self) -> None:
        from worker.queue_ops import list_error, list_processing

        self._write("processing", "p-null", "null")
        self._write("processing", "p-ok", '{"id": "p-ok"}')
        self._write("error", "e-list", "[]")
        processing = {p.stem: d for p, d in list_processing(self.root)}
        self.assertEqual(processing, {"p-null": {}, "p-ok": {"id": "p-ok"}})
        self.assertEqual([d for _, d in list_error(self.root)], [{}])

    def test_pending_insights_count_non_object_at_default_priority(self) -> None:
        from worker.queue_metrics import _compute_pending_insights

        self._write("pending", "n", "null")
        self._write("pending", "a", "[]")
        self._write("pending", "ok", '{"priority": 1}')
        _, _, by_pri = _compute_pending_insights(self.paths["pending"], datetime.now(UTC))
        self.assertEqual(by_pri, {"5": 2, "1": 1})


class TestRequeueErrorNonObject(_QueueCase):
    def test_corrupt_record_raises_and_stays_in_error(self) -> None:
        from worker.queue_ops import requeue_error

        for i, text in enumerate((*NON_OBJECTS, "{garbage")):
            with self.subTest(text=text):
                err = self._write("error", f"bad{i}", text)
                with self.assertRaises(ValueError):
                    requeue_error(err, root=self.root)
                self.assertEqual(err.read_text(), text)
                self.assertFalse((self.paths["pending"] / err.name).exists())

    def test_missing_record_raises_without_publishing_a_stub(self) -> None:
        from worker.queue_ops import requeue_error

        with self.assertRaises(ValueError):
            requeue_error(self.paths["error"] / "ghost.json", root=self.root)
        self.assertEqual(list(self.paths["pending"].iterdir()), [])

    def test_object_record_is_requeued(self) -> None:
        from worker.queue_ops import requeue_error

        err = self._write("error", "ok", '{"id": "ok", "attempts": 2}')
        new_path = requeue_error(err, root=self.root)
        self.assertEqual(json.loads(new_path.read_text())["status"], "pending")
        self.assertFalse(err.exists())

    def test_requeue_errors_command_skips_corrupt_and_requeues_the_rest(self) -> None:
        from worker.commands import RequeueErrorsCommand

        bad = self._write("error", "bad", "null")
        self._write("error", "ok", '{"id": "ok"}')
        args = argparse.Namespace(
            limit=0, delay=0, reset_attempts=False, new_max_attempts=0, since=None, match=[]
        )
        out = io.StringIO()
        with (
            self.assertLogs("worker.commands", level="WARNING") as logs,
            contextlib.redirect_stdout(out),
        ):
            rc = RequeueErrorsCommand.run(args)
        self.assertEqual(rc, 0)
        self.assertTrue(bad.exists())
        self.assertTrue((self.paths["pending"] / "ok.json").exists())
        self.assertIn("bad.json", "\n".join(logs.output))
        self.assertEqual(json.loads(out.getvalue())["requeued"], 1)


if __name__ == "__main__":
    unittest.main()
