"""CLI tests for the ``select-concerns`` subcommand of workflow.

Covers:
- _cmd_select_concerns exit codes, text and JSON output formats
- --paths-file I/O and decode errors (exit 1 contract)
- stdin paths-file (``-``) and missing rules file
- Unknown task_type exits 2, lists valid types without echoing the value
- End-to-end run through workflow_main argparse wiring
- End-to-end run of the real ./bin/workflow wrapper with PYTHONPATH unset
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess  # nosec B404 - runs the repo's own ./bin/workflow wrapper
import sys
import tempfile
import unittest
import unittest.mock as mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from workflow import concern_select
from workflow.cli import main as workflow_main
from workflow.concern_select import (
    SelectionRulesNotFoundError,
    select_guides,
    valid_task_types,
)
from workflow.cli_dispatch_review import _cmd_select_concerns

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(**kwargs) -> argparse.Namespace:
    """Build a minimal Namespace for _cmd_select_concerns."""
    defaults = {
        "paths": [],
        "paths_file": "",
        "task_type": "",
        "format": "text",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = workflow_main(argv)
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# CLI: _cmd_select_concerns exit codes and output
# ---------------------------------------------------------------------------


class TestCmdSelectConcerns(unittest.TestCase):
    def test_text_format_prints_one_guide_per_line(self) -> None:
        args = _make_args(paths=["src/foo.py"], format="text")
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _cmd_select_concerns(args)
        self.assertEqual(rc, 0)
        lines = [line for line in buf.getvalue().splitlines() if line.strip()]
        self.assertGreater(len(lines), 0)
        for line in lines:
            self.assertTrue(line.endswith(".md"), f"unexpected line: {line!r}")

    def test_json_format_returns_guides_and_matched(self) -> None:
        args = _make_args(paths=["src/foo.py"], format="json")
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _cmd_select_concerns(args)
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("guides", data)
        self.assertIn("matched", data)
        self.assertIsInstance(data["guides"], list)
        self.assertIsInstance(data["matched"], dict)

    def test_missing_paths_file_returns_exit_1(self) -> None:
        args = _make_args(paths_file="/tmp/does-not-exist-abcdef.txt")  # nosec B108 - test path
        import io
        from contextlib import redirect_stderr

        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = _cmd_select_concerns(args)
        self.assertEqual(rc, 1)

    def test_paths_file_is_read(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("src/foo.py\n")
            fh.write("workflows/bar.yaml\n")
            tmp_path = fh.name

        import io
        from contextlib import redirect_stdout

        try:
            args = _make_args(paths_file=tmp_path, format="json")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = _cmd_select_concerns(args)
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertIn("correctness.md", data["guides"])
            self.assertIn("workflow.md", data["guides"])
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_task_type_passed_through(self) -> None:
        args = _make_args(task_type="security", format="json")
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _cmd_select_concerns(args)
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("security.md", data["guides"])

    def test_no_paths_no_task_type_returns_defaults(self) -> None:
        args = _make_args(format="json")
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _cmd_select_concerns(args)
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("correctness.md", data["guides"])
        self.assertIn("patterns.md", data["guides"])


class TestCmdSelectConcernsPathsFileErrors(unittest.TestCase):
    """--paths-file I/O and decode errors must return exit 1, not raise.

    Covers the documented contract in _cmd_select_concerns's docstring:
    "Exit codes: 0 success, 1 on I/O or parse error."
    """

    def test_non_utf8_paths_file_returns_exit_1(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fh:
            fh.write(b"src/foo.py\n\xff\xfe not valid utf-8 \x80\x81\n")
            tmp_path = fh.name

        import io
        from contextlib import redirect_stderr

        try:
            args = _make_args(paths_file=tmp_path, format="json")
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = _cmd_select_concerns(args)
            self.assertEqual(rc, 1)
            self.assertIn("select-concerns: paths-file unreadable", buf.getvalue())
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_unreadable_paths_file_returns_exit_1(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("src/foo.py\n")
            tmp_path = fh.name
        Path(tmp_path).chmod(0o000)

        import io
        from contextlib import redirect_stderr

        try:
            args = _make_args(paths_file=tmp_path, format="json")
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = _cmd_select_concerns(args)
            self.assertEqual(rc, 1)
            self.assertIn("select-concerns: paths-file unreadable", buf.getvalue())
        finally:
            Path(tmp_path).chmod(0o644)
            Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Unknown task_type CLI exit codes
# ---------------------------------------------------------------------------


class TestUnknownTaskTypeCLI(unittest.TestCase):
    def test_cli_exits_2_listing_valid_types_without_echoing_the_value(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = _cmd_select_concerns(_make_args(task_type="features$(id)"))
        self.assertEqual(rc, 2)
        message = err.getvalue()
        for task_type in valid_task_types():
            self.assertIn(task_type, message)
        self.assertNotIn("$(id)", message)

    def test_cli_accepts_every_valid_type(self) -> None:
        for task_type in valid_task_types():
            with self.subTest(task_type=task_type):
                out = io.StringIO()
                with redirect_stdout(out):
                    rc = _cmd_select_concerns(_make_args(task_type=task_type, format="json"))
                self.assertEqual(rc, 0)
                self.assertTrue(json.loads(out.getvalue())["guides"])


# ---------------------------------------------------------------------------
# CLI: stdin paths-file and a missing rules file
# ---------------------------------------------------------------------------


class TestCmdSelectConcernsStdinAndMissingRules(unittest.TestCase):
    def test_paths_file_dash_reads_stdin(self) -> None:
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("src/a.py\nworkflows/b.yaml\n")), \
                redirect_stdout(out):
            rc = _cmd_select_concerns(_make_args(paths_file="-", format="json"))
        self.assertEqual(rc, 0)
        guides = json.loads(out.getvalue())["guides"]
        self.assertIn("correctness.md", guides)
        self.assertIn("workflow.md", guides)

    def test_missing_rules_file_is_one_line_exit_1(self) -> None:
        missing = Path(tempfile.gettempdir()) / "no-such-checkout" / "concerns" / "selection.yaml"
        concern_select._load_rules.cache_clear()
        self.addCleanup(concern_select._load_rules.cache_clear)
        err = io.StringIO()
        with mock.patch.object(concern_select, "_SELECTION_YAML", missing), \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = _cmd_select_concerns(_make_args(paths=["src/a.py"]))
        self.assertEqual(rc, 1)
        lines = err.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1, err.getvalue())
        self.assertIn(str(missing), lines[0])
        self.assertIn("repository checkout", lines[0])
        self.assertNotIn("Traceback", err.getvalue())

    def test_missing_rules_file_raises_the_named_error(self) -> None:
        missing = Path(tempfile.gettempdir()) / "no-such-checkout" / "selection.yaml"
        concern_select._load_rules.cache_clear()
        self.addCleanup(concern_select._load_rules.cache_clear)
        with mock.patch.object(concern_select, "_SELECTION_YAML", missing), \
                self.assertRaises(SelectionRulesNotFoundError):
            select_guides(paths=["src/a.py"])


# ---------------------------------------------------------------------------
# End to end: registration and argparse wiring, not a hand-built Namespace
# ---------------------------------------------------------------------------


class TestSelectConcernsThroughMain(unittest.TestCase):
    def test_paths_json(self) -> None:
        rc, out, _ = _run_main(["select-concerns", "--paths", "src/a.py", "--format", "json"])
        self.assertEqual(rc, 0)
        self.assertIn("correctness.md", json.loads(out)["guides"])

    def test_separator_form_the_workflow_engine_emits(self) -> None:
        rc, out, _ = _run_main(["select-concerns", "--", "--paths", "src/a.py", "--format", "json"])
        self.assertEqual(rc, 0)
        self.assertIn("correctness.md", json.loads(out)["guides"])

    def test_paths_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "paths.txt"
            pf.write_text("workflows/x.yaml\n", encoding="utf-8")
            rc, out, _ = _run_main(["select-concerns", "--paths-file", str(pf), "--format", "json"])
        self.assertEqual(rc, 0)
        self.assertIn("workflow-stages.md", json.loads(out)["guides"])

    def test_unknown_task_type_exits_2(self) -> None:
        rc, _, err = _run_main(["select-concerns", "--task-type", "features"])
        self.assertEqual(rc, 2)
        self.assertIn("valid types", err)


class TestSelectConcernsWrapper(unittest.TestCase):
    """Run the real ./bin/workflow wrapper with PYTHONPATH unset."""

    def _run(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        return subprocess.run(  # nosec B603 - fixed argv, repo-owned wrapper
            [str(_REPO_ROOT / "bin" / "workflow"), "select-concerns", *args],
            cwd=_REPO_ROOT, env=env, input=stdin, capture_output=True,
            text=True, timeout=60, check=False,
        )

    def test_paths_json(self) -> None:
        proc = self._run("--paths", "src/a.py", "workflows/b.yaml", "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("correctness.md", data["guides"])
        self.assertIn("workflow.md", data["guides"])
        self.assertEqual(set(data["matched"]), set(data["guides"]))

    def test_paths_file_and_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "paths.txt"
            pf.write_text("src/a.py\n", encoding="utf-8")
            from_file = self._run("--paths-file", str(pf), "--format", "json")
        from_stdin = self._run("--paths-file", "-", "--format", "json", stdin="src/a.py\n")
        self.assertEqual(from_file.returncode, 0, from_file.stderr)
        self.assertEqual(from_stdin.returncode, 0, from_stdin.stderr)
        self.assertEqual(json.loads(from_file.stdout), json.loads(from_stdin.stdout))

    def test_unknown_task_type_exits_2(self) -> None:
        proc = self._run("--task-type", "features")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("valid types", proc.stderr)


if __name__ == "__main__":
    unittest.main()
