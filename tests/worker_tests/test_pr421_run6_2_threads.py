"""Regression tests for PR #421 run-6-2 review threads.

Three findings from the Copilot re-review after round 6:

Finding 1 (PRRT_kwDOQr1kjM6miGEl — same underlying bug, 3 call sites):
  requeue_processing() was called bare (no try/except) in three places in
  job_runtime.py — process_one's None-token branch, _start_batch's None-token
  branch, and _abandon_claim — so a queue I/O error there would propagate
  uncaught, crashing the caller and potentially leaving the job stranded in
  processing/.  Fixed by wrapping each call in try/except with a
  # nosec B110 comment and a log message that notes the job may remain
  stranded until manual/reaper recovery.

Finding 2 (PRRT_kwDOQr1kjM6mh-Xe):
  When drain_live_threads catches _TransitionLockTimeout, the processing/
  record is left untouched (no lock held).  With job_timeout=0 (the shipped
  launchd default), the stale-job reaper never reaps the record, and
  recover_staged_requeues ignores plain *.json files, so the job is silently
  stranded after a launchd SIGKILL.  Fixed by writing a zero-byte
  *.json.shutdown-timeout sentinel beside the processing/ record (no lock
  needed, since the marker never touches the record itself), and adding
  recover_shutdown_timeout_markers() to queue_ops that is called at startup
  alongside recover_staged_requeues().  The marker is cleaned up once the
  processing/ record is gone or successfully requeued.

Finding 3 (PRRT_kwDOQr1kjM6miGEu):
  The existing test_rival_created_between_exists_check_and_replace_is_overwritten
  test in test_queue_claim_ownership.py did not actually inject a rival in the
  window it described — it just called _copy_exclusive() with no contention and
  checked the trivially-true happy path.  The production code has a genuine
  limitation on no-hardlink filesystems: a rival created between dest.exists()
  and tmp.replace(dest) is silently overwritten (the post-replace content
  re-read matches our bytes, so _NoClobberRaceLost is not raised).  The fix adds
  a second dest.exists() check immediately before the replace, narrowing the
  window to the replace call itself.  A rival created between the second check
  and the replace is still undetectable on standard POSIX (no renameat2
  RENAME_NOREPLACE in the stdlib), and is documented as a residual known
  limitation; the test confirms this behavior explicitly.
"""

from __future__ import annotations

import errno
import json
import threading
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


def _fake_claim(proc: Path, token: str) -> Any:
    """Stand-in for ``start_processing``: move the pending record to ``proc``.

    Planting ``proc`` before ``tick()`` instead would leave a pending/ and a
    processing/ record with the same id, which the claim loop skips as a
    duplicate of a running job, so the mocked claim would never be reached.
    """

    def _claim(job_path: Path, root: Path | None = None) -> tuple[Path, str]:
        record = _read(job_path)
        if token:
            record["claim_token"] = token
        proc.parent.mkdir(parents=True, exist_ok=True)
        proc.write_text(json.dumps(record), encoding="utf-8")
        job_path.unlink()
        return proc, token

    return _claim


class _RuntimeTestBase(unittest.TestCase, QueueRootIsolationMixin):
    """Temp queue root, every job_runtime queue call redirected to it."""

    def setUp(self) -> None:
        self.setup_queue_root()
        self.stack = _patch_queue_root(self.root)
        self.addCleanup(self.stack.close)
        self._threads_before = set(threading.enumerate())
        self.addCleanup(self._join_new_threads)

    def _join_new_threads(self) -> None:
        for t in threading.enumerate():
            if t not in self._threads_before and t.ident is not None:
                t.join(timeout=10)

    def _handlers(self, mapping: dict) -> None:
        self.stack.enter_context(patch.dict("worker.job_runtime.HANDLERS", mapping))


# ---------------------------------------------------------------------------
# Finding 1 — requeue_processing() call sites lack try/except
# ---------------------------------------------------------------------------


class TestProcessOneRequeueIOError(_RuntimeTestBase):
    """process_one: a queue I/O error from requeue_processing must not propagate."""

    def test_io_error_from_requeue_is_caught_and_logged(self) -> None:
        """Happy/sad: process_one returns 0 and logs, does NOT re-raise."""
        enqueue(Job(id="io1", type="noop", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=1)
        # Simulate start_processing returning a tuple with an empty token
        # (metadata write failed), then make requeue_processing raise.
        fake_proc = self.root / "processing" / "io1.json"
        fake_proc.parent.mkdir(parents=True, exist_ok=True)
        fake_proc.write_text(json.dumps({"id": "io1"}), encoding="utf-8")

        with (
            patch.object(q, "start_processing", return_value=(fake_proc, "")),
            patch.object(q, "requeue_processing", side_effect=OSError("disk full")),
            self.assertLogs("worker.job_runtime", "ERROR"),
        ):
            result = runner.processor.process_one(
                self.root / "pending" / "io1.json",
                {"id": "io1", "type": "noop", "payload": {}},
            )
        # Returns 0 (skipped), does not raise
        self.assertEqual(result, 0)

    def test_requeue_succeeds_normal_path_unaffected(self) -> None:
        """Happy path: process_one still skips without error when start_processing
        returns empty token and requeue_processing succeeds."""
        enqueue(Job(id="io2", type="noop", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=1)
        fake_proc = self.root / "processing" / "io2.json"
        fake_proc.parent.mkdir(parents=True, exist_ok=True)
        fake_proc.write_text(json.dumps({"id": "io2"}), encoding="utf-8")

        with (
            patch.object(q, "start_processing", return_value=(fake_proc, "")),
            patch.object(q, "requeue_processing", return_value=None),
        ):
            result = runner.processor.process_one(
                self.root / "pending" / "io2.json",
                {"id": "io2", "type": "noop", "payload": {}},
            )
        self.assertEqual(result, 0)


class TestStartBatchTokenlessRequeueIOError(_RuntimeTestBase):
    """_start_batch's None-token branch: queue I/O error from requeue_processing
    must not propagate out of tick()."""

    def test_io_error_from_requeue_is_caught_and_logged(self) -> None:
        enqueue(Job(id="sb1", type="noop", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=1)
        fake_proc = self.root / "processing" / "sb1.json"

        with (
            patch.object(q, "start_processing", side_effect=_fake_claim(fake_proc, "")),
            patch.object(q, "requeue_processing", side_effect=OSError("disk full")),
            self.assertLogs("worker.job_runtime", "ERROR"),
        ):
            # tick() calls _start_batch; must not raise even when requeue fails
            result = runner.tick()
        # 0 jobs started (claim was lost, loop broke)
        self.assertEqual(result, 0)

    def test_tokenless_claim_breaks_loop_and_requeues_normally(self) -> None:
        """Happy path: empty token causes break and requeue without error."""
        enqueue(Job(id="sb2", type="noop", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=1)
        fake_proc = self.root / "processing" / "sb2.json"

        with (
            patch.object(q, "start_processing", side_effect=_fake_claim(fake_proc, "")),
            patch.object(q, "requeue_processing", return_value=None),
            self.assertLogs("worker.job_runtime", "WARNING"),
        ):
            result = runner.tick()
        self.assertEqual(result, 0)


class TestAbandonClaimRequeueIOError(_RuntimeTestBase):
    """_abandon_claim: queue I/O error from requeue_processing must not propagate."""

    def test_io_error_from_requeue_is_caught_and_logged(self) -> None:
        enqueue(Job(id="ac1", type="noop", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=1)

        # Make start_processing succeed with a real token
        fake_proc = self.root / "processing" / "ac1.json"
        token = "8eff29a31dc1faa7f1fb93d57908faa8"  # nosec B105 - fake claim token, not a secret

        import threading as _threading

        with (
            patch.object(q, "start_processing", side_effect=_fake_claim(fake_proc, token)),
            patch.object(_threading.Thread, "start", side_effect=RuntimeError("thread fail")),
            patch.object(q, "requeue_processing", side_effect=OSError("disk full")),
            self.assertLogs("worker.job_runtime", "ERROR"),
        ):
            result = runner.tick()
        # 0 started (thread.start() failed and _abandon_claim was called)
        self.assertEqual(result, 0)
        # The entry is kept so the next prune retries the requeue rather than
        # leaving the claim in processing/ with nothing tracking it.
        self.assertIn("ac1", runner._live_threads)

        # The fake claim moved the pending/ copy, so the retry publishes the
        # processing/ record.
        runner._prune_live_threads()
        self.assertNotIn("ac1", runner._live_threads)
        self.assertEqual(sorted(p.name for p in (self.root / "pending").iterdir()), ["ac1.json"])
        self.assertFalse(fake_proc.exists())

    def test_abandon_claim_requeue_succeeds_normal_path(self) -> None:
        """Happy path: thread start failure triggers _abandon_claim successfully."""
        enqueue(Job(id="ac2", type="noop", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=1)

        fake_proc = self.root / "processing" / "ac2.json"
        token = "f11c903fff6ddba6fa0a0452143bf001"  # nosec B105 - fake claim token, not a secret

        import threading as _threading

        with (
            patch.object(q, "start_processing", side_effect=_fake_claim(fake_proc, token)),
            patch.object(_threading.Thread, "start", side_effect=RuntimeError("thread fail")),
            patch.object(q, "requeue_processing", return_value=None),
            self.assertLogs("worker.job_runtime", "ERROR"),
        ):
            result = runner.tick()
        self.assertEqual(result, 0)
        self.assertNotIn("ac2", runner._live_threads)


# ---------------------------------------------------------------------------
# Finding 2 — shutdown-timeout marker written and recovered
# ---------------------------------------------------------------------------


class TestShutdownTimeoutMarkerWritten(_RuntimeTestBase):
    """drain_live_threads writes a *.json.shutdown-timeout sentinel when
    _TransitionLockTimeout is raised for a job."""

    def test_marker_written_on_lock_timeout(self) -> None:
        """Sad path: _TransitionLockTimeout causes a marker to be written beside
        the processing/ record."""
        from worker.queue_ops import _TransitionLockTimeout

        enqueue(Job(id="st1", type="noop", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=1)
        # Manually plant a processing/ record to simulate an in-flight job
        paths = q._ensure_dirs(self.root)
        proc = paths["processing"] / "st1.json"
        proc.write_text(json.dumps({"id": "st1", "claim_token": "c89b8fb8c4dd560f722a0020452041f9"}), encoding="utf-8")
        # Register a fake dead thread so drain_live_threads iterates over it
        dead_thread = threading.Thread(target=lambda: None, daemon=True)
        dead_thread.start()
        dead_thread.join()
        runner._live_threads["st1"] = (dead_thread, "c89b8fb8c4dd560f722a0020452041f9")

        with (
            patch.object(q, "requeue_processing", side_effect=_TransitionLockTimeout("timed out")),
            self.assertLogs("worker.job_runtime", "ERROR"),
        ):
            runner.drain_live_threads(grace=0.0)

        marker = paths["processing"] / "st1.json.shutdown-timeout.c89b8fb8c4dd560f722a0020452041f9"
        self.assertTrue(marker.exists(), "shutdown-timeout marker was not written")

    def test_no_marker_on_successful_requeue(self) -> None:
        """Happy path: a requeue_processing call that returns without raising
        (whether it requeued the job or found nothing left to do) leaves no
        marker behind -- even past the deadline, where a marker is written
        proactively before the call, it is removed again once the call
        returns normally."""
        enqueue(Job(id="st2", type="noop", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=1)
        paths = q._ensure_dirs(self.root)
        proc = paths["processing"] / "st2.json"
        proc.write_text(json.dumps({"id": "st2", "claim_token": "1b976f14465708e1a58a9272cceb5767"}), encoding="utf-8")
        dead_thread = threading.Thread(target=lambda: None, daemon=True)
        dead_thread.start()
        dead_thread.join()
        runner._live_threads["st2"] = (dead_thread, "1b976f14465708e1a58a9272cceb5767")

        with patch.object(q, "requeue_processing", return_value=None):
            runner.drain_live_threads(grace=0.0)

        # No marker of any kind (successful requeue attempt, even one that
        # returned None because the job already left processing/, writes none).
        markers = list(paths["processing"].glob("st2.json.shutdown-timeout*"))
        self.assertEqual(markers, [], "marker should not exist on clean drain")

    def test_marker_written_proactively_before_past_deadline_call(self) -> None:
        """Sad path: once the shared deadline has passed, the marker is
        written BEFORE requeue_processing is even called (not only after a
        failure), so recovery intent is durable even if the call itself
        hangs indefinitely on a stalled filesystem and the process is later
        SIGKILLed before the call returns."""
        enqueue(Job(id="st8", type="noop", payload={}), root=self.root)
        runner = _make_runner(self.root, max_per_tick=1)
        paths = q._ensure_dirs(self.root)
        proc = paths["processing"] / "st8.json"
        proc.write_text(json.dumps({"id": "st8", "claim_token": "5071f176e4b4ca7f9f82103860727de4"}), encoding="utf-8")
        dead_thread = threading.Thread(target=lambda: None, daemon=True)
        dead_thread.start()
        dead_thread.join()
        runner._live_threads["st8"] = (dead_thread, "5071f176e4b4ca7f9f82103860727de4")

        marker = paths["processing"] / "st8.json.shutdown-timeout.5071f176e4b4ca7f9f82103860727de4"
        seen_during_call = []

        def _check_marker_exists(*_a: object, **_kw: object) -> None:
            # Called from inside requeue_processing's mock, simulating a
            # call that is still "in flight": the marker must already exist
            # at this point, before the (simulated) filesystem work completes.
            seen_during_call.append(marker.exists())
            return None

        with patch.object(q, "requeue_processing", side_effect=_check_marker_exists):
            runner.drain_live_threads(grace=0.0)

        self.assertEqual(seen_during_call, [True], "marker must exist before the call, not only after it fails")
        # The call returned normally (no exception), so the now-unneeded
        # marker was removed afterward.
        self.assertFalse(marker.exists(), "marker should be removed after a normal return")


class TestRecoverShutdownTimeoutMarkers(unittest.TestCase, QueueRootIsolationMixin):
    """recover_shutdown_timeout_markers requeues stranded jobs on startup."""

    def setUp(self) -> None:
        self.setup_queue_root()

    def test_requeues_processing_job_with_marker(self) -> None:
        """Sad path: processing/ record with a marker is moved back to pending/
        when the marker's encoded token still matches the record."""
        paths = q._ensure_dirs(self.root)
        # Plant a job in processing/ with a marker recording its claim token.
        proc = paths["processing"] / "st3.json"
        proc.write_text(
            json.dumps(
                {"id": "st3", "type": "noop", "payload": {}, "status": "processing",
                 "claim_token": "157da89b190077d5db54e8dc14c8e031"}
            ),
            encoding="utf-8",
        )
        marker = paths["processing"] / "st3.json.shutdown-timeout.157da89b190077d5db54e8dc14c8e031"
        marker.touch()

        recovered = q.recover_shutdown_timeout_markers(root=self.root)
        self.assertIn("st3", recovered)
        self.assertTrue((paths["pending"] / "st3.json").exists(), "job not moved to pending/")
        self.assertFalse(proc.exists(), "processing/ record should be gone")
        self.assertFalse(marker.exists(), "marker should be cleaned up")

    def test_requeues_tokenless_job_with_tokenless_marker(self) -> None:
        """Sad path: a marker recorded with no token (drain's own claim had none)
        still recovers a record that also still carries no token."""
        paths = q._ensure_dirs(self.root)
        proc = paths["processing"] / "st3b.json"
        proc.write_text(
            json.dumps({"id": "st3b", "type": "noop", "payload": {}, "status": "processing"}),
            encoding="utf-8",
        )
        marker = paths["processing"] / "st3b.json.shutdown-timeout."
        marker.touch()

        recovered = q.recover_shutdown_timeout_markers(root=self.root)
        self.assertIn("st3b", recovered)
        self.assertTrue((paths["pending"] / "st3b.json").exists())
        self.assertFalse(marker.exists())

    def test_does_not_steal_claim_reclaimed_by_another_worker(self) -> None:
        """Sad path: if another worker's own reaper has since reclaimed this
        stem with a different token, recovery must not requeue that worker's
        live claim -- the ownership check refuses it, and the stale marker is
        still cleaned up rather than retried forever."""
        paths = q._ensure_dirs(self.root)
        proc = paths["processing"] / "st3c.json"
        proc.write_text(
            json.dumps(
                {"id": "st3c", "type": "noop", "payload": {}, "status": "processing",
                 "claim_token": "d1fdda4c2518ec248d59b4e542d3edf5"}
            ),
            encoding="utf-8",
        )
        # The marker was written under the OLD (now-superseded) token.
        marker = paths["processing"] / "st3c.json.shutdown-timeout.ced0137178f383017fec9f15dfbb0b7a"
        marker.touch()

        recovered = q.recover_shutdown_timeout_markers(root=self.root)
        self.assertNotIn("st3c", recovered, "must not steal another worker's live claim")
        self.assertTrue(proc.exists(), "the new owner's processing/ record must survive untouched")
        self.assertEqual(_read(proc)["claim_token"], "d1fdda4c2518ec248d59b4e542d3edf5")
        self.assertFalse(marker.exists(), "stale marker should still be cleaned up")

    def test_cleans_up_stale_marker_when_job_already_gone(self) -> None:
        """Happy path: marker without a corresponding processing/ record is removed."""
        paths = q._ensure_dirs(self.root)
        marker = paths["processing"] / "st4.json.shutdown-timeout.ea0e975045c49f559a6467097867f82a"
        marker.touch()

        recovered = q.recover_shutdown_timeout_markers(root=self.root)
        self.assertNotIn("st4", recovered)
        self.assertFalse(marker.exists(), "stale marker should be cleaned up")

    def test_no_double_requeue_when_already_pending(self) -> None:
        """Happy path: if the job is already in pending/ (queued by another path),
        the marker is cleaned up without duplicating the pending record."""
        paths = q._ensure_dirs(self.root)
        # The job was already moved to pending/ (e.g. by recover_staged_requeues)
        pending = paths["pending"] / "st5.json"
        pending.write_text(
            json.dumps({"id": "st5", "type": "noop", "payload": {}, "status": "pending"}),
            encoding="utf-8",
        )
        # No processing/ record — marker is stale
        marker = paths["processing"] / "st5.json.shutdown-timeout.bc06d793159b29fd1cb06eb0afe1daa7"
        marker.touch()

        recovered = q.recover_shutdown_timeout_markers(root=self.root)
        self.assertNotIn("st5", recovered)
        # pending/ copy is intact and unchanged
        self.assertTrue(pending.exists())
        self.assertFalse(marker.exists(), "stale marker should be cleaned up")

    def test_marker_left_on_requeue_failure(self) -> None:
        """Sad path: if requeue_processing raises, marker stays for next startup."""
        paths = q._ensure_dirs(self.root)
        proc = paths["processing"] / "st6.json"
        proc.write_text(
            json.dumps(
                {"id": "st6", "type": "noop", "payload": {}, "status": "processing",
                 "claim_token": "d25840337eeea75771588cc1dd5484c9"}
            ),
            encoding="utf-8",
        )
        marker = paths["processing"] / "st6.json.shutdown-timeout.d25840337eeea75771588cc1dd5484c9"
        marker.touch()

        with (
            patch.object(q, "requeue_processing", side_effect=OSError("disk full")),
            self.assertLogs("worker.queue_ops", "WARNING"),
        ):
            recovered = q.recover_shutdown_timeout_markers(root=self.root)

        self.assertNotIn("st6", recovered)
        # marker preserved for next startup
        self.assertTrue(marker.exists(), "marker should stay on failed requeue")

    def test_run_once_calls_recover_shutdown_timeout_markers(self) -> None:
        """Happy path: run_once calls recover_shutdown_timeout_markers at startup."""
        paths = q._ensure_dirs(self.root)
        proc = paths["processing"] / "st7.json"
        proc.write_text(
            json.dumps(
                {"id": "st7", "type": "noop", "payload": {}, "status": "processing",
                 "claim_token": "b2f5ce4c0127de9b40f0e9e73d400d90"}
            ),
            encoding="utf-8",
        )
        marker = paths["processing"] / "st7.json.shutdown-timeout.b2f5ce4c0127de9b40f0e9e73d400d90"
        marker.touch()

        runner = _make_runner(self.root, max_per_tick=1)
        stack = _patch_queue_root(self.root)
        with stack:
            runner.run_once()

        # After run_once, the marker should be gone and the job requeued
        self.assertFalse(marker.exists(), "marker should be cleaned up by run_once")


class TestWriteShutdownTimeoutMarker(unittest.TestCase, QueueRootIsolationMixin):
    """write_shutdown_timeout_marker creates the expected file."""

    def setUp(self) -> None:
        self.setup_queue_root()

    def test_creates_marker_file(self) -> None:
        paths = q._ensure_dirs(self.root)
        q.write_shutdown_timeout_marker("m1", "adc18b3458d2e630c942e2f2b1f1e046", root=self.root)
        marker = paths["processing"] / "m1.json.shutdown-timeout.adc18b3458d2e630c942e2f2b1f1e046"
        self.assertTrue(marker.exists())

    def test_creates_marker_file_with_no_token(self) -> None:
        """None is encoded as an empty trailing segment, distinguishable from
        any real hex token (which is never empty)."""
        paths = q._ensure_dirs(self.root)
        q.write_shutdown_timeout_marker("m1b", None, root=self.root)
        marker = paths["processing"] / "m1b.json.shutdown-timeout."
        self.assertTrue(marker.exists())

    def test_idempotent(self) -> None:
        """touch() is idempotent; writing twice does not raise."""
        q.write_shutdown_timeout_marker("m2", "be104824eccd93d21fe73175f39589c8", root=self.root)
        q.write_shutdown_timeout_marker("m2", "be104824eccd93d21fe73175f39589c8", root=self.root)
        paths = q._ensure_dirs(self.root)
        self.assertTrue((paths["processing"] / "m2.json.shutdown-timeout.be104824eccd93d21fe73175f39589c8").exists())


class TestRemoveShutdownTimeoutMarker(unittest.TestCase, QueueRootIsolationMixin):
    """remove_shutdown_timeout_marker deletes the marker written for a job."""

    def setUp(self) -> None:
        self.setup_queue_root()

    def test_removes_existing_marker(self) -> None:
        paths = q._ensure_dirs(self.root)
        q.write_shutdown_timeout_marker("rm1", "09ab9726e74e760ca184c4539fe37191", root=self.root)
        marker = paths["processing"] / "rm1.json.shutdown-timeout.09ab9726e74e760ca184c4539fe37191"
        self.assertTrue(marker.exists())
        q.remove_shutdown_timeout_marker("rm1", "09ab9726e74e760ca184c4539fe37191", root=self.root)
        self.assertFalse(marker.exists())

    def test_missing_marker_is_a_noop(self) -> None:
        """Removing a marker that was never written (or already removed)
        does not raise."""
        q.remove_shutdown_timeout_marker("rm2", "73995df32dfc9d471e1285d3a0fd7026", root=self.root)  # must not raise


class TestRecoverShutdownTimeoutMarkersParsesJobIdWithEmbeddedSuffix(
    unittest.TestCase, QueueRootIsolationMixin
):
    """recover_shutdown_timeout_markers must parse the marker filename
    correctly even when the job id itself contains the literal marker
    suffix text: the parse is anchored at the end of the name, so only the
    final occurrence is the true boundary."""

    def setUp(self) -> None:
        self.setup_queue_root()

    def test_job_id_containing_marker_suffix_text_is_parsed_correctly(self) -> None:
        """A job id such as 'a.json.shutdown-timeout.b' must not be
        mis-parsed as job id 'a' with token 'b.json.shutdown-timeout.<tok>' --
        the real marker filename appends the true suffix again at the end,
        and only the LAST occurrence is the genuine boundary."""
        paths = q._ensure_dirs(self.root)
        tricky_id = "a.json.shutdown-timeout.b"
        proc = paths["processing"] / f"{tricky_id}.json"
        proc.write_text(
            json.dumps(
                {"id": tricky_id, "type": "noop", "payload": {}, "status": "processing",
                 "claim_token": "960c2822cae41d21c036af8b8f5b21b4"}
            ),
            encoding="utf-8",
        )
        q.write_shutdown_timeout_marker(tricky_id, "960c2822cae41d21c036af8b8f5b21b4", root=self.root)

        recovered = q.recover_shutdown_timeout_markers(root=self.root)

        self.assertIn(tricky_id, recovered, "the full tricky job id must be recovered intact")
        self.assertTrue(
            (paths["pending"] / f"{tricky_id}.json").exists(),
            "the job with the embedded-suffix id must be requeued, not stranded",
        )
        self.assertFalse(proc.exists())

    def test_job_record_itself_is_never_mistaken_for_a_marker(self) -> None:
        """The plain job record file for a tricky id (e.g.
        'a.json.shutdown-timeout.b.json' on disk) must never itself be
        parsed as a marker, regardless of directory iteration order.

        Before the fix, ``recover_shutdown_timeout_markers`` iterated every
        file in processing/ and treated any whose name contained
        ``marker_suffix`` as a marker with no check that it was actually one
        (as opposed to a job record that happens to contain that literal
        text). For this tricky id, the job record's OWN filename
        ('a.json.shutdown-timeout.b.json') itself matches via rfind --
        parsed as bogus job id 'a' with bogus token 'b.json' -- and got
        processed as if it were a marker for a job that never existed. This
        this order-dependent bug did not reproduce locally (this test's
        sibling passed on macOS) but failed on CI's Linux runner, where
        directory iteration order let the bogus parse run before the real
        marker's. Testing the fix directly, independent of iteration order:
        with NO real marker file present at all, a lone job record whose
        name embeds the marker suffix text must not be requeued or removed.
        """
        paths = q._ensure_dirs(self.root)
        tricky_id = "z.json.shutdown-timeout.q"
        proc = paths["processing"] / f"{tricky_id}.json"
        proc.write_text(
            json.dumps(
                {"id": tricky_id, "type": "noop", "payload": {}, "status": "processing",
                 "claim_token": "1c3e7a28533a07d1d3efce37c3d23469"}
            ),
            encoding="utf-8",
        )
        # Deliberately no write_shutdown_timeout_marker call: only the job
        # record itself is on disk, so any requeue at all proves the record
        # was wrongly treated as a marker.

        recovered = q.recover_shutdown_timeout_markers(root=self.root)

        self.assertEqual(recovered, [], "no marker exists; nothing should be recovered")
        self.assertTrue(proc.exists(), "the job record must be left untouched in processing/")
        self.assertFalse(
            (paths["pending"] / f"{tricky_id}.json").exists(),
            "the job record must not be requeued just because its name embeds marker_suffix",
        )


# ---------------------------------------------------------------------------
# Finding 3 — _copy_exclusive rival-in-window race
# ---------------------------------------------------------------------------


class TestCopyExclusiveRivalInWindow(unittest.TestCase, QueueRootIsolationMixin):
    """The no-clobber fallback in _copy_exclusive on no-hardlink filesystems.

    The hard-link path is disabled by patching os.link to raise OSError(EPERM),
    forcing the check-then-replace fallback.
    """

    rival_content = json.dumps({"id": "p1", "payload": {"theirs": True}}).encode()
    our_content = json.dumps({"id": "p1", "payload": {"mine": True}}).encode()

    def setUp(self) -> None:
        self.setup_queue_root()
        paths = q._ensure_dirs(self.root)
        self.staged = paths["processing"] / "p1.json.requeue"
        self.staged.write_bytes(self.our_content)
        self.dest = paths["pending"] / "p1.json"

    def _no_hardlinks(self):
        """Context manager that disables hard links for _copy_exclusive."""
        return patch("worker.queue_ops.os.link", side_effect=OSError(errno.EPERM, "no links"))

    def test_rival_before_first_check_is_refused(self) -> None:
        """A rival already present when dest.exists() first runs causes
        FileExistsError and the staged file is kept intact."""
        self.dest.write_bytes(self.rival_content)
        with self._no_hardlinks():
            with self.assertRaises(FileExistsError):
                q._copy_exclusive(self.staged, self.dest)
        self.assertEqual(self.dest.read_bytes(), self.rival_content, "rival bytes must survive")
        self.assertTrue(self.staged.exists(), "staged file must be kept")

    def test_rival_created_between_second_check_and_replace_is_overwritten(self) -> None:
        """Known POSIX limitation: a rival created in the residual window between
        the second dest.exists() check and tmp.replace(dest) is overwritten
        without raising _NoClobberRaceLost.  There is no renameat2(RENAME_NOREPLACE)
        in the Python stdlib, so this narrow window cannot be closed atomically.
        This test documents the actual behavior rather than asserting it is safe.
        """
        # Intercept at the second existence check. The first check returns False
        # (dest doesn't exist), the rival is then created, the second check is
        # also forced to return False (simulating the race window), and then
        # tmp.replace(dest) overwrites the rival.
        exists_calls: list[bool] = []
        original_exists = Path.exists

        def patched_exists(self_path: Path) -> bool:
            if self_path == self.dest:
                result = original_exists(self_path)
                exists_calls.append(result)
                if len(exists_calls) == 2:
                    # Second check: create rival as side effect to simulate the
                    # race, but still return False to let the replace proceed.
                    self.dest.write_bytes(self.rival_content)
                    return False
                return result
            return original_exists(self_path)

        with (
            self._no_hardlinks(),
            patch.object(Path, "exists", patched_exists),
        ):
            # No exception is raised — this is the known limitation.
            q._copy_exclusive(self.staged, self.dest)

        # Our bytes won (we replaced the rival).
        self.assertEqual(self.dest.read_bytes(), self.our_content)

    def test_rival_created_between_first_and_second_check_is_caught(self) -> None:
        """The second dest.exists() check added in this fix catches rivals created
        between the first check and the second: FileExistsError is raised and the
        rival's record survives."""
        exists_calls: list[int] = []
        original_exists = Path.exists

        def patched_exists(self_path: Path) -> bool:
            if self_path == self.dest:
                exists_calls.append(1)
                if len(exists_calls) == 1:
                    # First check: no rival yet; return False
                    return False
                # Second check: create the rival first, then let the real
                # check find it.
                if len(exists_calls) == 2:
                    self.dest.write_bytes(self.rival_content)
                return original_exists(self_path)
            return original_exists(self_path)

        with (
            self._no_hardlinks(),
            patch.object(Path, "exists", patched_exists),
        ):
            with self.assertRaises(FileExistsError):
                q._copy_exclusive(self.staged, self.dest)

        # Rival bytes are intact
        self.assertEqual(self.dest.read_bytes(), self.rival_content)
        # Staged file preserved for recovery
        self.assertTrue(self.staged.exists())

    def test_publish_no_clobber_with_no_rival_succeeds(self) -> None:
        """Happy path: publish succeeds and staged is removed when dest is free."""
        with self._no_hardlinks():
            result = q._publish_no_clobber(self.staged, self.dest)
        self.assertTrue(result)
        self.assertEqual(self.dest.read_bytes(), self.our_content)
        self.assertFalse(self.staged.exists())

    def test_later_rival_overwrites_us_raises_no_clobber_race_lost(self) -> None:
        """The post-replace re-read catches a rival that overwrites US after we
        published: _NoClobberRaceLost is raised."""
        original_replace = Path.replace

        def patched_replace(self_path: Path, target: Path) -> Any:
            result = original_replace(self_path, target)
            # After our replace, simulate a rival writing different bytes to dest
            target.write_bytes(self.rival_content)
            return result

        with (
            self._no_hardlinks(),
            patch.object(Path, "replace", patched_replace),
        ):
            with self.assertRaises(q._NoClobberRaceLost):
                q._copy_exclusive(self.staged, self.dest)


if __name__ == "__main__":
    unittest.main()
