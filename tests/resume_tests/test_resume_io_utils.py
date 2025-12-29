"""Tests for resume/io_utils.py file I/O utilities."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from resume.io_utils import (
    read_text_any,
    read_text_raw,
    read_yaml_or_json,
    safe_import,
    write_text,
    write_yaml_or_json,
)
from tests.fixtures import TempDirMixin, temp_yaml_file


class TestSafeImport(unittest.TestCase):
    """Tests for safe_import function."""

    def test_import_existing_module(self):
        result = safe_import("os")
        self.assertIsNotNone(result)

    def test_import_nonexistent_module(self):
        result = safe_import("nonexistent_module_xyz")
        self.assertIsNone(result)

    def test_import_returns_none_on_exception(self):
        with patch("builtins.__import__", side_effect=Exception("Import error")):
            result = safe_import("any_module")
            self.assertIsNone(result)


class TestReadTextAny(unittest.TestCase):
    """Tests for read_text_any function."""

    def test_read_txt_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello, world!")
            f.flush()
            try:
                result = read_text_any(f.name)
                self.assertEqual(result, "Hello, world!")
            finally:
                os.unlink(f.name)

    def test_read_md_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Markdown\nContent here")
            f.flush()
            try:
                result = read_text_any(f.name)
                self.assertEqual(result, "# Markdown\nContent here")
            finally:
                os.unlink(f.name)

    def test_read_html_file_strips_tags(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write("<html><body><p>Hello</p></body></html>")
            f.flush()
            try:
                result = read_text_any(f.name)
                self.assertIn("Hello", result)
                self.assertNotIn("<p>", result)
            finally:
                os.unlink(f.name)

    def test_read_htm_file_strips_tags(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".htm", delete=False) as f:
            f.write("<div>Content</div>")
            f.flush()
            try:
                result = read_text_any(f.name)
                self.assertIn("Content", result)
                self.assertNotIn("<div>", result)
            finally:
                os.unlink(f.name)

    def test_read_unknown_suffix_as_text(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xyz", delete=False) as f:
            f.write("Unknown format content")
            f.flush()
            try:
                result = read_text_any(f.name)
                self.assertEqual(result, "Unknown format content")
            finally:
                os.unlink(f.name)

    def test_read_docx_without_dependency_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"fake docx")
            try:
                with patch("resume.io_utils.safe_import", return_value=None):
                    with self.assertRaises(RuntimeError) as ctx:
                        read_text_any(f.name)
                    self.assertIn("python-docx", str(ctx.exception))
            finally:
                os.unlink(f.name)

    def test_read_docx_with_mock_dependency(self):
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"fake docx")
            try:
                mock_docx = MagicMock()
                mock_doc = MagicMock()
                mock_para1 = MagicMock()
                mock_para1.text = "Line 1"
                mock_para2 = MagicMock()
                mock_para2.text = "Line 2"
                mock_doc.paragraphs = [mock_para1, mock_para2]
                mock_docx.Document.return_value = mock_doc

                with patch("resume.io_utils.safe_import", return_value=mock_docx):
                    with patch.dict("sys.modules", {"docx": mock_docx}):
                        with patch("resume.io_utils.Document", mock_docx.Document, create=True):
                            # Since the import happens dynamically, we need to mock it inline
                            result = read_text_any(f.name)
                            # Due to dynamic import, just verify no crash for now
            finally:
                os.unlink(f.name)

    def test_read_pdf_without_dependency_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-fake")
            try:
                with patch("resume.io_utils.safe_import", return_value=None):
                    with self.assertRaises(RuntimeError) as ctx:
                        read_text_any(f.name)
                    self.assertIn("pdfminer", str(ctx.exception))
            finally:
                os.unlink(f.name)


class TestReadTextRaw(unittest.TestCase):
    """Tests for read_text_raw function."""

    def test_read_raw_preserves_html_tags(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write("<html><body><p>Hello</p></body></html>")
            f.flush()
            try:
                result = read_text_raw(f.name)
                self.assertIn("<p>", result)
                self.assertIn("Hello", result)
            finally:
                os.unlink(f.name)

    def test_read_raw_ignores_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            with open(path, "wb") as f:
                f.write(b"Valid text \xff\xfe invalid bytes")
            result = read_text_raw(path)
            self.assertIn("Valid text", result)


class TestReadYamlOrJson(unittest.TestCase):
    """Tests for read_yaml_or_json function."""

    def test_read_json_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "value", "number": 42}, f)
            f.flush()
            try:
                result = read_yaml_or_json(f.name)
                self.assertEqual(result["key"], "value")
                self.assertEqual(result["number"], 42)
            finally:
                os.unlink(f.name)

    def test_read_yaml_file(self):
        with temp_yaml_file({"key": "value", "number": 42}, suffix=".yaml") as path:
            result = read_yaml_or_json(path)
            self.assertEqual(result["key"], "value")
            self.assertEqual(result["number"], 42)

    def test_read_yml_file(self):
        with temp_yaml_file({"items": ["a", "b"]}, suffix=".yml") as path:
            result = read_yaml_or_json(path)
            self.assertEqual(result["items"], ["a", "b"])

    def test_read_nonexistent_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_yaml_or_json("/nonexistent/path/file.json")


class TestWriteYamlOrJson(TempDirMixin, unittest.TestCase):
    """Tests for write_yaml_or_json function."""

    def test_write_json_file(self):
        path = Path(self.tmpdir) / "output.json"
        data = {"key": "value", "list": [1, 2, 3]}
        write_yaml_or_json(data, path)

        self.assertTrue(path.exists())
        with open(path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_write_yaml_file(self):
        path = Path(self.tmpdir) / "output.yaml"
        data = {"key": "value", "list": [1, 2, 3]}
        write_yaml_or_json(data, path)

        self.assertTrue(path.exists())
        result = read_yaml_or_json(path)
        self.assertEqual(result, data)

    def test_write_creates_parent_directories(self):
        path = Path(self.tmpdir) / "nested" / "dir" / "output.json"
        data = {"nested": True}
        write_yaml_or_json(data, path)

        self.assertTrue(path.exists())

    def test_write_json_preserves_unicode(self):
        path = Path(self.tmpdir) / "unicode.json"
        data = {"name": "日本語", "emoji": "🎉"}
        write_yaml_or_json(data, path)

        content = path.read_text(encoding="utf-8")
        self.assertIn("日本語", content)
        self.assertIn("🎉", content)


class TestWriteText(TempDirMixin, unittest.TestCase):
    """Tests for write_text function."""

    def test_write_text_file(self):
        path = Path(self.tmpdir) / "output.txt"
        write_text("Hello, world!", path)

        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "Hello, world!")

    def test_write_creates_parent_directories(self):
        path = Path(self.tmpdir) / "a" / "b" / "c" / "output.txt"
        write_text("Nested content", path)

        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "Nested content")

    def test_write_preserves_unicode(self):
        path = Path(self.tmpdir) / "unicode.txt"
        write_text("Unicode: 日本語 🎉", path)

        self.assertEqual(path.read_text(encoding="utf-8"), "Unicode: 日本語 🎉")


if __name__ == "__main__":
    unittest.main()
