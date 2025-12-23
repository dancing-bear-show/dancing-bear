"""Tests for core/textio.py text IO helpers."""

import tempfile
import unittest
from pathlib import Path

from core.textio import read_text, write_text


class TestReadText(unittest.TestCase):
    """Tests for read_text function."""

    def test_read_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.txt"
            path.write_text("Hello, World!", encoding="utf-8")
            result = read_text(path)
            self.assertEqual(result, "Hello, World!")

    def test_read_missing_file_returns_default(self):
        path = Path("/nonexistent/path/file.txt")
        result = read_text(path)
        self.assertEqual(result, "")

    def test_read_missing_file_custom_default(self):
        path = Path("/nonexistent/path/file.txt")
        result = read_text(path, default="fallback")
        self.assertEqual(result, "fallback")

    def test_read_missing_file_none_default(self):
        path = Path("/nonexistent/path/file.txt")
        result = read_text(path, default=None)
        self.assertIsNone(result)

    def test_read_utf8_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unicode.txt"
            path.write_text("日本語テスト", encoding="utf-8")
            result = read_text(path)
            self.assertEqual(result, "日本語テスト")

    def test_read_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.txt"
            path.write_text("", encoding="utf-8")
            result = read_text(path)
            self.assertEqual(result, "")

    def test_read_multiline_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multi.txt"
            content = "Line 1\nLine 2\nLine 3"
            path.write_text(content, encoding="utf-8")
            result = read_text(path)
            self.assertEqual(result, content)


class TestWriteText(unittest.TestCase):
    """Tests for write_text function."""

    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output.txt"
            write_text(path, "Test content")
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "Test content")

    def test_write_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "dir" / "file.txt"
            write_text(path, "Nested content")
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "Nested content")

    def test_write_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.txt"
            path.write_text("Original", encoding="utf-8")
            write_text(path, "Updated")
            self.assertEqual(path.read_text(encoding="utf-8"), "Updated")

    def test_write_utf8_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unicode.txt"
            content = "Ελληνικά 中文 العربية"
            write_text(path, content)
            self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_write_empty_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.txt"
            write_text(path, "")
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
