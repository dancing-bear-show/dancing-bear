"""Tests for the qwen model-call concurrency guard (contract.json:concurrency).

The lock protects the machine from running two model generations at once, so
it is tested at the level that matters: call_count on the transport mock, not
just the handler's return value. A test that only checks the return value
would pass even if the handler generated anyway and discarded the result —
the exact memory blowup the guard exists to prevent.

Stale-lock rule is the CONTRACT's, not a plain age check:
  dead holder PID                          -> STALE, reclaim
  alive holder, age <= stale_ceiling_sec    -> active, wait
  alive holder, age  > stale_ceiling_sec    -> SUSPECT, reclaim ONLY IF
      _pid_is_worker(pid) is False OR the lane is empty
All three branches are tested, including the "alive + non-empty lane is NOT
reclaimed" case that a naive age-only rule would get wrong.

worker.qwen does not exist in this worktree yet; ModuleNotFoundError here is
expected (see tests-impl.json).
"""

from __future__ import annotations

import contextlib
import json
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import TempDirMixin


def _job(payload: dict[str, object], **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "qwen-concurrency-job",
        "type": "qwen_patch",
        "attempts": 0,
        "max_attempts": 3,
        "payload": payload,
    }
    base.update(overrides)
    return base


_OLLAMA_RESPONSE = {
    "response": (
        "```diff\n"
        "diff --git a/README.md b/README.md\n"
        "index e69de29..4b825dc 100644\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1,2 @@\n"
        " existing line\n"
        "+added line\n"
        "```"
    ),
    "prompt_eval_count": 42,
    "eval_count": 7,
}


class QwenConcurrencyBaseTests(TempDirMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repo_root = Path(self.tmpdir) / "repo"
        (self.repo_root / "src").mkdir(parents=True)
        (self.repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        self.lock_path = Path(self.tmpdir) / "state" / "model.lock"

    def _common_patches(self):
        return [
            mock.patch("worker.qwen._repo_root", return_value=self.repo_root),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=self.lock_path),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
        ]


class QwenLockHeldTests(QwenConcurrencyBaseTests):
    def test_lock_already_held_returns_exact_deferred_busy_prefix(self) -> None:
        from worker import qwen

        job = _job({"files": ["src/README.md"], "instruction": "x"})

        with contextlib.ExitStack() as stack:
            for p in self._common_patches():
                stack.enter_context(p)
            stack.enter_context(mock.patch("worker.qwen._acquire_model_lock", return_value=False))
            mock_request = stack.enter_context(mock.patch("worker.qwen._ollama_request"))

            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertEqual(str(out), "deferred-qwen-busy")
        mock_request.assert_not_called()

    def test_model_not_called_while_lock_held(self) -> None:
        """A test that only checks the return value would miss the case
        where the handler generated anyway and discarded the result."""
        from worker import qwen

        job = _job({"files": ["src/README.md"], "instruction": "x"})

        with contextlib.ExitStack() as stack:
            for p in self._common_patches():
                stack.enter_context(p)
            stack.enter_context(mock.patch("worker.qwen._acquire_model_lock", return_value=False))
            mock_request = stack.enter_context(
                mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE))
            )

            qwen.handle_qwen_patch(job)

        self.assertEqual(mock_request.call_count, 0)


class QwenLockReleaseTests(QwenConcurrencyBaseTests):
    def test_lock_released_after_successful_job_allows_second_job_to_acquire(self) -> None:
        from worker import qwen

        job1 = _job({"files": ["src/README.md"], "instruction": "first"}, id="job-1")
        job2 = _job({"files": ["src/README.md"], "instruction": "second"}, id="job-2")

        with contextlib.ExitStack() as stack:
            for p in self._common_patches():
                stack.enter_context(p)
            stack.enter_context(
                mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE))
            )

            ok1, _ = qwen.handle_qwen_patch(job1)
            self.assertTrue(ok1)

            # A real, unpatched _acquire_model_lock must be able to acquire
            # again now that job1 released it. Do not mock the lock here —
            # this proves release, not merely that a mock says so.
            acquired = qwen._acquire_model_lock(job2["id"], wait_ceiling_sec=1)
            if acquired:
                qwen._release_model_lock(job2["id"])
            self.assertTrue(acquired, "lock was not released after a successful job")

    def test_lock_released_when_model_call_raises(self) -> None:
        """The failure path is what strands a lock in production."""
        from worker import qwen

        job1 = _job({"files": ["src/README.md"], "instruction": "first"}, id="job-1")
        job2_id = "job-2"

        with contextlib.ExitStack() as stack:
            for p in self._common_patches():
                stack.enter_context(p)
            stack.enter_context(
                mock.patch("worker.qwen._ollama_request", side_effect=RuntimeError("boom"))
            )

            ok1, _ = qwen.handle_qwen_patch(job1)
            self.assertFalse(ok1)

            acquired = qwen._acquire_model_lock(job2_id, wait_ceiling_sec=1)
            if acquired:
                qwen._release_model_lock(job2_id)
            self.assertTrue(acquired, "lock was stranded after the model call raised")


class QwenStaleLockTests(QwenConcurrencyBaseTests):
    """Three branches of the contract's stale-lock rule."""

    def setUp(self) -> None:
        super().setUp()
        # _acquire_model_lock resolves the lock path via _lock_path(), which
        # defaults to the real per-machine state dir. Without this patch,
        # every test below acquires an unrelated real-world lock file instead
        # of inspecting the SUSPECT/STALE lock _write_lock() wrote to
        # self.lock_path, and passes for the wrong reason regardless of the
        # stale-lock rule under test.
        self._lock_path_patcher = mock.patch("worker.qwen._lock_path", return_value=self.lock_path)
        self._lock_path_patcher.start()
        self.addCleanup(self._lock_path_patcher.stop)

    def _write_lock(self, pid: int, age_sec: float) -> None:
        import time

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        started_at = time.time() - age_sec
        self.lock_path.write_text(
            json.dumps({"pid": pid, "started_at": started_at}), encoding="utf-8"
        )

    def test_dead_holder_pid_is_reclaimed(self) -> None:
        from worker import qwen

        # A PID essentially guaranteed not to be alive.
        self._write_lock(pid=999999, age_sec=5)

        with mock.patch("worker.qwen._pid_alive", return_value=False):
            acquired = qwen._acquire_model_lock("job-dead-holder", wait_ceiling_sec=1)

        self.assertTrue(acquired, "a lock held by a dead PID must be reclaimed")
        if acquired:
            qwen._release_model_lock("job-dead-holder")

    def test_alive_holder_within_stale_ceiling_is_not_reclaimed(self) -> None:
        from worker import qwen

        self._write_lock(pid=1, age_sec=10)  # well under stale_ceiling_sec

        with (
            mock.patch("worker.qwen._pid_alive", return_value=True),
            mock.patch("worker.qwen.THRESHOLDS", qwen.QwenThresholds(stale_ceiling_sec=1200), create=True),
        ):
            acquired = qwen._acquire_model_lock("job-active-holder", wait_ceiling_sec=1)

        self.assertFalse(acquired, "an active, fresh lock must not be reclaimed")

    def test_alive_holder_older_than_ceiling_with_nonempty_lane_is_not_reclaimed(self) -> None:
        """SUSPECT branch: alive + past the ceiling is NOT reclaimed on age
        alone. It is only reclaimed if _pid_is_worker is False OR the lane is
        empty. Here the holder IS a worker process AND the lane is non-empty
        — neither condition holds, so the lock must be left alone."""
        from worker import qwen

        self._write_lock(pid=1, age_sec=2000)  # older than stale_ceiling_sec (1200)

        with (
            mock.patch("worker.qwen._pid_alive", return_value=True),
            mock.patch("worker.qwen._pid_is_worker", return_value=True),
            mock.patch("worker.qwen._lane_depth", return_value=1),  # non-empty lane
        ):
            acquired = qwen._acquire_model_lock("job-suspect-holder", wait_ceiling_sec=1)

        self.assertFalse(
            acquired,
            "an alive holder past the ceiling with a non-empty lane must NOT "
            "be reclaimed on age alone",
        )

    def test_alive_holder_older_than_ceiling_not_a_worker_process_is_reclaimed(self) -> None:
        """SUSPECT branch, condition met via _pid_is_worker == False."""
        from worker import qwen

        self._write_lock(pid=1, age_sec=2000)

        with (
            mock.patch("worker.qwen._pid_alive", return_value=True),
            mock.patch("worker.qwen._pid_is_worker", return_value=False),
            mock.patch("worker.qwen._lane_depth", return_value=3),  # lane non-empty is irrelevant here
        ):
            acquired = qwen._acquire_model_lock("job-reclaim-non-worker", wait_ceiling_sec=1)

        self.assertTrue(
            acquired,
            "a SUSPECT holder that is not a worker process must be reclaimed",
        )
        if acquired:
            qwen._release_model_lock("job-reclaim-non-worker")

    def test_alive_holder_older_than_ceiling_empty_lane_is_reclaimed(self) -> None:
        """SUSPECT branch, condition met via empty lane."""
        from worker import qwen

        self._write_lock(pid=1, age_sec=2000)

        with (
            mock.patch("worker.qwen._pid_alive", return_value=True),
            mock.patch("worker.qwen._pid_is_worker", return_value=True),
            mock.patch("worker.qwen._lane_depth", return_value=0),  # empty lane
        ):
            acquired = qwen._acquire_model_lock("job-reclaim-empty-lane", wait_ceiling_sec=1)

        self.assertTrue(
            acquired,
            "a SUSPECT holder whose lane is empty must be reclaimed",
        )
        if acquired:
            qwen._release_model_lock("job-reclaim-empty-lane")


if __name__ == "__main__":
    unittest.main()
