"""Tests for worker.handlers — focused on handle_workflow_stage."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from worker._helpers import get_repo_root
from worker.handlers import REGISTRY, _is_allowed_bin, handle_workflow_stage


def _make_job(payload: dict) -> dict:
    return {"id": "test-job", "type": "workflow_stage", "payload": payload}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestHandlerRegistry(unittest.TestCase):
    """workflow_stage must be registered and callable."""

    def test_workflow_stage_registered(self) -> None:
        self.assertIn("workflow_stage", REGISTRY)

    def test_workflow_stage_is_callable(self) -> None:
        self.assertTrue(callable(REGISTRY["workflow_stage"]))

    def test_registry_entry_is_handle_workflow_stage(self) -> None:
        self.assertIs(REGISTRY["workflow_stage"], handle_workflow_stage)


# ---------------------------------------------------------------------------
# Script path
# ---------------------------------------------------------------------------


class TestHandleWorkflowStageScriptPath(unittest.TestCase):
    """handle_workflow_stage with a script payload delegates to handle_run_shell."""

    def test_delegates_to_run_shell_when_script_present(self) -> None:
        job = _make_job({"script": "echo hello", "workspace_dir": ""})

        with patch("worker.handlers.handle_run_shell", return_value=(True, {"returncode": 0})) as mock_shell:
            ok, _ = handle_workflow_stage(job)

        mock_shell.assert_called_once()
        self.assertTrue(ok)

    def test_script_passed_through_to_shell_job(self) -> None:
        job = _make_job({"script": "echo hello"})

        with patch("worker.handlers.handle_run_shell", return_value=(True, {})) as mock_shell:
            handle_workflow_stage(job)

        shell_job = mock_shell.call_args[0][0]
        self.assertEqual(shell_job["payload"]["script"], "echo hello")

    def test_workspace_dir_set_as_cwd_for_script(self) -> None:
        job = _make_job({"script": "echo hi", "workspace_dir": "/tmp/ws"})  # nosec B108 - test string only

        with patch("worker.handlers.handle_run_shell", return_value=(True, {})) as mock_shell:
            handle_workflow_stage(job)

        shell_job = mock_shell.call_args[0][0]
        self.assertEqual(shell_job["payload"]["cwd"], "/tmp/ws")  # nosec B108 - test string only

    def test_cwd_not_set_when_workspace_dir_empty(self) -> None:
        job = _make_job({"script": "echo hi", "workspace_dir": ""})

        with patch("worker.handlers.handle_run_shell", return_value=(True, {})) as mock_shell:
            handle_workflow_stage(job)

        shell_job = mock_shell.call_args[0][0]
        self.assertNotIn("cwd", shell_job["payload"])

    def test_cli_commands_not_used_when_script_present(self) -> None:
        job = _make_job({"script": "echo hi", "cli_commands": ["./bin/worker status"]})

        with patch("worker.handlers.handle_run_shell", return_value=(True, {})), \
             patch("worker.handlers.handle_run_cli") as mock_cli:
            handle_workflow_stage(job)

        mock_cli.assert_not_called()


# ---------------------------------------------------------------------------
# CLI commands fallback path
# ---------------------------------------------------------------------------


class TestHandleWorkflowStageCLIPath(unittest.TestCase):
    """handle_workflow_stage falls back to handle_run_cli when no script."""

    def test_delegates_to_run_cli_when_no_script(self) -> None:
        job = _make_job({"cli_commands": ["./bin/worker status"], "workspace_dir": ""})

        with patch("worker.handlers.handle_run_cli", return_value=(True, {"returncode": 0})) as mock_cli:
            ok, _ = handle_workflow_stage(job)

        mock_cli.assert_called_once()
        self.assertTrue(ok)

    def test_first_cli_command_split_with_shlex(self) -> None:
        job = _make_job({"cli_commands": ['./bin/worker status --query "some query"']})

        with patch("worker.handlers.handle_run_cli", return_value=(True, {})) as mock_cli:
            handle_workflow_stage(job)

        cli_job = mock_cli.call_args_list[0][0][0]
        self.assertEqual(cli_job["payload"]["cmd"], ["./bin/worker", "status", "--query", "some query"])

    def test_all_cli_commands_executed(self) -> None:
        job = _make_job({"cli_commands": ["./bin/worker status", "./bin/worker counts"]})

        with patch("worker.handlers.handle_run_cli", return_value=(True, {})) as mock_cli:
            ok, _ = handle_workflow_stage(job)

        self.assertEqual(mock_cli.call_count, 2)
        self.assertTrue(ok)

    def test_cli_stops_on_first_failure(self) -> None:
        job = _make_job({"cli_commands": ["./bin/worker status", "./bin/worker counts"]})

        with patch("worker.handlers.handle_run_cli", side_effect=[(False, "err"), (True, {})]) as mock_cli:
            ok, _ = handle_workflow_stage(job)

        self.assertFalse(ok)
        self.assertEqual(mock_cli.call_count, 1)

    def test_workspace_dir_set_as_cwd_for_cli(self) -> None:
        job = _make_job({"cli_commands": ["./bin/worker status"], "workspace_dir": "/tmp/ws"})  # nosec B108 - test string only

        with patch("worker.handlers.handle_run_cli", return_value=(True, {})) as mock_cli:
            handle_workflow_stage(job)

        cli_job = mock_cli.call_args[0][0]
        self.assertEqual(cli_job["payload"]["cwd"], "/tmp/ws")  # nosec B108 - test string only

    def test_cwd_honoured_by_handle_run_cli(self) -> None:
        """cwd from payload reaches _execute_subprocess, not just handle_workflow_stage."""
        from worker.handlers import handle_run_cli
        job = {"id": "t", "type": "run_cli", "payload": {
            "cmd": ["./bin/worker", "status"],
            "cwd": "/tmp/custom-cwd",  # nosec B108 - test string only
        }}
        with patch("worker.handlers._execute_subprocess", return_value={"returncode": 0, "stdout": "", "stderr": ""}) as mock_exec, \
             patch("worker.handlers._is_allowed_bin", return_value=True), \
             patch("worker.handlers._build_command", return_value=["./bin/worker", "status"]):
            handle_run_cli(job)

        self.assertEqual(mock_exec.call_args.kwargs.get("cwd"), "/tmp/custom-cwd")  # nosec B108 - test string only


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


class TestHandleWorkflowStageErrors(unittest.TestCase):
    """handle_workflow_stage returns failure when payload has neither script nor cli_commands."""

    def test_missing_both_returns_false(self) -> None:
        job = _make_job({})
        ok, _ = handle_workflow_stage(job)
        self.assertFalse(ok)

    def test_missing_both_error_message(self) -> None:
        job = _make_job({})
        _, msg = handle_workflow_stage(job)
        self.assertIn("neither", str(msg))

    def test_empty_script_and_empty_cli_returns_false(self) -> None:
        job = _make_job({"script": "  ", "cli_commands": []})
        ok, _ = handle_workflow_stage(job)
        self.assertFalse(ok)


class TestGetRepoRoot(unittest.TestCase):
    """Regression guards for worker._helpers.get_repo_root.

    These exercise the real filesystem rather than a patched root: the bug they
    guard against was invisible to every existing test precisely because those
    tests patch get_repo_root. telemetry.otel.config._get_repo_root had the
    identical defect and carries the same guards.
    """

    def test_repo_root_is_not_src(self) -> None:
        # get_repo_root previously used parents[1], landing at <repo>/src.
        root = get_repo_root()
        self.assertNotEqual(root.name, "src")

    def test_repo_root_contains_bin_dir(self) -> None:
        # Every caller in worker.handlers builds `get_repo_root() / "bin"`.
        root = get_repo_root()
        self.assertTrue((root / "bin").is_dir(), f"Expected {root / 'bin'} to be a directory")

    def test_allowlisted_bin_resolves(self) -> None:
        # The user-visible symptom: with the root one level short, every
        # allowlisted command was rejected because <repo>/src/bin does not exist.
        self.assertTrue(_is_allowed_bin("worker"))

    def test_non_allowlisted_bin_still_rejected(self) -> None:
        # The allowlist boundary must survive the path fix.
        self.assertFalse(_is_allowed_bin("evil"))
        self.assertFalse(_is_allowed_bin("/bin/sh"))


if __name__ == "__main__":
    unittest.main()
