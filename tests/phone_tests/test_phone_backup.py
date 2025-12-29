"""Tests for phone/backup.py iOS backup file utilities."""

import os
import plistlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from phone.backup import (
    IconStateFile,
    _manifest_select,
    find_iconstate_file,
    find_latest_backup_dir,
    load_plist,
)


class TestIconStateFile(unittest.TestCase):
    """Tests for IconStateFile dataclass."""

    def test_iconstate_file_creation(self):
        isf = IconStateFile(path=Path("/path/to/file"), desc="test description")
        self.assertEqual(isf.path, Path("/path/to/file"))
        self.assertEqual(isf.desc, "test description")


class TestFindLatestBackupDir(unittest.TestCase):
    """Tests for find_latest_backup_dir function."""

    def test_returns_none_when_directory_does_not_exist(self):
        result = find_latest_backup_dir(Path("/nonexistent/path"))
        self.assertIsNone(result)

    def test_returns_none_when_directory_is_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = find_latest_backup_dir(Path(tmpdir))
            self.assertIsNone(result)

    def test_returns_none_when_only_files_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file, not a directory
            (Path(tmpdir) / "somefile.txt").touch()
            result = find_latest_backup_dir(Path(tmpdir))
            self.assertIsNone(result)

    def test_returns_most_recent_by_dir_mtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two backup directories
            dir1 = Path(tmpdir) / "backup1"
            dir2 = Path(tmpdir) / "backup2"
            dir1.mkdir()
            dir2.mkdir()

            # Set different mtimes by touching with delay
            os.utime(dir1, (1000, 1000))
            os.utime(dir2, (2000, 2000))

            result = find_latest_backup_dir(Path(tmpdir))
            self.assertEqual(result, dir2)

    def test_prefers_manifest_db_mtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dir1 = Path(tmpdir) / "backup1"
            dir2 = Path(tmpdir) / "backup2"
            dir1.mkdir()
            dir2.mkdir()

            # Create Manifest.db only in dir1
            manifest1 = dir1 / "Manifest.db"
            manifest1.touch()

            # Set dir2 as more recent by dir mtime
            os.utime(dir1, (1000, 1000))
            os.utime(manifest1, (3000, 3000))  # But manifest is newest
            os.utime(dir2, (2000, 2000))

            result = find_latest_backup_dir(Path(tmpdir))
            self.assertEqual(result, dir1)


class TestManifestSelect(unittest.TestCase):
    """Tests for _manifest_select function."""

    def test_executes_query_and_returns_rows(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        try:
            # Create a test database
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE test (id INTEGER, name TEXT)")
            conn.execute("INSERT INTO test VALUES (1, 'Alice')")
            conn.execute("INSERT INTO test VALUES (2, 'Bob')")
            conn.commit()
            conn.close()

            rows = _manifest_select(db_path, "SELECT * FROM test WHERE id = ?", (1,))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "Alice")
        finally:
            os.unlink(db_path)

    def test_returns_empty_list_for_no_matches(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        try:
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.commit()
            conn.close()

            rows = _manifest_select(db_path, "SELECT * FROM test WHERE id = ?", (999,))
            self.assertEqual(len(rows), 0)
        finally:
            os.unlink(db_path)


class TestFindIconstateFile(unittest.TestCase):
    """Tests for find_iconstate_file function."""

    def test_returns_none_when_manifest_db_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = find_iconstate_file(Path(tmpdir))
            self.assertIsNone(result)

    def test_returns_none_when_no_iconstate_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir)
            db_path = backup_dir / "Manifest.db"

            # Create the database with Files table but no IconState entries
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE Files (
                    fileID TEXT,
                    domain TEXT,
                    relativePath TEXT
                )
            """)
            conn.execute("INSERT INTO Files VALUES ('abc123', 'HomeDomain', 'Library/Other/file.txt')")
            conn.commit()
            conn.close()

            result = find_iconstate_file(backup_dir)
            self.assertIsNone(result)

    def test_prefers_iconstate_ipad_plist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir)
            db_path = backup_dir / "Manifest.db"

            # Create the database with multiple IconState files
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE Files (
                    fileID TEXT,
                    domain TEXT,
                    relativePath TEXT
                )
            """)
            conn.execute("INSERT INTO Files VALUES ('aaa111', 'HomeDomain', 'Library/SpringBoard/IconState.plist')")
            conn.execute("INSERT INTO Files VALUES ('bbb222', 'HomeDomain', 'Library/SpringBoard/IconState~ipad.plist')")
            conn.execute("INSERT INTO Files VALUES ('ccc333', 'HomeDomain', 'Library/SpringBoard/DesiredIconState.plist')")
            conn.commit()
            conn.close()

            # Create the hashed file path
            hashed_dir = backup_dir / "bb"
            hashed_dir.mkdir()
            (hashed_dir / "bbb222").touch()

            result = find_iconstate_file(backup_dir)
            self.assertIsNotNone(result)
            self.assertEqual(result.desc, "Library/SpringBoard/IconState~ipad.plist")

    def test_falls_back_to_iconstate_plist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir)
            db_path = backup_dir / "Manifest.db"

            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE Files (
                    fileID TEXT,
                    domain TEXT,
                    relativePath TEXT
                )
            """)
            conn.execute("INSERT INTO Files VALUES ('aaa111', 'HomeDomain', 'Library/SpringBoard/IconState.plist')")
            conn.execute("INSERT INTO Files VALUES ('ccc333', 'HomeDomain', 'Library/SpringBoard/DesiredIconState.plist')")
            conn.commit()
            conn.close()

            # Create the hashed file path
            hashed_dir = backup_dir / "aa"
            hashed_dir.mkdir()
            (hashed_dir / "aaa111").touch()

            result = find_iconstate_file(backup_dir)
            self.assertIsNotNone(result)
            self.assertEqual(result.desc, "Library/SpringBoard/IconState.plist")

    def test_returns_none_when_hashed_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir)
            db_path = backup_dir / "Manifest.db"

            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE Files (
                    fileID TEXT,
                    domain TEXT,
                    relativePath TEXT
                )
            """)
            conn.execute("INSERT INTO Files VALUES ('aaa111', 'HomeDomain', 'Library/SpringBoard/IconState.plist')")
            conn.commit()
            conn.close()

            # Do NOT create the hashed file
            result = find_iconstate_file(backup_dir)
            self.assertIsNone(result)


class TestLoadPlist(unittest.TestCase):
    """Tests for load_plist function."""

    def test_loads_plist_file(self):
        with tempfile.NamedTemporaryFile(suffix=".plist", delete=False) as f:
            plist_path = Path(f.name)

        try:
            data = {"key": "value", "number": 42, "list": [1, 2, 3]}
            with open(plist_path, "wb") as f:
                plistlib.dump(data, f)

            result = load_plist(plist_path)
            self.assertEqual(result["key"], "value")
            self.assertEqual(result["number"], 42)
            self.assertEqual(result["list"], [1, 2, 3])
        finally:
            os.unlink(plist_path)

    def test_loads_complex_plist(self):
        with tempfile.NamedTemporaryFile(suffix=".plist", delete=False) as f:
            plist_path = Path(f.name)

        try:
            data = {
                "buttonBar": [{"bundleIdentifier": "com.apple.safari"}],
                "iconLists": [
                    [{"bundleIdentifier": "com.app1"}, {"bundleIdentifier": "com.app2"}]
                ],
            }
            with open(plist_path, "wb") as f:
                plistlib.dump(data, f)

            result = load_plist(plist_path)
            self.assertIn("buttonBar", result)
            self.assertIn("iconLists", result)
            self.assertEqual(result["buttonBar"][0]["bundleIdentifier"], "com.apple.safari")
        finally:
            os.unlink(plist_path)


if __name__ == "__main__":
    unittest.main()
