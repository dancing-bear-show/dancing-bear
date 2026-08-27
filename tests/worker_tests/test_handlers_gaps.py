"""Gap coverage tests for worker.handlers — internal helpers not reached by test_handlers.py.

Covers:
  - _build_command (relative vs. absolute prog)
  - _validate_run_cli_payload (empty cmd, disallowed prog, happy path)
  - _parse_run_cli_timeout (valid, missing, non-numeric)
  - _shell_allowlist / _get_shell_allowlist (env-var override, defaults)
  - _write_script_tempfile (happy path, executable bit, cleanup on error)
  - _needs_tempfile
  - _resolve_exec_context (cwd defaulting, timeout fallback)
  - _exec_shell_result (ok and error branches)
  - _is_allowed_bin (absolute path edge cases)
"""

from __future__ import annotations

import os
import stat
import unittest
from pathlib import Path
from unittest.mock import patch


class TestBuildCommand(unittest.TestCase):
    """_build_command resolves relative names to absolute bin/ paths."""

    def test_relative_name_becomes_absolute(self) -> None:
        from worker.handlers import _build_command

        with patch("worker.handlers.get_repo_root", return_value=Path("/repo")):
            result = _build_command("worker", ["worker", "status"])
        self.assertTrue(Path(result[0]).is_absolute())
        self.assertIn("bin", result[0])
        self.assertIn("worker", result[0])

    def test_relative_name_passes_remaining_args(self) -> None:
        from worker.handlers import _build_command

        with patch("worker.handlers.get_repo_root", return_value=Path("/repo")):
            result = _build_command("worker", ["worker", "--dry-run", "--format", "json"])
        self.assertEqual(result[1:], ["--dry-run", "--format", "json"])

    def test_absolute_prog_returned_unchanged(self) -> None:
        from worker.handlers import _build_command

        abs_prog = "/usr/local/bin/something"
        result = _build_command(abs_prog, [abs_prog, "arg1"])
        self.assertEqual(result[0], abs_prog)
        self.assertEqual(result[1:], ["arg1"])

    def test_absolute_prog_with_no_extra_args(self) -> None:
        from worker.handlers import _build_command

        abs_prog = "/usr/local/bin/tool"
        result = _build_command(abs_prog, [abs_prog])
        self.assertEqual(result, [abs_prog])


class TestValidateRunCliPayload(unittest.TestCase):
    """_validate_run_cli_payload error and happy paths."""

    def test_empty_cmd_list_returns_error(self) -> None:
        from worker.handlers import _validate_run_cli_payload

        error, prog, cmd_list = _validate_run_cli_payload({"cmd": []})
        self.assertIn("missing", error)
        self.assertIsNone(prog)
        self.assertIsNone(cmd_list)

    def test_none_cmd_returns_error(self) -> None:
        from worker.handlers import _validate_run_cli_payload

        error, prog, cmd_list = _validate_run_cli_payload({})
        self.assertIn("missing", error)
        self.assertIsNone(prog)
        self.assertIsNone(cmd_list)

    def test_disallowed_program_returns_error(self) -> None:
        from worker.handlers import _validate_run_cli_payload

        error, prog, cmd_list = _validate_run_cli_payload({"cmd": ["evil-script", "--flag"]})
        self.assertIn("disallowed", error)
        self.assertIsNone(prog)
        self.assertIsNone(cmd_list)

    def test_allowed_program_returns_prog_and_cmd_list(self) -> None:
        from worker.handlers import _validate_run_cli_payload

        with patch("worker.handlers._is_allowed_bin", return_value=True):
            error, prog, cmd_list = _validate_run_cli_payload({"cmd": ["worker", "status"]})
        self.assertIsNone(error)
        self.assertEqual(prog, "worker")
        self.assertEqual(cmd_list, ["worker", "status"])


class TestParseRunCliTimeout(unittest.TestCase):
    """_parse_run_cli_timeout falls back to 300 on bad input."""

    def test_valid_integer_payload(self) -> None:
        from worker.handlers import _parse_run_cli_timeout

        self.assertEqual(_parse_run_cli_timeout({"timeout": 600}), 600)

    def test_valid_string_integer(self) -> None:
        from worker.handlers import _parse_run_cli_timeout

        self.assertEqual(_parse_run_cli_timeout({"timeout": "120"}), 120)

    def test_missing_timeout_defaults_to_300(self) -> None:
        from worker.handlers import _parse_run_cli_timeout

        self.assertEqual(_parse_run_cli_timeout({}), 300)

    def test_non_numeric_string_falls_back_to_300(self) -> None:
        from worker.handlers import _parse_run_cli_timeout

        self.assertEqual(_parse_run_cli_timeout({"timeout": "bad"}), 300)


class TestShellAllowlist(unittest.TestCase):
    """_shell_allowlist returns env-var override or conservative defaults."""

    def test_default_allowlist_includes_python3_and_bash(self) -> None:
        from worker.handlers import _shell_allowlist

        env_key = "DANCING_BEAR_WORKER_SHELL_ALLOWLIST"
        original = os.environ.pop(env_key, None)
        try:
            result = _shell_allowlist()
        finally:
            if original is not None:
                os.environ[env_key] = original

        self.assertIn("python3", result)
        self.assertIn("bash", result)

    def test_env_var_replaces_defaults(self) -> None:
        from worker.handlers import _shell_allowlist

        with patch.dict(os.environ, {"DANCING_BEAR_WORKER_SHELL_ALLOWLIST": "python3,bash"}):
            result = _shell_allowlist()
        self.assertEqual(result, {"python3", "bash"})
        self.assertNotIn("jq", result)

    def test_env_var_strips_whitespace(self) -> None:
        from worker.handlers import _shell_allowlist

        with patch.dict(os.environ, {"DANCING_BEAR_WORKER_SHELL_ALLOWLIST": " rg , jq "}):
            result = _shell_allowlist()
        self.assertEqual(result, {"rg", "jq"})

    def test_get_shell_allowlist_mirrors_shell_allowlist(self) -> None:
        from worker.handlers import _get_shell_allowlist, _shell_allowlist

        env_key = "DANCING_BEAR_WORKER_SHELL_ALLOWLIST"
        original = os.environ.pop(env_key, None)
        try:
            direct = _shell_allowlist()
            via_getter = _get_shell_allowlist()
        finally:
            if original is not None:
                os.environ[env_key] = original

        self.assertEqual(direct, via_getter)


class TestWriteScriptTempfile(unittest.TestCase):
    """_write_script_tempfile creates executable temp scripts."""

    def test_writes_content_to_file(self) -> None:
        from worker.handlers import _write_script_tempfile

        path = _write_script_tempfile("echo hello\n")
        try:
            with open(path) as fh:
                content = fh.read()
            self.assertEqual(content, "echo hello\n")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_file_is_executable(self) -> None:
        from worker.handlers import _write_script_tempfile

        path = _write_script_tempfile("#!/bin/bash\necho hi\n")
        try:
            mode = os.stat(path).st_mode
            self.assertTrue(mode & stat.S_IXUSR, "Owner execute bit must be set")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_tempfile_has_sh_suffix(self) -> None:
        from worker.handlers import _write_script_tempfile

        path = _write_script_tempfile("echo x")
        try:
            self.assertTrue(path.endswith(".sh"), f"Expected .sh suffix, got: {path}")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_raises_on_chmod_failure(self) -> None:
        """When os.chmod fails the error must propagate (not be swallowed)."""
        from worker.handlers import _write_script_tempfile

        with patch("worker.handlers.os.chmod", side_effect=OSError("chmod failed")):
            with self.assertRaises(OSError):
                _write_script_tempfile("echo x")


class TestNeedsTempfile(unittest.TestCase):
    """_needs_tempfile identifies scripts requiring temp-file dispatch."""

    def test_multiline_needs_tempfile(self) -> None:
        from worker.handlers import _needs_tempfile

        self.assertTrue(_needs_tempfile("echo hi\necho there"))

    def test_double_quote_needs_tempfile(self) -> None:
        from worker.handlers import _needs_tempfile

        self.assertTrue(_needs_tempfile('echo "hello world"'))

    def test_single_quote_needs_tempfile(self) -> None:
        from worker.handlers import _needs_tempfile

        self.assertTrue(_needs_tempfile("echo 'hello'"))

    def test_simple_single_line_does_not_need_tempfile(self) -> None:
        from worker.handlers import _needs_tempfile

        self.assertFalse(_needs_tempfile("echo hello"))

    def test_empty_script_does_not_need_tempfile(self) -> None:
        from worker.handlers import _needs_tempfile

        self.assertFalse(_needs_tempfile(""))


class TestResolveExecContext(unittest.TestCase):
    """_resolve_exec_context extracts env, timeout, and cwd from a payload."""

    def test_extracts_env_overlay(self) -> None:
        from worker.handlers import _resolve_exec_context

        env, _timeout, _cwd = _resolve_exec_context({"env": {"FOO": "bar"}, "cwd": "/tmp"})  # nosec B108 - test path
        self.assertEqual(env, {"FOO": "bar"})

    def test_extracts_timeout(self) -> None:
        from worker.handlers import _resolve_exec_context

        _env, timeout, _cwd = _resolve_exec_context({"timeout": 42, "cwd": "/tmp"})  # nosec B108 - test path
        self.assertEqual(timeout, 42)

    def test_bad_timeout_falls_back_to_300(self) -> None:
        from worker.handlers import _resolve_exec_context

        _env, timeout, _cwd = _resolve_exec_context({"timeout": "bad", "cwd": "/tmp"})  # nosec B108 - test path
        self.assertEqual(timeout, 300)

    def test_cwd_extracted_when_present(self) -> None:
        from worker.handlers import _resolve_exec_context

        _env, _timeout, cwd = _resolve_exec_context({"cwd": "/workspace"})
        self.assertEqual(cwd, "/workspace")

    def test_missing_cwd_defaults_to_repo_root(self) -> None:
        from worker.handlers import _resolve_exec_context

        with patch("worker.handlers.get_repo_root", return_value=Path("/repo")):
            _env, _timeout, cwd = _resolve_exec_context({})
        self.assertEqual(cwd, "/repo")

    def test_empty_cwd_defaults_to_repo_root(self) -> None:
        from worker.handlers import _resolve_exec_context

        with patch("worker.handlers.get_repo_root", return_value=Path("/repo")):
            _env, _timeout, cwd = _resolve_exec_context({"cwd": ""})
        self.assertEqual(cwd, "/repo")


class TestExecShellResult(unittest.TestCase):
    """_exec_shell_result converts subprocess output dicts to (ok, result) tuples."""

    def test_returncode_zero_is_ok(self) -> None:
        from worker.handlers import _exec_shell_result

        ok, result = _exec_shell_result({"returncode": 0, "stdout": "hi", "stderr": ""})
        self.assertTrue(ok)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["stdout"], "hi")

    def test_nonzero_returncode_is_not_ok(self) -> None:
        from worker.handlers import _exec_shell_result

        ok, result = _exec_shell_result({"returncode": 1, "stdout": "", "stderr": "oops"})
        self.assertFalse(ok)
        self.assertIn("oops", str(result))

    def test_nonzero_with_no_stderr_returns_dict(self) -> None:
        from worker.handlers import _exec_shell_result

        ok, result = _exec_shell_result({"returncode": 2, "stdout": "out", "stderr": ""})
        self.assertFalse(ok)
        # Empty stderr => falls back to the full output dict
        self.assertIsInstance(result, dict)

    def test_missing_returncode_treated_as_nonzero(self) -> None:
        from worker.handlers import _exec_shell_result

        ok, _result = _exec_shell_result({})
        self.assertFalse(ok)


class TestIsAllowedBinEdgeCases(unittest.TestCase):
    """_is_allowed_bin rejects absolute paths not under bin/ and handles resolve errors."""

    def test_absolute_path_outside_bin_rejected(self) -> None:
        from worker.handlers import _is_allowed_bin

        # /bin/sh is not under the repo's bin/ directory
        self.assertFalse(_is_allowed_bin("/bin/sh"))

    def test_path_resolve_exception_returns_false(self) -> None:
        from worker.handlers import _is_allowed_bin

        with patch("worker.handlers.Path.resolve", side_effect=OSError("bad")):
            result = _is_allowed_bin("/some/absolute/path")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
