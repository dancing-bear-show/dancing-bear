"""Tests for resume/cleanup.py file management utilities."""

from __future__ import annotations

import os
import time
import unittest
from pathlib import Path

from tests.fixtures import TempDirMixin

from resume.cleanup import (
    TidyPlan,
    _match_files,
    build_tidy_plan,
    execute_archive,
    execute_delete,
    purge_temp_files,
)


class TestTidyPlan(unittest.TestCase):
    """Tests for TidyPlan dataclass."""

    def test_creation(self):
        plan = TidyPlan(keep=[Path("a.txt")], move=[Path("b.txt")], archive_dir=Path("archive"))
        self.assertEqual(plan.keep, [Path("a.txt")])
        self.assertEqual(plan.move, [Path("b.txt")])
        self.assertEqual(plan.archive_dir, Path("archive"))


class TestMatchFiles(TempDirMixin, unittest.TestCase):
    """Tests for _match_files function."""

    def setUp(self):
        super().setUp()
        # Create test files
        Path(self.tmpdir, "resume_v1.docx").touch()
        Path(self.tmpdir, "resume_v2.docx").touch()
        Path(self.tmpdir, "resume_v3.pdf").touch()
        Path(self.tmpdir, "cover_letter.docx").touch()
        Path(self.tmpdir, "notes.txt").touch()

    def test_match_by_prefix(self):
        result = _match_files(Path(self.tmpdir), "resume", None)
        names = [p.name for p in result]
        self.assertIn("resume_v1.docx", names)
        self.assertIn("resume_v2.docx", names)
        self.assertIn("resume_v3.pdf", names)
        self.assertNotIn("cover_letter.docx", names)

    def test_match_by_suffix(self):
        result = _match_files(Path(self.tmpdir), None, [".docx"])
        names = [p.name for p in result]
        self.assertIn("resume_v1.docx", names)
        self.assertIn("cover_letter.docx", names)
        self.assertNotIn("resume_v3.pdf", names)

    def test_match_by_prefix_and_suffix(self):
        result = _match_files(Path(self.tmpdir), "resume", [".docx"])
        names = [p.name for p in result]
        self.assertIn("resume_v1.docx", names)
        self.assertIn("resume_v2.docx", names)
        self.assertNotIn("resume_v3.pdf", names)

    def test_match_all_files(self):
        result = _match_files(Path(self.tmpdir), None, None)
        self.assertEqual(len(result), 5)

    def test_case_insensitive_prefix(self):
        result = _match_files(Path(self.tmpdir), "RESUME", None)
        names = [p.name for p in result]
        self.assertIn("resume_v1.docx", names)

    def test_case_insensitive_suffix(self):
        result = _match_files(Path(self.tmpdir), None, [".DOCX"])
        names = [p.name for p in result]
        self.assertIn("resume_v1.docx", names)


class TestBuildTidyPlan(TempDirMixin, unittest.TestCase):
    """Tests for build_tidy_plan function."""

    def setUp(self):
        super().setUp()
        # Create files with different mtimes
        for i, name in enumerate(["old.txt", "medium.txt", "new.txt"]):
            p = Path(self.tmpdir, name)
            p.touch()
            # Set mtime to ensure ordering
            os.utime(p, (time.time() - (3 - i) * 100, time.time() - (3 - i) * 100))

    def test_keeps_newest_files(self):
        plan = build_tidy_plan(self.tmpdir, keep=2)
        keep_names = [p.name for p in plan.keep]
        move_names = [p.name for p in plan.move]
        self.assertEqual(len(plan.keep), 2)
        self.assertEqual(len(plan.move), 1)
        self.assertIn("new.txt", keep_names)
        self.assertIn("medium.txt", keep_names)
        self.assertIn("old.txt", move_names)

    def test_default_archive_dir(self):
        plan = build_tidy_plan(self.tmpdir)
        self.assertEqual(plan.archive_dir, Path(self.tmpdir) / "archive")

    def test_custom_archive_dir(self):
        plan = build_tidy_plan(self.tmpdir, archive_dir="/custom/archive")
        self.assertEqual(plan.archive_dir, Path("/custom/archive"))

    def test_keep_zero(self):
        plan = build_tidy_plan(self.tmpdir, keep=0)
        self.assertEqual(len(plan.keep), 0)
        self.assertEqual(len(plan.move), 3)

    def test_keep_more_than_available(self):
        plan = build_tidy_plan(self.tmpdir, keep=10)
        self.assertEqual(len(plan.keep), 3)
        self.assertEqual(len(plan.move), 0)


class TestExecuteArchive(TempDirMixin, unittest.TestCase):
    """Tests for execute_archive function."""

    def setUp(self):
        super().setUp()
        self.file1 = Path(self.tmpdir, "file1.txt")
        self.file2 = Path(self.tmpdir, "file2.txt")
        self.file1.write_text("content1")
        self.file2.write_text("content2")
        self.archive = Path(self.tmpdir, "archive")

    def test_moves_files_to_archive(self):
        plan = TidyPlan(keep=[], move=[self.file1, self.file2], archive_dir=self.archive)
        moved = execute_archive(plan)
        self.assertEqual(len(moved), 2)
        self.assertFalse(self.file1.exists())
        self.assertFalse(self.file2.exists())
        self.assertTrue((self.archive / "file1.txt").exists())

    def test_creates_archive_dir(self):
        plan = TidyPlan(keep=[], move=[self.file1], archive_dir=self.archive)
        execute_archive(plan)
        self.assertTrue(self.archive.exists())

    def test_subfolder(self):
        plan = TidyPlan(keep=[], move=[self.file1], archive_dir=self.archive)
        moved = execute_archive(plan, subfolder="2024")
        self.assertTrue((self.archive / "2024").exists())
        self.assertTrue((self.archive / "2024" / "file1.txt").exists())

    def test_handles_duplicate_names(self):
        # Create existing file in archive
        self.archive.mkdir()
        (self.archive / "file1.txt").write_text("existing")
        plan = TidyPlan(keep=[], move=[self.file1], archive_dir=self.archive)
        moved = execute_archive(plan)
        # Should create file1.1.txt
        self.assertTrue((self.archive / "file1.1.txt").exists())


class TestExecuteDelete(TempDirMixin, unittest.TestCase):
    """Tests for execute_delete function."""

    def setUp(self):
        super().setUp()
        self.file1 = Path(self.tmpdir, "file1.txt")
        self.file2 = Path(self.tmpdir, "file2.txt")
        self.file1.write_text("content1")
        self.file2.write_text("content2")

    def test_deletes_files(self):
        plan = TidyPlan(keep=[], move=[self.file1, self.file2], archive_dir=Path(self.tmpdir))
        deleted = execute_delete(plan)
        self.assertEqual(len(deleted), 2)
        self.assertFalse(self.file1.exists())
        self.assertFalse(self.file2.exists())

    def test_handles_missing_files(self):
        missing = Path(self.tmpdir, "missing.txt")
        plan = TidyPlan(keep=[], move=[missing], archive_dir=Path(self.tmpdir))
        deleted = execute_delete(plan)
        self.assertEqual(len(deleted), 0)


class TestPurgeTempFiles(TempDirMixin, unittest.TestCase):
    """Tests for purge_temp_files function."""

    def setUp(self):
        super().setUp()
        # Create temp files
        Path(self.tmpdir, "~$resume.docx").touch()
        Path(self.tmpdir, ".DS_Store").touch()
        Path(self.tmpdir, "normal.txt").touch()
        # Create subdir with temp files
        subdir = Path(self.tmpdir, "subdir")
        subdir.mkdir()
        Path(subdir, "~$other.docx").touch()

    def test_removes_tilde_dollar_files(self):
        removed = purge_temp_files(self.tmpdir)
        names = [p.name for p in removed]
        self.assertIn("~$resume.docx", names)
        self.assertFalse(Path(self.tmpdir, "~$resume.docx").exists())

    def test_removes_ds_store(self):
        removed = purge_temp_files(self.tmpdir)
        names = [p.name for p in removed]
        self.assertIn(".DS_Store", names)

    def test_keeps_normal_files(self):
        purge_temp_files(self.tmpdir)
        self.assertTrue(Path(self.tmpdir, "normal.txt").exists())

    def test_recursive_removal(self):
        removed = purge_temp_files(self.tmpdir)
        names = [p.name for p in removed]
        self.assertIn("~$other.docx", names)


if __name__ == "__main__":
    unittest.main()
