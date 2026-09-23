"""Regression tests for PR #421 review threads.

Pre-fix behavior (on 112a0223 before each fix is applied):
- Thread 1: drain_live_threads races with start_processing in the worker
  thread; requeue_processing returns None and the job is not requeued.
  The thread runs the job to completion even after a grace=0 shutdown.
- Thread 2: recover_staged_requeues does not exist (AttributeError/ImportError).
- Thread 3: nan and +inf pass the ``< 0`` check and reach WorkerConfig.

Post-fix:
- Thread 1: process_one checks stop_event immediately after claiming the job;
  if shutdown is requested it requeues the job and returns without running.
  This closes the race whether stop_event was set before or after the claim.
- Thread 2: recover_staged_requeues moves *.json.requeue files to pending/.
- Thread 3: math.isfinite check rejects nan, +inf, and -inf.
"""

from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.worker_tests.helpers import QueueRootIsolationMixin
from tests.worker_tests.test_daemon_nonblocking import (
    _make_runner,
    _patch_queue_root,
)
from worker.queue_ops import (
    Job,
    enqueue,
)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Thread 1: shutdown/claim race
#
# Pre-fix (112a0223): process_one claims the job and then runs the handler,
# with no check of stop_event between the claim and the run.  When
# drain_live_threads fires before start_processing (the thread is registered
# but not yet claiming), requeue_processing finds no file and returns None.
# The thread then claims and runs the job — stranded in done/ instead of
# pending/ when the daemon was supposed to shut down.
#
# Post-fix: process_one checks stop_event AFTER start_processing succeeds.
# If the event is set it requeues the job and returns 0 without running.
# This closes both windows:
#   - drain ran before the claim → requeue_processing returned None, but the
#     worker's post-claim check requeues the job
#   - drain ran after the claim → requeue_processing already moved the file;
#     post-claim check's requeue_processing call returns None (no-op)
#
# The test makes the race deterministic by pre-setting stop_event before
# tick() and using a fast (non-blocking) handler.  On 112a0223 the handler
# runs and the job lands in done/; after the fix the worker short-circuits
# and the job lands in pending/.
# ---------------------------------------------------------------------------


def _cheap_handler(job_data: dict[str, object]) -> tuple[bool, object]:
    return True, "ok"


class TestShutdownClaimRace(unittest.TestCase, QueueRootIsolationMixin):
    """process_one requeues the job when stop_event is set after the claim.

    Pre-fix (112a0223): no post-claim stop_event check; handler runs.
    Post-fix: check in process_one; job lands in pending/ instead of done/.
    """

    def setUp(self) -> None:
        self.setup_queue_root()
        base = _patch_queue_root(self.root)
        base.enter_context(patch.dict("worker.job_runtime.HANDLERS", {"fast": _cheap_handler}))
        self.addCleanup(base.close)
        self.addCleanup(self._join_new_threads)
        self._threads_before = set(threading.enumerate())

    def _join_new_threads(self) -> None:
        for t in threading.enumerate():
            if t not in self._threads_before:
                t.join(timeout=5)

    def test_job_requeued_when_stop_event_set_before_tick(self) -> None:
        """stop_event set before tick() → process_one claims, checks, requeues.

        Pre-fix (112a0223): no stop-event check; handler runs; job lands in done/.
        Post-fix: process_one checks stop_event after claiming; job in pending/.

        The race is made deterministic by pre-setting stop_event so the worker
        always sees it set after claiming, regardless of scheduling.
        """
        runner = _make_runner(self.root, max_per_tick=1)
        enqueue(Job(id="race1", type="fast", payload={}, attempts=2), root=self.root)

        # Pre-set stop_event: the thread will see it set immediately after claiming.
        runner.stop_event.set()

        runner.tick()
        # Wait for the worker thread to finish.
        thread = runner._live_threads.get("race1")
        if thread is not None:
            thread.join(timeout=5)

        pending = self.root / "pending" / "race1.json"
        done = self.root / "done" / "race1.json"
        # Pre-fix: done exists, pending does not (handler ran to completion).
        # Post-fix: pending exists, done does not (thread requeued instead of running).
        self.assertTrue(pending.exists(), "job must be in pending/ after stop-event requeue")
        self.assertFalse(done.exists(), "job must NOT be in done/ — handler must not have run")
        data = _read(pending)
        self.assertEqual(data["attempts"], 2, "attempts must not be incremented by requeue")


# ---------------------------------------------------------------------------
# Thread 2: staged-requeue recovery
# ---------------------------------------------------------------------------


class TestStagedRequeueRecovery(unittest.TestCase, QueueRootIsolationMixin):
    """*.json.requeue files stranded by a crash are recovered to pending/."""

    def setUp(self) -> None:
        self.setup_queue_root()

    def _processing_dir(self) -> Path:
        d = self.root / "processing"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _plant_staged(self, job_id: str, data: dict[str, Any]) -> Path:
        """Write a *.json.requeue file directly into processing/."""
        staged = self._processing_dir() / f"{job_id}.json.requeue"
        staged.write_text(json.dumps(data), encoding="utf-8")
        return staged

    def test_staged_requeue_is_moved_to_pending(self) -> None:
        """A *.json.requeue file in processing/ is completed to pending/ on recovery.

        On 112a0223 there is no recover_staged_requeues function, so the file
        stays invisible forever.  After the fix it appears in pending/.
        """
        from worker.queue_ops import recover_staged_requeues  # type: ignore[attr-defined]

        data = {"id": "stranded1", "type": "slow", "status": "pending", "attempts": 2}
        staged = self._plant_staged("stranded1", data)
        self.assertTrue(staged.exists(), "precondition: staged file planted")

        moved = recover_staged_requeues(root=self.root)

        self.assertEqual(moved, ["stranded1"])
        self.assertFalse(staged.exists(), "staged file should be gone")
        pending = self.root / "pending" / "stranded1.json"
        self.assertTrue(pending.exists(), "job must land in pending/")
        recovered = _read(pending)
        self.assertEqual(recovered["attempts"], 2)

    def test_staged_requeue_recovery_is_idempotent(self) -> None:
        """Running recovery twice on the same file produces exactly one pending/ copy."""
        from worker.queue_ops import recover_staged_requeues  # type: ignore[attr-defined]

        data = {"id": "idem1", "type": "slow", "status": "pending", "attempts": 0}
        self._plant_staged("idem1", data)

        first = recover_staged_requeues(root=self.root)
        second = recover_staged_requeues(root=self.root)

        self.assertEqual(first, ["idem1"])
        self.assertEqual(second, [], "second pass must be a no-op")
        self.assertTrue((self.root / "pending" / "idem1.json").exists())

    def test_no_staged_files_returns_empty(self) -> None:
        """Recovery on a clean queue returns an empty list."""
        from worker.queue_ops import recover_staged_requeues  # type: ignore[attr-defined]

        enqueue(Job(id="normal1", type="slow", payload={}), root=self.root)
        result = recover_staged_requeues(root=self.root)
        self.assertEqual(result, [])
        # Normal pending job is untouched
        self.assertTrue((self.root / "pending" / "normal1.json").exists())


# ---------------------------------------------------------------------------
# Thread 3: non-finite --shutdown-grace
# ---------------------------------------------------------------------------


class TestShutdownGraceNonFinite(unittest.TestCase):
    """nan and +inf are rejected by --shutdown-grace.

    argparse converts "--shutdown-grace nan" to float("nan") before handing it
    to _parse_shutdown_grace; the same for "inf".  "-inf" starts with "-" so
    argparse treats it as an option flag and errors before our validation runs;
    it is covered by a direct unit test of _parse_shutdown_grace instead.

    Pre-fix (112a0223): only ``< 0`` is checked, so nan and inf both pass.
    Post-fix: ``not math.isfinite(value)`` catches both.
    """

    def _exit_code(self, argv: list[str]) -> int:
        from worker.cli import main

        with patch("worker.cli.DaemonRunner") as runner_cls, \
             patch("worker.cli.JobProcessor"), \
             patch("sys.stderr"):
            runner_cls.return_value.run_daemon.return_value = 0
            return main(argv)

    def test_nan_is_rejected(self) -> None:
        """--shutdown-grace nan must produce a non-zero exit code.

        On 112a0223 _parse_shutdown_grace only checks < 0, so nan passes.
        """
        self.assertNotEqual(self._exit_code(["daemon", "--shutdown-grace", "nan"]), 0)

    def test_positive_inf_is_rejected(self) -> None:
        """--shutdown-grace inf must produce a non-zero exit code.

        On 112a0223 _parse_shutdown_grace only checks < 0, so +inf passes.
        """
        self.assertNotEqual(self._exit_code(["daemon", "--shutdown-grace", "inf"]), 0)

    def test_negative_inf_rejected_by_parse_function(self) -> None:
        """-inf is rejected by _parse_shutdown_grace directly.

        argparse treats "-inf" as an option flag and errors before our code
        runs, so we test the parser function directly for this value.
        -inf satisfies ``< 0`` so it was already rejected pre-fix; this is a
        pass-on-both-old-and-new test that verifies the function never accepts
        -inf regardless of which check catches it.
        """
        import argparse
        from worker.cli import _parse_shutdown_grace
        from core.cli_errors import UsageError

        ns = argparse.Namespace(shutdown_grace=float("-inf"))
        with self.assertRaises(UsageError):
            _parse_shutdown_grace(ns)

    def test_zero_is_accepted(self) -> None:
        """grace=0 is valid (disable waiting; requeue immediately)."""
        self.assertEqual(self._exit_code(["daemon", "--shutdown-grace", "0"]), 0)

    def test_positive_finite_is_accepted(self) -> None:
        self.assertEqual(self._exit_code(["daemon", "--shutdown-grace", "5.5"]), 0)


# ---------------------------------------------------------------------------
# Resource-warning guard (file-handle leak in commands.py)
# ---------------------------------------------------------------------------


class TestNoResourceWarnings(unittest.TestCase, QueueRootIsolationMixin):
    """StatusCommand._load_completed_job_rows must not leak file handles.

    Pre-fix (before the ``with`` fix in commands.py): iterating over
    ``path.open("r", ...)`` without a context manager leaves the handle open
    until GC.  Under CPython that is usually immediate, but ResourceWarning
    is emitted before the finaliser runs; under PyPy / strict-GC environments
    the warning triggers every time.  The test simulates a readable log file
    and asserts that no ResourceWarning is raised.
    """

    def setUp(self) -> None:
        self.setup_queue_root()

    def test_load_completed_job_rows_no_resource_warning(self) -> None:
        """_load_completed_job_rows closes its file handle (no ResourceWarning).

        Pre-fix: ``for line in path.open(...)`` leaves the handle open;
        Python emits a ResourceWarning during GC.
        Post-fix: ``with path.open(...) as fh:`` closes it immediately.
        """
        import gc
        import warnings
        import json as _json
        import tempfile
        from pathlib import Path as _Path
        from worker.commands import StatusCommand

        # Write a minimal perf-log file with one matching record.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as tf:
            log_path = _Path(tf.name)
            tf.write(_json.dumps({"args": ["daemon", "run_cli", "ok"], "ts": "2026-01-01T00:00:00Z", "duration_ms": 10}) + "\n")
            tf.write(_json.dumps({"args": ["other"], "ts": "2026-01-01T00:00:01Z", "duration_ms": 5}) + "\n")

        self.addCleanup(log_path.unlink, missing_ok=True)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", ResourceWarning)
            rows = StatusCommand._load_completed_job_rows(log_path)
            gc.collect()

        resource_warnings = [x for x in w if issubclass(x.category, ResourceWarning)]
        self.assertEqual(
            resource_warnings, [],
            f"Unexpected ResourceWarning(s): {[str(x.message) for x in resource_warnings]}",
        )
        self.assertEqual(len(rows), 1, "should parse exactly one matching record")


# ---------------------------------------------------------------------------
# Real-queue contamination guard
# ---------------------------------------------------------------------------


class TestRealQueueUntouched(unittest.TestCase, QueueRootIsolationMixin):
    """Worker tests must never write to the user's real queue.

    The guard verifies that ``QueueRootIsolationMixin.setup_queue_root``
    redirects BOTH ``queue_ops.QUEUE_ROOT`` AND the
    ``DANCING_BEAR_WORKER_STATE_DIR`` environment variable so that any code
    path that resolves the state dir — whether from the already-imported
    constant or from a fresh ``get_worker_state_dir`` call — lands in the
    temp tree instead of the user's real queue.

    Pre-fix (before this PR): ``setup_queue_root`` only saved/restored
    ``QUEUE_ROOT`` but never set ``DANCING_BEAR_WORKER_STATE_DIR``, leaving
    a fresh call to ``get_worker_state_dir`` pointing at the real queue.
    Post-fix: both are redirected and the env var is restored on cleanup.
    """

    def setUp(self) -> None:
        self.setup_queue_root()

    def test_worker_state_dir_env_is_redirected_during_test(self) -> None:
        """DANCING_BEAR_WORKER_STATE_DIR must point at a temp tree during tests.

        Pre-fix: setup_queue_root never set the env var; a fresh call to
        get_worker_state_dir() returned the real ~/Library/… path.
        Post-fix: setup_queue_root sets the var to the temp root.
        """
        import os
        from worker._helpers import WORKER_STATE_DIR_ENV, get_worker_state_dir

        env_val = os.environ.get(WORKER_STATE_DIR_ENV, "")
        self.assertTrue(
            env_val,
            f"{WORKER_STATE_DIR_ENV} is not set — setup_queue_root must set it "
            "to prevent writes to the real queue.",
        )

        # get_worker_state_dir must resolve under our temp tree, not the real queue.
        # Use resolve() to canonicalize both paths so that macOS symlink
        # differences (/var → /private/var) do not cause a false failure.
        import pathlib
        resolved = get_worker_state_dir("queue").resolve()
        tmp_resolved = pathlib.Path(self.tmp.name).resolve()
        self.assertTrue(
            str(resolved).startswith(str(tmp_resolved)),
            f"get_worker_state_dir resolved to {resolved!r} which is NOT under "
            f"the temp tree {tmp_resolved!r}.  A no-root call would reach the real queue.",
        )

    def test_queue_root_module_var_is_redirected(self) -> None:
        """queue_ops.QUEUE_ROOT must point at the temp tree, not the real queue.

        Pre-fix: QUEUE_ROOT was left as-is between ``isolate_queue_root``
        saving it and the first explicit reassignment in _make_runner.
        Post-fix: setup_queue_root sets q.QUEUE_ROOT = self.root.
        """
        from worker import queue_ops as q

        self.assertEqual(
            q.QUEUE_ROOT,
            self.root,
            f"q.QUEUE_ROOT={q.QUEUE_ROOT!r} but expected temp root {self.root!r}.  "
            "setup_queue_root must update q.QUEUE_ROOT immediately.",
        )


if __name__ == "__main__":
    unittest.main()
