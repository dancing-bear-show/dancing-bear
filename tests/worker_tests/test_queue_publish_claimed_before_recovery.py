"""Recovery of an interrupted publish whose ``dest`` was claimed first.

A publish can put the staged record at pending/<id>.json and stop before
``staged.unlink()``. If another daemon claims that pending/ record before
this queue's recovery runs, ``dest`` is gone and recovery used to publish the
staged copy again: the second copy waited behind ``start_processing``'s
duplicate-claim refusal and ran as soon as the first claim finished.

Every publisher now writes a fresh ``REQUEUE_ID_FIELD`` into the staged
record, and claim/finish keep it, so recovery recognises the claimed or
finished descendant and discards the staged copy (and any leftover temp).

The crash state is produced by the real requeue/retry paths with the
post-publish unlinks suppressed. No threads are started.
"""

from __future__ import annotations

import errno
import json
import os
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from tests.worker_tests.helpers import QueueRootIsolationMixin
from worker import queue_ops as q

_JOB_ID = "j1"
_real_link = os.link


def _link_without_hardlinks_for_staged(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
    """``os.link`` that reports "no hard links" for the staged file only.

    Sends ``_publish_no_clobber`` down the ``_copy_exclusive`` temp-link path.
    """
    if str(src).endswith(q._REQUEUE_STAGING_SUFFIX):
        raise OSError(errno.EPERM, "hard links unsupported")
    _real_link(src, dst)


def _no_unlink(self: Path, missing_ok: bool = False) -> None:
    """Stand-in for a crash between publishing ``dest`` and removing ``staged``."""


class _Base(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()
        paths = q._ensure_dirs(self.root)
        self.pending = paths["pending"]
        self.processing = paths["processing"]
        self.done = paths["done"]
        self.staged = self.processing / f"{_JOB_ID}.json{q._REQUEUE_STAGING_SUFFIX}"
        self.dest = self.pending / f"{_JOB_ID}.json"
        self.runs = 0

    def _enqueue(self, **payload: object) -> None:
        q.enqueue(q.Job(id=_JOB_ID, type="noop", payload=dict(payload)), root=self.root)

    def _claim(self) -> tuple[Path, str]:
        claim = q.start_processing(self.dest, self.root)
        assert claim is not None
        self.runs += 1
        return claim

    def _crash_after_publish(self, publish: Callable[[], object], *, hard_links: bool) -> None:
        """Run ``publish`` so it stops after ``dest`` exists, before ``staged`` goes."""
        with mock.patch.object(Path, "unlink", _no_unlink):
            if hard_links:
                publish()
            else:
                with mock.patch.object(q.os, "link", _link_without_hardlinks_for_staged):
                    publish()
        self.assertTrue(self.staged.exists())
        self.assertTrue(self.dest.exists())

    def _requeue_crash(self, *, hard_links: bool) -> None:
        self._enqueue()
        self._claim()
        self.runs = 0
        self._crash_after_publish(
            lambda: q.requeue_processing(_JOB_ID, reason="shutdown", root=self.root),
            hard_links=hard_links,
        )

    def _drain(self) -> None:
        """Recover, then claim and finish every eligible pending job, as a daemon tick would."""
        q.recover_staged_requeues(self.root)
        for path, _ in q.list_pending(self.root):
            claim = q.start_processing(path, self.root)
            if claim is not None:
                self.runs += 1
                q.finish(claim[0], True, root=self.root, claim_token=claim[1])

    def _publish_temps(self) -> list[str]:
        return sorted(p.name for p in self.pending.glob(f".{_JOB_ID}.json.tmp.*"))


class TestClaimedBeforeRecoveryHardLink(_Base):
    """Direct publish: ``os.link(staged, dest)``."""

    hard_links = True

    def test_claimed_publish_is_not_republished(self) -> None:
        self._requeue_crash(hard_links=self.hard_links)
        proc_path, token = self._claim()

        self.assertEqual(q.recover_staged_requeues(self.root), [])

        self.assertFalse(self.staged.exists())
        self.assertEqual(self._publish_temps(), [])
        self.assertEqual(sorted(p.name for p in self.pending.iterdir()), [])
        q.finish(proc_path, True, root=self.root, claim_token=token)
        self._drain()
        self.assertEqual(self.runs, 1)

    def test_finished_publish_is_not_republished(self) -> None:
        self._requeue_crash(hard_links=self.hard_links)
        proc_path, token = self._claim()
        q.finish(proc_path, True, root=self.root, claim_token=token)

        self.assertEqual(q.recover_staged_requeues(self.root), [])

        self.assertFalse(self.staged.exists())
        self.assertEqual(self._publish_temps(), [])
        self._drain()
        self.assertEqual(self.runs, 1)

    def test_new_enqueue_of_same_id_still_runs(self) -> None:
        self._requeue_crash(hard_links=self.hard_links)
        proc_path, token = self._claim()
        q.finish(proc_path, True, root=self.root, claim_token=token)
        self._drain()

        self._enqueue(second=True)
        self._drain()

        self.assertEqual(self.runs, 2)
        record = json.loads((self.done / f"{_JOB_ID}.json").read_text())
        self.assertEqual(record["payload"], {"second": True})

    def test_new_enqueue_while_stale_staged_remains_runs_once(self) -> None:
        """No recovery pass between the first run and the re-enqueue."""
        self._requeue_crash(hard_links=self.hard_links)
        proc_path, token = self._claim()
        q.finish(proc_path, True, root=self.root, claim_token=token)
        self._enqueue(second=True)

        self._drain()
        self._drain()

        self.assertEqual(self.runs, 2)
        self.assertFalse(self.staged.exists())
        record = json.loads((self.done / f"{_JOB_ID}.json").read_text())
        self.assertEqual(record["payload"], {"second": True})


class TestClaimedBeforeRecoveryTempLink(TestClaimedBeforeRecoveryHardLink):
    """Fallback publish: ``_copy_exclusive`` temp file linked to ``dest``."""

    hard_links = False


class TestRetryPublishClaimedBeforeRecovery(_Base):
    """``retry`` writes its own staged record, so it carries an identity too."""

    def test_retry_publish_is_not_republished(self) -> None:
        self._enqueue()
        proc_path, token = self._claim()
        self._crash_after_publish(
            lambda: q.retry(proc_path, delay_sec=0, root=self.root, claim_token=token),
            hard_links=True,
        )
        second_path, second_token = self._claim()

        self.assertEqual(q.recover_staged_requeues(self.root), [])

        self.assertFalse(self.staged.exists())
        q.finish(second_path, True, root=self.root, claim_token=second_token)
        self._drain()
        self.assertEqual(self.runs, 2)


class TestUnpublishedStagedIsStillPublished(_Base):
    """Only a ``pending`` staged record can have been published already."""

    def test_unrewritten_staged_with_matching_id_is_published(self) -> None:
        stale = {"id": _JOB_ID, "type": "noop", "status": "done", q.REQUEUE_ID_FIELD: "a" * 32}
        (self.done / f"{_JOB_ID}.json").write_text(json.dumps(stale))
        self.staged.write_text(json.dumps({**stale, "status": "processing"}))

        self.assertEqual(q.recover_staged_requeues(self.root), [_JOB_ID])

        self.assertTrue(self.dest.exists())
        self.assertNotEqual(
            json.loads(self.dest.read_text())[q.REQUEUE_ID_FIELD], "a" * 32
        )

    def test_staged_without_identity_is_published(self) -> None:
        record = {"id": _JOB_ID, "type": "noop", "status": "pending"}
        (self.done / f"{_JOB_ID}.json").write_text(json.dumps(record))
        self.staged.write_text(json.dumps(record))

        self.assertEqual(q.recover_staged_requeues(self.root), [_JOB_ID])
        self.assertTrue(self.dest.exists())


if __name__ == "__main__":
    unittest.main()
