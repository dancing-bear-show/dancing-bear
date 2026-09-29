"""Regression tests for PR #421 run-6 review threads.

Covers three findings raised after round 4's push (a3b24a9), all gaps in
round 4's own work:

Finding 1 (PRRT_kwDOQr1kjM6mg1Ml, job_runtime.py:375 and :613/:622):
  Both _start_batch and process_one requeued a tokenless claim by stem alone
  with no ownership check at all -- requeue_processing's claim_token
  parameter defaulted to None, and a bare None is indistinguishable from "no
  token to compare" and "caller has no token concept". Fixed with a
  _NO_TOKEN_CHECK sentinel: both call sites now pass claim_token=None
  explicitly, which requeue_processing/_stage_and_requeue treat as "verify
  the record still carries no token" rather than skipping the check.

Finding 2 (PRRT_kwDOQr1kjM6mg1M1, queue_ops.py:~435):
  _copy_exclusive's temp file was created with mode 0o644 instead of the
  0o600 every other atomic queue writer uses, exposing job payloads to
  group/other on a permissive umask.

Finding 3 (PRRT_kwDOQr1kjM6mg1M8, queue_ops.py:~502):
  On the no-hardlink path, _publish_no_clobber could not distinguish "dest
  already holds MY OWN interrupted publish" (crashed after _copy_exclusive
  succeeded but before staged.unlink()) from "dest holds a rival's record" --
  the samefile() check the hard-link branch uses is unavailable without
  hard links. Fixed with a content comparison: identical bytes finish the
  publish (unlink staged, return True); different bytes are refused as a
  genuine rival, as before.
"""

from __future__ import annotations

import errno
import json
import stat
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
# Finding 1: tokenless requeue verifies the record still carries no token
# ---------------------------------------------------------------------------


class TestTokenlessRequeueVerifiesUnderLock(unittest.TestCase, QueueRootIsolationMixin):
    """requeue_processing(claim_token=None) checks under the transition lock
    that the record still carries no token, rather than requeuing the stem
    unconditionally."""

    def setUp(self) -> None:
        self.setup_queue_root()
        self.join_new_threads_before_restore()

    def test_happy_path_none_token_requeues_when_record_still_tokenless(self) -> None:
        """A processing/ record with no claim token is requeued when
        claim_token=None is passed explicitly (the record's own state
        matches the expectation)."""
        paths = q._ensure_dirs(self.root)
        proc = paths["processing"] / "tokenless1.json"
        proc.write_text(
            json.dumps({"id": "tokenless1", "type": "t", "payload": {}, "status": "processing"}),
            encoding="utf-8",
        )

        result = q.requeue_processing(
            "tokenless1", reason="test-reason", root=self.root, claim_token=None
        )

        self.assertIsNotNone(result, "record with no token must be requeued when expecting None")
        pending = self.root / "pending" / "tokenless1.json"
        self.assertTrue(pending.exists())
        self.assertNotIn(q.CLAIM_TOKEN_FIELD, _read(pending))

    def test_sad_path_none_token_skips_requeue_when_reclaimed_with_real_token(self) -> None:
        """A rival that reclaimed the same stem with a real token between our
        read and this call must not be requeued out from under it.

        Pre-fix: requeue_processing's claim_token defaulted to None with no
        way to say "verify the record is still tokenless", so a call site
        with no explicit token requeued this stem unconditionally --
        clobbering the rival's newer, real claim.
        """
        paths = q._ensure_dirs(self.root)
        proc = paths["processing"] / "reclaimed1.json"
        proc.write_text(
            json.dumps({
                "id": "reclaimed1", "type": "t", "payload": {}, "status": "processing",
                q.CLAIM_TOKEN_FIELD: "rivals-real-token",  # nosec B106 - test claim token, not a secret
            }),
            encoding="utf-8",
        )

        result = q.requeue_processing(
            "reclaimed1", reason="test-reason", root=self.root, claim_token=None
        )

        self.assertIsNone(result, "must not requeue a record a rival has since claimed with a real token")
        self.assertTrue(proc.exists(), "rival's processing/ record must be left alone")
        self.assertEqual(_read(proc)[q.CLAIM_TOKEN_FIELD], "rivals-real-token")
        self.assertFalse((self.root / "pending" / "reclaimed1.json").exists())

    def test_process_one_requeues_with_claim_token_none_explicit(self) -> None:
        """process_one's empty-token branch passes claim_token=None
        explicitly to requeue_processing (not omitted), so the record's
        current state is verified rather than assumed.

        Previously this was tested by patching q.claim_token to return None,
        but claim_token is no longer called in process_one: start_processing now
        returns the token atomically as the second element of its tuple.
        The failure is now simulated by returning (proc_path, "") from
        start_processing with the token stripped from disk.
        """
        base = _patch_queue_root(self.root)
        self.addCleanup(base.close)
        enqueue(Job(id="run-once-tok", type="fast", payload={}, attempts=2), root=self.root)

        real_start = q.start_processing

        def _start_empty_token(
            job_path: Path, root: Path | None = None
        ) -> tuple[Path, str] | None:
            result = real_start(job_path, root)
            if result is not None:
                proc, _tok = result
                data = json.loads(proc.read_text(encoding="utf-8"))
                data.pop(q.CLAIM_TOKEN_FIELD, None)
                proc.write_text(json.dumps(data), encoding="utf-8")
                return proc, ""
            return result

        with patch("worker.job_runtime.q.start_processing", side_effect=_start_empty_token), \
             self.assertLogs("worker.job_runtime", "WARNING"), \
             patch("worker.job_runtime.q.requeue_processing", side_effect=q.requeue_processing) as spy:
            runner = _make_runner(self.root, max_per_tick=1)
            result = runner.run_once()

        self.assertEqual(result, 0)
        spy.assert_called_once()
        self.assertIn("claim_token", spy.call_args.kwargs, "claim_token must be passed explicitly, not omitted")
        self.assertIsNone(spy.call_args.kwargs["claim_token"])


# ---------------------------------------------------------------------------
# Finding 2: _copy_exclusive's temp file uses 0o600, matching every other
# atomic queue writer
# ---------------------------------------------------------------------------


class TestCopyExclusiveTempFileMode(unittest.TestCase, QueueRootIsolationMixin):
    def setUp(self) -> None:
        self.setup_queue_root()
        paths = q._ensure_dirs(self.root)
        self.staged = paths["processing"] / "mode1.json.requeue"
        self.payload = {"id": "mode1", "status": "pending", "type": "t", "payload": {"secret": "value"}}
        self.staged.write_text(json.dumps(self.payload), encoding="utf-8")
        self.dest = paths["pending"] / "mode1.json"
        link_patch = patch("worker.queue_ops.os.link", side_effect=OSError(errno.EPERM, "no links"))
        link_patch.start()
        self.addCleanup(link_patch.stop)

    def test_happy_path_publish_succeeds_with_owner_only_mode(self) -> None:
        """The published record is created with 0o600 (owner rw only),
        matching atomic_write_json's convention -- not 0o644.

        Pre-fix: the temp file (and therefore the published dest) was
        created with 0o644, exposing job payloads to group/other on a
        permissive umask.
        """
        q._copy_exclusive(self.staged, self.dest)

        self.assertTrue(self.dest.exists())
        mode = stat.S_IMODE(self.dest.stat().st_mode)
        self.assertEqual(
            mode, 0o600,
            f"published record has mode {oct(mode)}, expected 0o600 (owner-only)",
        )
        self.assertEqual(_read(self.dest)["payload"], {"secret": "value"})

    def test_sad_path_world_readable_mode_is_never_produced(self) -> None:
        """The world/group-readable bits (0o044) are never set on the
        published file, regardless of the process umask."""
        with patch("os.umask", return_value=0):  # simulate a permissive umask
            q._copy_exclusive(self.staged, self.dest)

        mode = stat.S_IMODE(self.dest.stat().st_mode)
        self.assertEqual(mode & 0o077, 0, f"group/other bits set: {oct(mode)}")


# ---------------------------------------------------------------------------
# Finding 3: _publish_no_clobber recognizes its own interrupted publish
# ---------------------------------------------------------------------------


class TestPublishNoClobberSelfRecognition(unittest.TestCase, QueueRootIsolationMixin):
    """On the no-hardlink path, a dest that already holds OUR OWN content
    (an interrupted publish from a prior call) must be recognized and
    finished, not refused as a rival."""

    def setUp(self) -> None:
        self.setup_queue_root()
        paths = q._ensure_dirs(self.root)
        self.staged = paths["processing"] / "interrupted1.json.requeue"
        self.payload = {"id": "interrupted1", "status": "pending", "type": "t", "payload": {"k": 1}}
        self.staged.write_text(json.dumps(self.payload), encoding="utf-8")
        self.dest = paths["pending"] / "interrupted1.json"
        link_patch = patch("worker.queue_ops.os.link", side_effect=OSError(errno.EPERM, "no links"))
        link_patch.start()
        self.addCleanup(link_patch.stop)

    def test_happy_path_no_dest_publishes_normally(self) -> None:
        """With no dest present, publish succeeds and staged is removed."""
        published = q._publish_no_clobber(self.staged, self.dest)

        self.assertTrue(published)
        self.assertFalse(self.staged.exists())
        self.assertEqual(_read(self.dest)["payload"], {"k": 1})

    def test_sad_path_own_interrupted_publish_is_recognized_and_finished(self) -> None:
        """dest already holds bytes identical to staged (a prior call
        published successfully and crashed before unlinking staged): this
        call must recognize its own publish, unlink staged, and report
        success -- not refuse it as a rival and strand staged forever.

        Pre-fix: FileExistsError from _copy_exclusive was always treated as
        a rival on the no-hardlink path (samefile() is unavailable without
        hard links), so a second recovery pass over the same staged file
        returned False every time, and once dest was later consumed by a
        worker, a THIRD pass would see dest gone and republish the stale
        staged copy -- duplicating the job.
        """
        # Simulate a prior call's _copy_exclusive having already succeeded:
        # dest holds the exact bytes staged would produce, but staged itself
        # was never unlinked (the crash landed between the two).
        self.dest.write_bytes(self.staged.read_bytes())

        published = q._publish_no_clobber(self.staged, self.dest)

        self.assertTrue(published, "must recognize an identical dest as its own interrupted publish")
        self.assertFalse(self.staged.exists(), "staged must be unlinked once recognized as already published")
        self.assertEqual(_read(self.dest)["payload"], {"k": 1})

    def test_sad_path_genuine_rival_is_still_refused(self) -> None:
        """dest holds DIFFERENT content (a genuine rival's record, not our
        own): this must still be refused, and staged kept for recovery."""
        self.dest.write_text(
            json.dumps({"id": "interrupted1", "payload": {"theirs": True}}), encoding="utf-8"
        )

        with self.assertLogs("worker.queue_ops", "WARNING"):
            published = q._publish_no_clobber(self.staged, self.dest)

        self.assertFalse(published, "a genuinely different dest must still be refused")
        self.assertTrue(self.staged.exists(), "staged must be kept for recovery")
        self.assertEqual(_read(self.dest)["payload"], {"theirs": True}, "rival's record must be untouched")


if __name__ == "__main__":
    unittest.main()
