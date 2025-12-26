"""Tests for resume/io_utils.py."""
import json
import tempfile
import unittest
from pathlib import Path

from resume.io_utils import (
    safe_import,
    read_text_any,
    read_text_raw,
    read_yaml_or_json,
    write_yaml_or_json,
    write_text,
)


class TestSafeImport(unittest.TestCase):
    """Tests for safe_import function."""

    def test_imports_existing_module(self):
        result = safe_import("os")
        self.assertIsNotNone(result)

    def test_imports_json_module(self):
        result = safe_import("json")
        self.assertIsNotNone(result)

    def test_returns_none_for_nonexistent(self):
        result = safe_import("nonexistent_module_xyz_123")
        self.assertIsNone(result)

    def test_returns_none_for_import_error(self):
        # An invalid module name that would cause import error
        result = safe_import("...invalid...")
        self.assertIsNone(result)


class TestReadTextAny(unittest.TestCase):
    """Tests for read_text_any function."""

    def test_reads_txt_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello World")
            path = f.name
        try:
            result = read_text_any(path)
            self.assertEqual(result, "Hello World")
        finally:
            Path(path).unlink()

    def test_reads_md_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Heading\n\nParagraph text")
            path = f.name
        try:
            result = read_text_any(path)
            self.assertIn("Heading", result)
            self.assertIn("Paragraph", result)
        finally:
            Path(path).unlink()

    def test_strips_html_tags(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write("<html><body><p>Hello</p></body></html>")
            path = f.name
        try:
            result = read_text_any(path)
            self.assertIn("Hello", result)
            self.assertNotIn("<p>", result)
            self.assertNotIn("</p>", result)
        finally:
            Path(path).unlink()

    def test_reads_htm_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".htm", delete=False) as f:
            f.write("<div>Content</div>")
            path = f.name
        try:
            result = read_text_any(path)
            self.assertIn("Content", result)
        finally:
            Path(path).unlink()

    def test_fallback_to_text(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xyz", delete=False) as f:
            f.write("Unknown extension content")
            path = f.name
        try:
            result = read_text_any(path)
            self.assertEqual(result, "Unknown extension content")
        finally:
            Path(path).unlink()


class TestReadTextRaw(unittest.TestCase):
    """Tests for read_text_raw function."""

    def test_reads_without_transformation(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write("<html><body>Raw content</body></html>")
            path = f.name
        try:
            result = read_text_raw(path)
            # Should NOT strip HTML tags
            self.assertIn("<html>", result)
            self.assertIn("</body>", result)
        finally:
            Path(path).unlink()

    def test_preserves_whitespace(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("  indented\n\n\nmultiple lines  ")
            path = f.name
        try:
            result = read_text_raw(path)
            self.assertEqual(result, "  indented\n\n\nmultiple lines  ")
        finally:
            Path(path).unlink()


class TestReadYamlOrJson(unittest.TestCase):
    """Tests for read_yaml_or_json function."""

    def test_reads_yaml_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("name: John\nage: 30\n")
            path = f.name
        try:
            result = read_yaml_or_json(path)
            self.assertEqual(result["name"], "John")
            self.assertEqual(result["age"], 30)
        finally:
            Path(path).unlink()

    def test_reads_yml_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("items:\n  - one\n  - two\n")
            path = f.name
        try:
            result = read_yaml_or_json(path)
            self.assertEqual(result["items"], ["one", "two"])
        finally:
            Path(path).unlink()

    def test_reads_json_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "value", "num": 42}, f)
            path = f.name
        try:
            result = read_yaml_or_json(path)
            self.assertEqual(result["key"], "value")
            self.assertEqual(result["num"], 42)
        finally:
            Path(path).unlink()

    def test_raises_for_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            read_yaml_or_json("/nonexistent/path/file.yaml")


class TestWriteYamlOrJson(unittest.TestCase):
    """Tests for write_yaml_or_json function."""

    def test_writes_yaml_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "output.yaml"
            data = {"name": "Test", "items": [1, 2, 3]}
            write_yaml_or_json(data, path)

            self.assertTrue(path.exists())
            result = read_yaml_or_json(path)
            self.assertEqual(result["name"], "Test")
            self.assertEqual(result["items"], [1, 2, 3])

    def test_writes_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "output.json"
            data = {"key": "value"}
            write_yaml_or_json(data, path)

            self.assertTrue(path.exists())
            content = path.read_text()
            parsed = json.loads(content)
            self.assertEqual(parsed["key"], "value")

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "deep" / "output.yaml"
            write_yaml_or_json({"test": True}, path)

            self.assertTrue(path.exists())

    def test_writes_unicode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "unicode.json"
            data = {"name": "日本語テスト", "emoji": "🚀"}
            write_yaml_or_json(data, path)

            result = read_yaml_or_json(path)
            self.assertEqual(result["name"], "日本語テスト")
            self.assertEqual(result["emoji"], "🚀")


class TestWriteText(unittest.TestCase):
    """Tests for write_text function."""

    def test_writes_text_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "output.txt"
            write_text("Hello, World!", path)

            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(), "Hello, World!")

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "a" / "b" / "c" / "file.txt"
            write_text("Nested content", path)

            self.assertTrue(path.exists())

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "overwrite.txt"
            write_text("First", path)
            write_text("Second", path)

            self.assertEqual(path.read_text(), "Second")


if __name__ == "__main__":
    unittest.main(verbosity=2)
