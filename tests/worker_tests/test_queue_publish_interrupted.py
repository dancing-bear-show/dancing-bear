"""Recovery of a publish interrupted after ``dest`` was written.

``_copy_exclusive`` publishes by hard-linking a hidden temp file to ``dest``
(or renaming it over ``dest``), so ``dest`` is never ``staged``'s inode. A
crash after that publish but before ``staged`` was unlinked left a complete
``dest`` that recovery's ``os.link(staged, dest)`` reported as FileExistsError,
and that branch recognised only ``samefile(staged)``. The staged copy was kept
as a "rival" refusal; once ``dest`` was claimed, the next recovery pass found
pending/ free and published it again, so the job ran twice.
``_is_own_interrupted_publish`` now recognises identical bytes on both
FileExistsError branches, and leftover temp links to ``dest`` are removed.

No threads are started: every case builds the on-disk crash state directly.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from tests.worker_tests.helpers import QueueRootIsolationMixin
from worker import queue_ops as q

_JOB_ID = "j1"


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def _record(**extra: object) -> bytes:
    data: dict[str, object] = {
        "id": _JOB_ID,
        "type": "noop",
        "status": "pending",
        "attempts": 0,
        "not_before": "2026-01-01T00:00:00Z",
    }
    data.update(extra)
    return json.dumps(data).encode()


class _Base(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()
        paths = q._ensure_dirs(self.root)
        self.pending = paths["pending"]
        self.processing = paths["processing"]
        self.staged = self.processing / f"{_JOB_ID}.json.requeue"
        self.dest = self.pending / f"{_JOB_ID}.json"
        self.temp = self.pending / f".{_JOB_ID}.json.tmp.{'0' * 32}"

    def _claim_dest(self) -> None:
        claim = q.start_processing(self.dest, self.root)
        self.assertIsNotNone(claim)

    def _copies_of_job(self) -> int:
        """Count visible records for the job across pending/ and processing/."""
        return sum(
            1 for folder in (self.pending, self.processing)
            if (folder / f"{_JOB_ID}.json").exists()
        )


class TestInterruptedTempLinkPublish(_Base):
    """Crash after ``os.link(tmp, dest)``: dest shares the temp's inode."""

    def setUp(self) -> None:
        super().setUp()
        self.staged.write_bytes(_record())
        self.temp.write_bytes(_record())
        os.link(self.temp, self.dest)

    def test_recovery_recognises_own_publish_and_cleans_up(self) -> None:
        self.assertEqual(q.recover_staged_requeues(self.root), [_JOB_ID])
        self.assertFalse(self.staged.exists())
        self.assertFalse(self.temp.exists())
        self.assertEqual(_names(self.pending), [f"{_JOB_ID}.json"])
        self.assertEqual(self.dest.read_bytes(), _record())

    def test_job_exists_once_after_claim_and_second_recovery(self) -> None:
        q.recover_staged_requeues(self.root)
        self._claim_dest()
        self.assertEqual(q.recover_staged_requeues(self.root), [])
        self.assertEqual(_names(self.pending), [])
        self.assertEqual(_names(self.processing), [f"{_JOB_ID}.json"])
        self.assertEqual(self._copies_of_job(), 1)


class TestInterruptedReplacePublish(_Base):
    """Crash after the no-hardlink ``tmp.replace(dest)``: no temp, distinct inode."""

    def setUp(self) -> None:
        super().setUp()
        self.staged.write_bytes(_record())
        self.dest.write_bytes(_record())

    def test_job_exists_once_after_claim_and_second_recovery(self) -> None:
        self.assertEqual(q.recover_staged_requeues(self.root), [_JOB_ID])
        self.assertFalse(self.staged.exists())
        self._claim_dest()
        self.assertEqual(q.recover_staged_requeues(self.root), [])
        self.assertEqual(self._copies_of_job(), 1)


class TestGenuineRivalIsStillRefused(_Base):
    """A different record at dest is a rival: staged is kept, not dropped."""

    def setUp(self) -> None:
        super().setUp()
        self.staged.write_bytes(_record(payload={"mine": True}))
        self.dest.write_bytes(_record(payload={"theirs": True}))

    def test_rival_is_not_overwritten_and_staged_is_kept(self) -> None:
        self.assertEqual(q.recover_staged_requeues(self.root), [])
        self.assertTrue(self.staged.exists())
        self.assertEqual(self.dest.read_bytes(), _record(payload={"theirs": True}))

    def test_staged_copy_is_published_once_the_rival_is_claimed(self) -> None:
        q.recover_staged_requeues(self.root)
        self._claim_dest()
        self.assertEqual(q.recover_staged_requeues(self.root), [_JOB_ID])
        self.assertIn(b'"mine": true', self.dest.read_bytes())

    def test_unrelated_temp_is_not_removed(self) -> None:
        """A temp that is not a link to dest is never deleted by the cleanup."""
        self.temp.write_bytes(_record(payload={"mine": True}))
        q.recover_staged_requeues(self.root)
        self.assertTrue(self.temp.exists())


class TestDiscardPublishTemps(_Base):
    def test_removes_only_links_to_dest(self) -> None:
        self.dest.write_bytes(_record())
        os.link(self.dest, self.temp)
        other = self.pending / f".{_JOB_ID}.json.tmp.{'1' * 32}"
        other.write_bytes(_record())
        q._discard_publish_temps(self.dest)
        self.assertFalse(self.temp.exists())
        self.assertTrue(other.exists())
        self.assertTrue(self.dest.exists())


if __name__ == "__main__":
    unittest.main()
