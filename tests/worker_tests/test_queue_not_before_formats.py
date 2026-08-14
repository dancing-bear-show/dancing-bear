"""Sad-path tests for not_before scheduling across ISO timestamp formats.

worker/cli.py exposes a public --not-before flag taking user-supplied ISO
timestamps. list_pending treats an unparseable not_before as "eligible now"
(worker/queue_ops.py), so any tightening of the timestamp parser silently
converts a deferred job into one that runs immediately -- no error, only a
debug log.

That failure mode has already occurred twice (see PR #190): a Z-only strptime
narrowing, and a missing .strip(). The existing tests did not catch either,
because test_future_job_excluded only exercises the 'Z' form and
test_invalid_not_before_treated_as_eligible only uses obviously-bogus input.
Neither covers a VALID timestamp in a different-but-legal format.

These tests pin the deferral guarantee per format so a future parser change
fails loudly here instead of silently dropping scheduling.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta

from tests.worker_tests.helpers import QueueRootIsolationMixin, _make_root


def _future(**kw) -> datetime:
    return datetime.now(UTC) + timedelta(**kw)


def _past(**kw) -> datetime:
    return datetime.now(UTC) - timedelta(**kw)


class TestNotBeforeFormatsDeferCorrectly(unittest.TestCase, QueueRootIsolationMixin):
    """A future not_before must defer the job in EVERY legal ISO form."""

    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def _write_job(self, job_id: str, not_before: str) -> None:
        from worker.queue_ops import _ensure_dirs
        _ensure_dirs(self.root)
        (self.root / "pending" / f"{job_id}.json").write_text(
            json.dumps({"id": job_id, "type": "noop", "not_before": not_before}),
            encoding="utf-8",
        )

    def _pending_ids(self) -> set[str]:
        from worker.queue_ops import list_pending
        return {data["id"] for _, data in list_pending(self.root)}

    def test_future_z_suffix_is_deferred(self):
        self._write_job("z", _future(hours=1).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertNotIn("z", self._pending_ids())

    def test_future_explicit_utc_offset_is_deferred(self):
        """A '+00:00' offset is valid ISO 8601 and must not read as invalid."""
        self._write_job("offset", _future(hours=1).isoformat())
        self.assertNotIn("offset", self._pending_ids())

    def test_future_fractional_seconds_is_deferred(self):
        ts = _future(hours=1).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        self._write_job("frac", ts)
        self.assertNotIn("frac", self._pending_ids())

    def test_future_with_surrounding_whitespace_is_deferred(self):
        """A stray space (shell quoting, copy-paste) must not defeat deferral."""
        ts = " " + _future(hours=1).strftime("%Y-%m-%dT%H:%M:%SZ") + " "
        self._write_job("padded", ts)
        self.assertNotIn("padded", self._pending_ids())

    def test_all_future_formats_deferred_together(self):
        """Guards against one format regressing while others still pass."""
        f = _future(hours=1)
        for name, ts in {
            "m_z": f.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "m_offset": f.isoformat(),
            "m_frac": f.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "m_pad": " " + f.strftime("%Y-%m-%dT%H:%M:%SZ") + " ",
        }.items():
            self._write_job(name, ts)
        self.assertEqual(self._pending_ids(), set())


class TestEnqueueValidatesNotBefore(unittest.TestCase, QueueRootIsolationMixin):
    """enqueue rejects an unschedulable not_before instead of writing it.

    Catching it at entry means a typo'd --not-before fails immediately with a
    clear error, rather than producing a job that is silently held forever.
    """

    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def test_invalid_not_before_raises(self):
        from worker.queue_ops import Job, enqueue
        job = Job(id="bad", type="noop", payload={}, not_before="not-a-date")
        with self.assertRaises(ValueError):
            enqueue(job, root=self.root)

    def test_invalid_not_before_writes_no_job_file(self):
        from worker.queue_ops import Job, enqueue
        job = Job(id="bad2", type="noop", payload={}, not_before="2026-13-45T99:99:99Z")
        with self.assertRaises(ValueError):
            enqueue(job, root=self.root)
        self.assertEqual(list((self.root / "pending").glob("*.json")), [])

    def test_valid_formats_are_accepted(self):
        from worker.queue_ops import Job, enqueue
        f = _future(hours=1)
        for i, ts in enumerate([
            f.strftime("%Y-%m-%dT%H:%M:%SZ"),
            f.isoformat(),
            f.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            " " + f.strftime("%Y-%m-%dT%H:%M:%SZ") + " ",
        ]):
            enqueue(Job(id=f"ok{i}", type="noop", payload={}, not_before=ts), root=self.root)
        self.assertEqual(len(list((self.root / "pending").glob("*.json"))), 4)

    def test_empty_not_before_defaults_to_now(self):
        from worker.queue_ops import Job, enqueue
        path = enqueue(Job(id="empty", type="noop", payload={}), root=self.root)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(data["not_before"])


class TestNotBeforePastFormatsAreEligible(unittest.TestCase, QueueRootIsolationMixin):
    """A past not_before must make the job eligible in every legal form.

    The mirror of the deferral tests: a parser change that made everything
    unparseable would pass those (all deferred... by accident) unless the
    past-timestamp direction is asserted too.
    """

    def setUp(self):
        self.tmp, self.root = _make_root()
        self.addCleanup(self.tmp.cleanup)
        self.isolate_queue_root()

    def _write_job(self, job_id: str, not_before: str) -> None:
        from worker.queue_ops import _ensure_dirs
        _ensure_dirs(self.root)
        (self.root / "pending" / f"{job_id}.json").write_text(
            json.dumps({"id": job_id, "type": "noop", "not_before": not_before}),
            encoding="utf-8",
        )

    def _pending_ids(self) -> set[str]:
        from worker.queue_ops import list_pending
        return {data["id"] for _, data in list_pending(self.root)}

    def test_past_z_suffix_is_eligible(self):
        self._write_job("pz", _past(hours=1).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertIn("pz", self._pending_ids())

    def test_past_explicit_utc_offset_is_eligible(self):
        self._write_job("poffset", _past(hours=1).isoformat())
        self.assertIn("poffset", self._pending_ids())

    def test_empty_not_before_is_eligible(self):
        self._write_job("empty", "")
        self.assertIn("empty", self._pending_ids())

    def test_unparseable_not_before_is_held_and_warned(self):
        """Hand-edited/legacy files bypass enqueue validation, so the read side
        must still refuse to run them early."""
        self._write_job("broken", "definitely-not-a-timestamp")
        with self.assertLogs("worker.queue_ops", level="WARNING"):
            self.assertNotIn("broken", self._pending_ids())

    def test_one_bad_job_does_not_hide_good_ones(self):
        """A single malformed job must not suppress the rest of the queue."""
        self._write_job("bad", "nonsense")
        self._write_job("good", _past(hours=1).strftime("%Y-%m-%dT%H:%M:%SZ"))
        with self.assertLogs("worker.queue_ops", level="WARNING"):
            ids = self._pending_ids()
        self.assertEqual(ids, {"good"})


if __name__ == "__main__":
    unittest.main()
