"""Tests for workflow.worktree_gate and the snapshot-dirty / check-unlisted CLI.

The gate exists because commit-and-push stages exactly fix-results.json's
files_changed: on the first live run of review-fix-threads a fixer's test file
was missing from that list, and nothing noticed.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess  # nosec B404 - drives a throwaway git repo in a temp dir
import tempfile
import unittest
from pathlib import Path

from workflow.cli_dispatch import _cmd_check_unlisted, _cmd_snapshot_dirty
from workflow.worktree_gate import parse_porcelain_z, snapshot_dirty, unlisted_changes


class TestParsePorcelainZ(unittest.TestCase):
    def test_modified_and_untracked(self) -> None:
        self.assertEqual(parse_porcelain_z(" M src/a.py\0?? tests/test_a.py\0"),
                         {"src/a.py", "tests/test_a.py"})

    def test_rename_yields_both_paths(self) -> None:
        """The origin is a separate NUL field; skipping it would misread it as
        an entry and drop its first three characters."""
        self.assertEqual(parse_porcelain_z("R  new.py\0old.py\0 M x.py\0"),
                         {"new.py", "old.py", "x.py"})

    def test_paths_with_spaces_are_kept_whole(self) -> None:
        self.assertEqual(parse_porcelain_z("?? a dir/b c.py\0"), {"a dir/b c.py"})

    def test_empty_output(self) -> None:
        self.assertEqual(parse_porcelain_z(""), set())


class TestUnlistedChanges(unittest.TestCase):
    def test_new_unlisted_file_is_reported(self) -> None:
        self.assertEqual(unlisted_changes({}, {"src/a.py": "1", "tests/t.py": "2"}, ["src/a.py"]),
                         ["tests/t.py"])

    def test_preexisting_dirt_from_another_session_is_ignored(self) -> None:
        self.assertEqual(unlisted_changes({"notes.md": "1"}, {"notes.md": "1"}, []), [])

    def test_preexisting_dirt_edited_again_is_reported(self) -> None:
        """Already dirty is not a licence: a changed hash means this run touched it."""
        self.assertEqual(unlisted_changes({"notes.md": "1"}, {"notes.md": "2"}, []), ["notes.md"])

    def test_reverted_file_is_reported(self) -> None:
        self.assertEqual(unlisted_changes({"notes.md": "1"}, {}, []), ["notes.md"])

    def test_dot_slash_listing_matches(self) -> None:
        self.assertEqual(unlisted_changes({}, {"src/a.py": "1"}, ["./src/a.py"]), [])


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # nosec B603 B607 - fixed argv, temp repo


class _Repo(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        self.repo.mkdir()
        self.ws = Path(tmp.name) / "ws"
        self.ws.mkdir()
        _git(self.repo, "init", "-q")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "init")
        (self.repo / "src").mkdir()
        (self.repo / "src/a.py").write_text("a = 1\n")
        _git(self.repo, "add", "src/a.py")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "a")
        self.enterContext(contextlib.chdir(self.repo))

    def _run_cmd(self, func, **kwargs: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = func(argparse.Namespace(**kwargs))
        return rc, out.getvalue(), err.getvalue()

    def _snapshot(self) -> Path:
        path = self.ws / "baseline.json"
        rc, _, err = self._run_cmd(_cmd_snapshot_dirty, out=str(path))
        self.assertEqual(rc, 0, err)
        return path

    def _results(self, files: object) -> Path:
        path = self.ws / "fix-results.json"
        path.write_text(json.dumps({"files_changed": files}))
        return path


class TestCheckUnlistedCLI(_Repo):
    def test_fix_without_its_test_file_fails(self) -> None:
        """The dry-run shape: src listed, test file edited but not listed."""
        baseline = self._snapshot()
        (self.repo / "src/a.py").write_text("a = 2\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_a.py").write_text("pass\n")
        rc, out, _ = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                   fix_results=str(self._results(["src/a.py"])))
        self.assertEqual((rc, out), (1, "UNLISTED: tests/test_a.py\n"))

    def test_every_edit_listed_passes(self) -> None:
        baseline = self._snapshot()
        (self.repo / "src/a.py").write_text("a = 2\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_a.py").write_text("pass\n")
        rc, out, _ = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                   fix_results=str(self._results(["src/a.py", "tests/test_a.py"])))
        self.assertEqual((rc, out), (0, ""))

    def test_other_sessions_untouched_dirt_passes(self) -> None:
        (self.repo / "scratch.txt").write_text("someone else's\n")
        baseline = self._snapshot()
        (self.repo / "src/a.py").write_text("a = 2\n")
        rc, _, _ = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                 fix_results=str(self._results(["src/a.py"])))
        self.assertEqual(rc, 0)

    def test_unlisted_protected_edit_is_reported(self) -> None:
        """An edit that skipped the list would also have skipped check-paths."""
        baseline = self._snapshot()
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude/settings.json").write_text("{}\n")
        rc, out, _ = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                   fix_results=str(self._results([])))
        self.assertEqual((rc, out), (1, "UNLISTED: .claude/settings.json\n"))

    def test_bad_inputs_fail_closed(self) -> None:
        baseline = self._snapshot()
        cases = {
            "missing baseline": dict(baseline=str(self.ws / "nope.json"),
                                     fix_results=str(self._results([]))),
            "files_changed not a list": dict(baseline=str(baseline),
                                             fix_results=str(self._results("src/a.py"))),
            "files_changed holds a non-string": dict(baseline=str(baseline),
                                                     fix_results=str(self._results([1]))),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                rc, _, err = self._run_cmd(_cmd_check_unlisted, **kwargs)
                self.assertEqual(rc, 1)
                self.assertIn("check-unlisted:", err)

    def test_baseline_without_dirty_object_fails(self) -> None:
        bad = self.ws / "bad.json"
        bad.write_text(json.dumps({"paths": []}))
        rc, _, err = self._run_cmd(_cmd_check_unlisted, baseline=str(bad),
                                   fix_results=str(self._results([])))
        self.assertEqual(rc, 1)
        self.assertIn("no 'dirty' object", err)


class TestSnapshotOutsideRepo(unittest.TestCase):
    def test_git_failure_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                snapshot_dirty(tmp)
            with contextlib.chdir(tmp):
                err = io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    rc = _cmd_snapshot_dirty(argparse.Namespace(out=str(Path(tmp) / "b.json")))
            self.assertEqual(rc, 1)
            self.assertFalse((Path(tmp) / "b.json").exists())


if __name__ == "__main__":
    unittest.main()
