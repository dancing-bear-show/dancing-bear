"""Tests for bin/mypy_ratchet.py — the mypy changed-files gate and ratchet.

The gate's whole value is that it fails when it should. The failure mode that
matters is not a crash but a *false clean*: a run that checked nothing, or
output that could not be parsed, reported as a pass. Those paths get the most
attention here.

bin/ is not a package, so the module is loaded by path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "bin" / "mypy_ratchet.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("mypy_ratchet", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mr = _load_module()


class ParseTotalTests(unittest.TestCase):
    """The summary line is the only trustworthy error count in mypy's output."""

    def test_parses_plural_summary(self):
        self.assertEqual(
            mr._parse_total("Found 445 errors in 122 files (checked 514 source files)"),
            445,
        )

    def test_parses_singular_summary(self):
        # `Found 1 error in 1 file` — no trailing 's' on either noun.
        self.assertEqual(
            mr._parse_total("Found 1 error in 1 file (checked 3 source files)"), 1
        )

    def test_success_line_is_zero(self):
        self.assertEqual(mr._parse_total("Success: no issues found in 6 source files"), 0)

    def test_missing_summary_raises_rather_than_returning_zero(self):
        """A crashed mypy must never read as a clean run.

        This is the single most likely way the ratchet lands broken: if an
        unparseable run counted as zero errors, every subsequent comparison
        would pass and the gate would be permanently disarmed.
        """
        with self.assertRaises(mr.MypyInvocationError):
            mr._parse_total("Traceback (most recent call last):\n  INTERNAL ERROR")

    def test_notes_only_output_raises(self):
        with self.assertRaises(mr.MypyInvocationError):
            mr._parse_total("src/x.py:1: note: some context")

    def test_empty_output_raises(self):
        with self.assertRaises(mr.MypyInvocationError):
            mr._parse_total("")


class ErrorsByFileTests(unittest.TestCase):
    def test_counts_errors_and_excludes_notes(self):
        output = (
            "src/a.py:1: error: bad\n"
            "src/a.py:2: note: contextual detail\n"
            "src/b.py:9:4: error: worse\n"
            "Found 2 errors in 2 files (checked 2 source files)\n"
        )
        self.assertEqual(mr._errors_by_file(output), {"src/a.py": 1, "src/b.py": 1})

    def test_handles_column_qualified_positions(self):
        self.assertEqual(mr._errors_by_file("src/a.py:3:17: error: x"), {"src/a.py": 1})


class PackageGroupingTests(unittest.TestCase):
    def test_src_paths_group_by_package(self):
        self.assertEqual(mr._package_of("src/telemetry/cli.py"), "telemetry")

    def test_non_src_paths_group_by_top_level_dir(self):
        self.assertEqual(mr._package_of("tests/mail_tests/fixtures.py"), "tests")
        self.assertEqual(mr._package_of("bin/mypy_ratchet.py"), "bin")

    def test_aggregates_counts(self):
        counts = {
            "src/core/a.py": 2,
            "src/core/b.py": 3,
            "src/wifi/c.py": 1,
        }
        self.assertEqual(mr._packages(counts), {"core": 5, "wifi": 1})


class IsCheckableTests(unittest.TestCase):
    def test_rejects_non_python(self):
        self.assertFalse(mr._is_checkable("src/core/data.yaml"))

    def test_rejects_paths_outside_checked_roots(self):
        self.assertFalse(mr._is_checkable("docs/notes.py"))

    def test_rejects_deleted_file(self):
        """A deleted path is still in the diff but would break the invocation."""
        self.assertFalse(mr._is_checkable("src/core/does_not_exist_xyz.py"))

    def test_accepts_existing_source_file(self):
        self.assertTrue(mr._is_checkable("bin/mypy_ratchet.py"))


class ChangedFilesTests(unittest.TestCase):
    """The diff must union committed and working-tree changes."""

    def test_unresolvable_base_is_a_hard_error(self):
        """A bad base ref must not quietly degrade to a working-tree scan."""
        with mock.patch.object(mr, "_rev_exists", return_value=False):
            with self.assertRaises(mr.MypyInvocationError) as ctx:
                mr._changed_files("no-such-ref")
        self.assertIn("fetch-depth", str(ctx.exception))

    def test_unions_committed_diff_with_working_tree(self):
        """Staged work must be checked even when the committed diff is non-empty.

        Taking the diff alone and only falling back when empty means that on any
        branch with a commit, uncommitted work is silently skipped — a pass
        while the new code goes unchecked.
        """

        def fake_git(*args):
            if args[0] == "diff":
                return "bin/mypy_ratchet.py\n"
            if args[0] == "status":
                return " M tests/infra/test_mypy_ratchet.py\n"
            return ""

        with mock.patch.object(mr, "_rev_exists", return_value=True):
            with mock.patch.object(mr, "_git", side_effect=fake_git):
                files, source = mr._changed_files("main")

        self.assertIn("bin/mypy_ratchet.py", files)
        self.assertIn("tests/infra/test_mypy_ratchet.py", files)
        self.assertIn("working tree", source)

    def test_rename_uses_destination_path(self):
        def fake_git(*args):
            if args[0] == "status":
                return "R  bin/old.py -> bin/mypy_ratchet.py\n"
            return ""

        with mock.patch.object(mr, "_rev_exists", return_value=True):
            with mock.patch.object(mr, "_git", side_effect=fake_git):
                files, _ = mr._changed_files("main")

        self.assertEqual(files, ["bin/mypy_ratchet.py"])

    def test_empty_diff_reports_no_files(self):
        with mock.patch.object(mr, "_rev_exists", return_value=True):
            with mock.patch.object(mr, "_git", return_value=""):
                files, _ = mr._changed_files("main")
        self.assertEqual(files, [])


class BaselineTests(unittest.TestCase):
    def test_committed_baseline_is_valid_and_self_consistent(self):
        """The shipped baseline must parse and its packages must sum to total."""
        with mr.BASELINE_PATH.open(encoding="utf-8") as handle:
            data = json.load(handle)

        self.assertIn("total", data)
        self.assertIn("packages", data)
        self.assertIn("legacy_files", data)
        self.assertEqual(
            sum(data["packages"].values()),
            data["total"],
            "per-package counts must sum to the recorded total",
        )
        self.assertEqual(data["roots"], list(mr.CHECKED_ROOTS))

    def test_missing_baseline_raises(self):
        with mock.patch.object(mr, "BASELINE_PATH", Path("/nonexistent/baseline.json")):
            with self.assertRaises(mr.MypyInvocationError):
                mr._load_baseline()


class RatchetPlatformTests(unittest.TestCase):
    """The ratchet enforces strictly on the baseline platform, not elsewhere.

    macOS and Linux legitimately produce different counts for the same tree:
    rumps is pinned darwin-only, so the menubar tests are analysed on one and
    absent on the other. Failing a macOS developer's build over that would train
    people to ignore the gate.
    """

    BASE = {"total": 100, "packages": {"core": 10, "mail": 5}, "legacy_files": []}

    @staticmethod
    def _output(core: int, mail: int) -> str:
        lines = [f"src/core/f{i}.py:1: error: x" for i in range(core)]
        lines += [f"src/mail/g{i}.py:1: error: x" for i in range(mail)]
        total = core + mail
        lines.append(f"Found {total} errors in {total} files (checked 20 source files)")
        return "\n".join(lines)

    def _run(self, platform: str, output: str) -> int:
        import argparse

        with mock.patch.object(mr, "_load_baseline", return_value=self.BASE), mock.patch.object(
            mr, "_run_mypy", return_value=output
        ), mock.patch.object(sys, "platform", platform):
            return mr.cmd_ratchet(argparse.Namespace())

    def test_regression_fails_on_baseline_platform(self):
        self.assertEqual(self._run("linux", self._output(core=12, mail=5)), 1)

    def test_regression_is_deferred_off_baseline_platform(self):
        """Not a pass claim — it reports the delta and defers to CI."""
        self.assertEqual(self._run("darwin", self._output(core=12, mail=5)), 0)

    def test_matching_counts_pass_on_baseline_platform(self):
        self.assertEqual(self._run("linux", self._output(core=10, mail=5)), 0)

    def test_improvement_passes_and_does_not_rewrite_baseline(self):
        before = mr.BASELINE_PATH.read_bytes()
        self.assertEqual(self._run("linux", self._output(core=8, mail=5)), 0)
        self.assertEqual(
            mr.BASELINE_PATH.read_bytes(),
            before,
            "the ratchet must never rewrite the baseline itself",
        )


class MypyOutputGuardTests(unittest.TestCase):
    def test_silent_mypy_run_raises(self):
        """No output at all cannot be interpreted as success."""
        completed = mock.Mock(stdout="", stderr="", returncode=0)
        with mock.patch.object(mr.subprocess, "run", return_value=completed):
            with self.assertRaises(mr.MypyInvocationError):
                mr._run_mypy(["src"])


class CliTests(unittest.TestCase):
    def test_requires_a_subcommand(self):
        with self.assertRaises(SystemExit):
            mr.main([])

    def test_invocation_error_exits_two(self):
        """A broken invocation is distinct from a type-error failure (1)."""
        with mock.patch.object(
            mr, "cmd_ratchet", side_effect=mr.MypyInvocationError("boom")
        ):
            self.assertEqual(mr.main(["ratchet"]), 2)


if __name__ == "__main__":
    unittest.main()
