"""Tests for core.path_guard — repo-relative path safety guard."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.path_guard import PathGuardError, check_path_safe, main as path_guard_main


def _make_repo(tmp: Path) -> Path:
    """Create a minimal fake repo directory tree with a .git/ dir."""
    (tmp / ".git").mkdir()
    (tmp / "src").mkdir()
    (tmp / "src" / "real.py").write_text("# real\n")
    return tmp


class TestCheckPathSafe(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo = _make_repo(Path(self._tmpdir.name))

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    # --- safe case ---

    def test_safe_repo_file(self) -> None:
        """A normal file inside the repo must pass without raising."""
        check_path_safe(str(self.repo), "src/real.py")

    # --- syntactic pre-filter ---

    def test_absolute_path_refused(self) -> None:
        with self.assertRaises(PathGuardError) as ctx:
            check_path_safe(str(self.repo), "/etc/passwd")
        self.assertIn("absolute", str(ctx.exception))

    def test_dotdot_segment_refused(self) -> None:
        with self.assertRaises(PathGuardError) as ctx:
            check_path_safe(str(self.repo), "src/../../../etc/passwd")
        self.assertIn("..", str(ctx.exception))

    def test_dotdot_at_start_refused(self) -> None:
        with self.assertRaises(PathGuardError) as ctx:
            check_path_safe(str(self.repo), "../outside.txt")
        self.assertIn("..", str(ctx.exception))

    # --- .git/ guard ---

    def test_git_dir_file_refused(self) -> None:
        git_file = self.repo / ".git" / "config"
        git_file.write_text("[core]\n")
        with self.assertRaises(PathGuardError) as ctx:
            check_path_safe(str(self.repo), ".git/config")
        self.assertIn(".git", str(ctx.exception))

    # --- symlink escaping repo ---

    def test_symlink_outside_repo_refused(self) -> None:
        outside = Path(self._tmpdir.name).parent / "outside_target.txt"
        try:
            outside.write_text("secret\n")
            link = self.repo / "src" / "evil_link.py"
            link.symlink_to(outside)
            with self.assertRaises(PathGuardError) as ctx:
                check_path_safe(str(self.repo), "src/evil_link.py")
            self.assertIn("escapes repo root", str(ctx.exception))
        finally:
            if outside.exists():
                outside.unlink()

    # --- not a regular file ---

    def test_directory_refused(self) -> None:
        with self.assertRaises(PathGuardError) as ctx:
            check_path_safe(str(self.repo), "src")
        self.assertIn("not a regular file", str(ctx.exception))

    def test_nonexistent_refused(self) -> None:
        with self.assertRaises(PathGuardError) as ctx:
            check_path_safe(str(self.repo), "src/ghost.py")
        self.assertIn("does not exist", str(ctx.exception))


class TestPathGuardMain(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo = _make_repo(Path(self._tmpdir.name))

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_returns_0_for_safe_path(self) -> None:
        rc = path_guard_main([str(self.repo), "src/real.py"])
        self.assertEqual(rc, 0)

    def test_returns_1_for_absolute_path(self) -> None:
        rc = path_guard_main([str(self.repo), "/etc/passwd"])
        self.assertEqual(rc, 1)

    def test_returns_1_for_dotdot(self) -> None:
        rc = path_guard_main([str(self.repo), "src/../../etc/passwd"])
        self.assertEqual(rc, 1)

    def test_returns_1_for_git_dir(self) -> None:
        (self.repo / ".git" / "config").write_text("[core]\n")
        rc = path_guard_main([str(self.repo), ".git/config"])
        self.assertEqual(rc, 1)

    def test_returns_1_for_nonexistent(self) -> None:
        rc = path_guard_main([str(self.repo), "src/no_such.py"])
        self.assertEqual(rc, 1)

    def test_returns_1_for_directory(self) -> None:
        rc = path_guard_main([str(self.repo), "src"])
        self.assertEqual(rc, 1)

    def test_returns_2_on_usage_error(self) -> None:
        rc = path_guard_main([str(self.repo)])
        self.assertEqual(rc, 2)

    def test_returns_1_for_symlink_outside_repo(self) -> None:
        outside = Path(self._tmpdir.name).parent / "outside_main.txt"
        try:
            outside.write_text("secret\n")
            link = self.repo / "src" / "evil_main.py"
            link.symlink_to(outside)
            rc = path_guard_main([str(self.repo), "src/evil_main.py"])
            self.assertEqual(rc, 1)
        finally:
            if outside.exists():
                outside.unlink()
