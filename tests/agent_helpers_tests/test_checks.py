"""run-tests: verdict logic, command construction, environment handling."""

from __future__ import annotations

import os
import sys
import unittest.mock
from pathlib import Path

from agent_helpers import checks
from agent_helpers.checks import build_commands, parse_tests_run, run_check
from core.process import CompletedRun
from tests.agent_helpers_tests.helpers import run_json, run_main, write
from tests.fixtures import TempDirMixin


def _run(stdout: str = "", stderr: str = "", rc: int = 0, timed_out: bool = False) -> CompletedRun:
    return CompletedRun(stdout=stdout, stderr=stderr, returncode=rc, timed_out=timed_out)


class TestParseTestsRun(unittest.TestCase):
    def test_single_and_plural(self):
        self.assertEqual(parse_tests_run("Ran 1 test in 0.001s\n"), 1)
        self.assertEqual(parse_tests_run("noise\nRan 42 tests in 3.2s\n\nOK\n"), 42)

    def test_sums_multiple_runs(self):
        self.assertEqual(parse_tests_run("Ran 2 tests in 1s\nRan 3 tests in 1s\n"), 5)

    def test_absent_is_none(self):
        self.assertIsNone(parse_tests_run("make: *** [venv] Error\n"))
        self.assertIsNone(parse_tests_run("we Ran 5 tests in jest\n"))


class TestRunCheckVerdict(unittest.TestCase):
    def _check(self, tool: str, run: CompletedRun, paths: list[str] | None = None):
        with unittest.mock.patch.object(checks, "run_binary", return_value=run) as rb:
            result = run_check(tool, "/repo", paths or [])
        return result, rb

    def test_test_passes_with_ran_line_on_stderr(self):
        result, rb = self._check("test", _run(stderr="Ran 5 tests in 0.1s\n\nOK\n"))
        self.assertTrue(result.passed)
        self.assertEqual(result.tests_run, 5)
        self.assertEqual(rb.call_args.args[0], ["make", "test"])

    def test_zero_exit_without_ran_line_is_failure(self):
        result, _ = self._check("test", _run(stdout="make: venv died quietly\n"))
        self.assertFalse(result.passed)
        self.assertEqual(result.exit_code, 0)
        self.assertIsNone(result.tests_run)
        self.assertIn("Ran N tests", result.error or "")

    def test_multi_path_command_without_ran_line_is_not_masked(self):
        runs = [_run(stderr="Ran 4 tests in 0.1s\n\nOK\n"), _run(stdout="silent\n")]
        with (
            unittest.mock.patch.object(checks, "run_binary", side_effect=runs),
            unittest.mock.patch.object(
                checks, "build_commands", return_value=([["a"], ["b"]], None)
            ),
        ):
            result = run_check("test", "/repo", ["x", "y"])
        self.assertFalse(result.passed)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Ran N tests", result.error or "")

    def test_zero_tests_ran_is_failure(self):
        result, _ = self._check("test", _run(stderr="Ran 0 tests in 0.000s\n\nNO TESTS RAN\n"))
        self.assertFalse(result.passed)
        self.assertEqual(result.tests_run, 0)

    def test_nonzero_exit_is_failure_and_keeps_output(self):
        result, _ = self._check(
            "test", _run(stderr="Ran 3 tests in 1s\n\nFAILED (failures=1)\n", rc=1)
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("FAILED", result.output)

    def test_timeout_is_failure(self):
        result, _ = self._check("test", _run(stderr="Ran 3 tests in 1s\n", rc=124, timed_out=True))
        self.assertFalse(result.passed)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.error, "timed out")

    def test_lint_and_typecheck_use_make_targets_and_need_no_ran_line(self):
        for tool, target in (("lint", "lint"), ("typecheck", "typecheck-changed")):
            with self.subTest(tool=tool):
                result, rb = self._check(tool, _run(stdout="clean\n"))
                self.assertTrue(result.passed)
                self.assertIsNone(result.tests_run)
                self.assertEqual(rb.call_args.args[0], ["make", target])

    def test_lint_failure(self):
        result, _ = self._check("lint", _run(stdout="E501\n", rc=2))
        self.assertFalse(result.passed)
        self.assertEqual(result.exit_code, 2)

    def test_long_output_is_tail_truncated_but_parsed_in_full(self):
        text = "Ran 7 tests in 1s\n" + "x" * (checks._MAX_OUTPUT_CHARS + 10)
        result, _ = self._check("test", _run(stderr=text))
        self.assertTrue(result.truncated)
        self.assertEqual(len(result.output), checks._MAX_OUTPUT_CHARS)
        self.assertEqual(result.tests_run, 7)
        self.assertTrue(result.passed)

    def test_child_env_replaces_foreign_pythonpath(self):
        with unittest.mock.patch.dict(os.environ, {"PYTHONPATH": "/other/checkout/src"}):
            _, rb = self._check("test", _run(stderr="Ran 1 test in 0s\n"))
        self.assertEqual(rb.call_args.kwargs["env"]["PYTHONPATH"], "/repo/src")
        self.assertEqual(rb.call_args.kwargs["cwd"], "/repo")
        self.assertGreater(rb.call_args.kwargs["timeout"], 0)


class TestResolveTestPath(TempDirMixin, unittest.TestCase):
    """Path-confinement guard for _resolve_test_path."""

    def _resolve(self, raw: str):
        return checks._resolve_test_path(Path(self.tmpdir).resolve(), raw)

    def test_relative_path_inside_repo_accepted(self):
        subdir = Path(self.tmpdir) / "tests"
        subdir.mkdir()
        path, error = self._resolve("tests")
        self.assertIsNone(error)
        self.assertIsNotNone(path)

    def test_relative_path_escaping_repo_rejected(self):
        _, error = self._resolve("../outside")
        self.assertIn("escapes", error or "")

    def test_absolute_path_inside_repo_accepted(self):
        subdir = Path(self.tmpdir) / "sub"
        subdir.mkdir()
        _, error = self._resolve(str(subdir))
        self.assertIsNone(error)

    def test_absolute_path_outside_repo_rejected(self):
        # Use the parent of tmpdir — guaranteed to be outside the repo root.
        parent = str(Path(self.tmpdir).parent)
        _, error = self._resolve(parent)
        self.assertIn("escapes", error or "")

    def test_dot_resolves_to_root_and_is_accepted(self):
        """'.' resolves to repo root itself; accepted since path == root is allowed."""
        path, error = self._resolve(".")
        self.assertIsNone(error)
        self.assertEqual(path, Path(self.tmpdir).resolve())

    def test_empty_string_resolves_to_root_and_is_accepted(self):
        """An empty string is treated the same as '.'."""
        path, error = self._resolve("")
        self.assertIsNone(error)
        self.assertEqual(path, Path(self.tmpdir).resolve())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks not available")
    def test_symlink_inside_repo_pointing_outside_rejected(self):
        """A symlink that resolves outside the repo root is rejected."""
        outside = Path(self.tmpdir).parent / "outside_target"
        outside.mkdir(exist_ok=True)
        link = Path(self.tmpdir) / "escape_link"
        try:
            os.symlink(str(outside), str(link))
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation failed on this platform")
        _, error = self._resolve("escape_link")
        self.assertIn("escapes", error or "")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks not available")
    def test_symlink_inside_repo_pointing_inside_accepted(self):
        """A symlink whose target is inside the repo root is accepted."""
        target = Path(self.tmpdir) / "real_dir"
        target.mkdir()
        link = Path(self.tmpdir) / "link_to_real"
        try:
            os.symlink(str(target), str(link))
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation failed on this platform")
        _, error = self._resolve("link_to_real")
        self.assertIsNone(error)


class TestBuildCommands(TempDirMixin, unittest.TestCase):
    def test_directory_uses_discover(self):
        (Path(self.tmpdir) / "tests").mkdir()
        commands, error = build_commands("test", self.tmpdir, ["tests"])
        self.assertIsNone(error)
        root = Path(self.tmpdir).resolve()
        self.assertEqual(
            commands,
            [
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-t",
                    str(root),
                    "-s",
                    str(root / "tests"),
                ]
            ],
        )

    def test_file_uses_pattern(self):
        (Path(self.tmpdir) / "tests").mkdir()
        write(str(Path(self.tmpdir) / "tests"), "test_a.py", "")
        commands, _ = build_commands("test", self.tmpdir, ["tests/test_a.py"])
        self.assertEqual(commands[0][-2:], ["-p", "test_a.py"])

    def test_one_command_per_path(self):
        for name in ("a", "b"):
            (Path(self.tmpdir) / name).mkdir()
        commands, _ = build_commands("test", self.tmpdir, ["a", "b"])
        self.assertEqual(len(commands), 2)

    def test_path_escaping_repo_is_rejected(self):
        commands, error = build_commands("test", self.tmpdir, ["../outside"])
        self.assertEqual(commands, [])
        self.assertIn("escapes", error or "")

    def test_missing_path_is_rejected(self):
        commands, error = build_commands("test", self.tmpdir, ["nope"])
        self.assertEqual(commands, [])
        self.assertIn("not found", error or "")

    def test_bad_path_yields_failed_result_without_running(self):
        with unittest.mock.patch.object(checks, "run_binary") as rb:
            result = run_check("test", self.tmpdir, ["nope"])
        rb.assert_not_called()
        self.assertFalse(result.passed)
        self.assertIn("not found", result.error or "")


class TestRunCheckRealSubprocess(TempDirMixin, unittest.TestCase):
    """One real unittest child process against a throwaway repo layout."""

    def _make_suite(self, body: str) -> None:
        tests = Path(self.tmpdir) / "tests"
        tests.mkdir()
        write(str(tests), "__init__.py", "")
        write(
            str(tests),
            "test_sample.py",
            f"import unittest\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        {body}\n",
        )

    def test_passing_suite(self):
        self._make_suite("self.assertTrue(True)")
        result = run_check("test", self.tmpdir, ["tests"])
        self.assertTrue(result.passed, result.output)
        self.assertEqual(result.tests_run, 1)

    def test_failing_suite(self):
        self._make_suite("self.fail('boom')")
        result = run_check("test", self.tmpdir, ["tests"])
        self.assertFalse(result.passed)
        self.assertEqual(result.tests_run, 1)
        self.assertIn("boom", result.output)


class TestRunTestsCli(unittest.TestCase):
    def test_default_tool_runs_make_test(self):
        with (
            unittest.mock.patch(
                "agent_helpers.cli.resolve_repo_root", return_value=("/repo", None)
            ),
            unittest.mock.patch.object(
                checks, "run_binary", return_value=_run(stderr="Ran 2 tests in 0s\n")
            ),
        ):
            result = run_json(["run-tests"])
        self.assertTrue(result["passed"])
        self.assertEqual(result["tests_run"], 2)
        self.assertEqual(result["commands"], [["make", "test"]])

    def test_paths_with_lint_is_usage_error(self):
        with unittest.mock.patch(
            "agent_helpers.cli.resolve_repo_root", return_value=("/repo", None)
        ):
            rc, out, err = run_main(["run-tests", "--tool", "lint", "--paths", "tests"])
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("--paths", err)

    def test_paths_with_lint_is_usage_error_outside_repo(self):
        with unittest.mock.patch(
            "agent_helpers.cli.resolve_repo_root", return_value=("", "not inside a git repository")
        ):
            rc, out, err = run_main(["run-tests", "--tool", "lint", "--paths", "tests"])
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("--paths", err)

    def test_outside_repo_reports_failure_in_body(self):
        with unittest.mock.patch(
            "agent_helpers.cli.resolve_repo_root", return_value=("", "not inside a git repository")
        ):
            result = run_json(["run-tests"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["error"], "not inside a git repository")
        # The error path must emit the same full CheckResult shape as the normal path.
        for key in (
            "tool",
            "paths",
            "commands",
            "exit_code",
            "passed",
            "tests_run",
            "timed_out",
            "error",
            "output",
            "truncated",
        ):
            self.assertIn(key, result, f"key {key!r} missing from outside-repo error body")


if __name__ == "__main__":
    unittest.main()
