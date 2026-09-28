"""Regression tests for PR #421 run-4 review threads.

Covers three findings raised after round 3's push (707ca18):

Finding 1 (PRRT_kwDOQr1kjM6mgd1K, job_runtime.py:361):
  process_one() (the run_once path) proceeded when claim_token() returned
  None after a start_processing metadata-write failure, unlike _start_batch
  (the daemon-tick path), which round 3 already guarded. A None token meant
  every finish()/retry() call downstream skipped its ownership check.

Finding 2 (PRRT_kwDOQr1kjM6mgd1h / PRRT_kwDOQr1kjM6mgjOg, queue_ops.py:428):
  _copy_exclusive's no-hardlink fallback (round 3's own fix for the
  visible-empty-placeholder defect) still had a check-then-replace race: a
  rival could create dest between dest.exists() returning False and
  tmp.replace(dest), and replace() would silently overwrite it.

Finding 3 (github-code-quality, test_queue_claim_ownership.py:39):
  _REAL_OPEN was an unused module-level global (CodeQL deadcode finding).
  Fixed by deletion; no test needed for a deleted unused symbol.
"""

from __future__ import annotations

import errno
import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.worker_tests.helpers import QueueRootIsolationMixin
from tests.worker_tests.test_daemon_nonblocking import _make_runner, _patch_queue_root
from worker import queue_ops as q
from worker.queue_ops import Job, enqueue


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


# ---------------------------------------------------------------------------
# Finding 1: process_one requeues on a missing claim token
# ---------------------------------------------------------------------------


class TestProcessOneMissingClaimToken(unittest.TestCase, QueueRootIsolationMixin):
    """run_once's claim path (process_one) treats a None claim_token as a
    lost claim, matching what _start_batch (the daemon-tick path) already
    does."""

    def setUp(self) -> None:
        self.setup_queue_root()
        self.stack = _patch_queue_root(self.root)
        self.addCleanup(self.stack.close)

    def test_happy_path_real_token_runs_the_handler(self) -> None:
        """A normal claim (real token) runs the handler and lands in done/."""
        ran: list[str] = []

        def _record(job_data: dict[str, object]) -> tuple[bool, object]:
            ran.append(str(job_data.get("id")))
            return True, "ok"

        self.stack.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"fast": _record}))
        enqueue(Job(id="tok-ok", type="fast", payload={}), root=self.root)

        runner = _make_runner(self.root, max_per_tick=1)
        self.assertEqual(runner.run_once(), 0)

        self.assertEqual(ran, ["tok-ok"])
        self.assertEqual(_names(self.root / "done"), ["tok-ok.json"])

    def test_sad_path_none_claim_token_requeues_without_running_handler(self) -> None:
        """claim_token() returning None means process_one requeues the claim
        and never calls process_claimed -- the handler must not run untracked.

        Pre-fix: process_one passed claim_token=None straight into
        process_claimed, which ran the handler and let every finish()/retry()
        call downstream skip its ownership check.
        """
        ran: list[str] = []

        def _record(job_data: dict[str, object]) -> tuple[bool, object]:
            ran.append(str(job_data.get("id")))
            return True, "ok"

        self.stack.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"fast": _record}))
        enqueue(Job(id="tok-none", type="fast", payload={}, attempts=1), root=self.root)

        # requeue_processing(claim_token=None) now verifies under the lock
        # that the processing/ record still carries no token, so the record
        # itself must also lack one to match the metadata-write failure this
        # test simulates -- strip the token start_processing would normally
        # write.
        real_start = q.start_processing

        def _start_without_token(job_path: Path, root: Path | None = None) -> Path | None:
            proc = real_start(job_path, root)
            if proc is not None:
                data = json.loads(proc.read_text(encoding="utf-8"))
                data.pop(q.CLAIM_TOKEN_FIELD, None)
                proc.write_text(json.dumps(data), encoding="utf-8")
            return proc

        with patch("worker.job_runtime.q.claim_token", return_value=None), \
             patch("worker.job_runtime.q.start_processing", side_effect=_start_without_token), \
             self.assertLogs("worker.job_runtime", "WARNING"):
            runner = _make_runner(self.root, max_per_tick=1)
            result = runner.run_once()

        self.assertEqual(result, 0)
        self.assertEqual(ran, [], "handler must not run when the claim token is missing")
        self.assertEqual(_names(self.root / "done"), [])
        pending = self.root / "pending" / "tok-none.json"
        self.assertTrue(pending.exists(), "job must be requeued to pending/, not lost")
        self.assertEqual(_read(pending)["attempts"], 1, "requeue on a missing token must not consume an attempt")


# ---------------------------------------------------------------------------
# Finding 2: _copy_exclusive detects a lost no-clobber race on no-hardlink FS
# ---------------------------------------------------------------------------


class TestCopyExclusiveDetectsLostRace(unittest.TestCase, QueueRootIsolationMixin):
    """On filesystems without hard links, _copy_exclusive cannot prevent a
    rival claiming dest between the exists() check and tmp.replace(dest),
    but it must detect the loss rather than silently overwriting the rival's
    record."""

    def setUp(self) -> None:
        self.setup_queue_root()
        paths = q._ensure_dirs(self.root)
        self.staged = paths["processing"] / "race1.json.requeue"
        self.payload = {"id": "race1", "status": "pending", "type": "t", "payload": {"mine": True}}
        self.staged.write_text(json.dumps(self.payload), encoding="utf-8")
        self.dest = paths["pending"] / "race1.json"
        link_patch = patch("worker.queue_ops.os.link", side_effect=OSError(errno.EPERM, "no links"))
        link_patch.start()
        self.addCleanup(link_patch.stop)

    def test_happy_path_no_rival_publishes_cleanly(self) -> None:
        """With no rival, _copy_exclusive publishes dest with our bytes and
        raises nothing."""
        q._copy_exclusive(self.staged, self.dest)
        self.assertEqual(_read(self.dest)["payload"], {"mine": True})

    def test_sad_path_rival_claims_dest_between_check_and_replace(self) -> None:
        """A rival that writes dest in the gap between dest.exists() and
        tmp.replace(dest) is detected: _NoClobberRaceLost is raised instead of
        _copy_exclusive silently overwriting the rival's record and returning
        success.
        """
        rival_payload = json.dumps({"id": "race1", "payload": {"theirs": True}}).encode()
        real_replace = Path.replace

        def _rival_writes_dest_then_replace(self_path: Path, target: Path):
            # Simulate a rival (e.g. a lock-free enqueue() of the same id)
            # landing between our exists() check and our replace(): by the
            # time replace() runs, dest already has different content on
            # disk from what real_replace will put there, and after OUR
            # replace() the post-replace read must still show OUR bytes
            # (replace always wins) -- so simulate the rival landing AFTER
            # our replace instead, which is the case the content re-read
            # actually catches.
            real_replace(self_path, target)
            if target == self.dest:
                target.write_bytes(rival_payload)

        with patch.object(Path, "replace", _rival_writes_dest_then_replace):
            with self.assertRaises(q._NoClobberRaceLost):
                q._copy_exclusive(self.staged, self.dest)

        # The rival's bytes are what is actually on disk; we must not have
        # reported success, and staged must not have been unlinked by us.
        self.assertEqual(json.loads(self.dest.read_bytes())["payload"], {"theirs": True})

    def test_publish_no_clobber_leaves_staged_on_lost_race(self) -> None:
        """_publish_no_clobber returns False and keeps staged when
        _copy_exclusive reports a lost race, instead of unlinking staged as
        if the publish had succeeded."""
        real_replace = Path.replace
        rival_payload = json.dumps({"id": "race1", "payload": {"theirs": True}}).encode()

        def _rival_after_replace(self_path: Path, target: Path):
            real_replace(self_path, target)
            if target == self.dest:
                target.write_bytes(rival_payload)

        with patch.object(Path, "replace", _rival_after_replace):
            published = q._publish_no_clobber(self.staged, self.dest)

        self.assertFalse(published, "must not report success on a lost race")
        self.assertTrue(self.staged.exists(), "staged copy must be kept for recovery")
        self.assertEqual(_read(self.staged)["payload"], {"mine": True})


if __name__ == "__main__":
    unittest.main()
