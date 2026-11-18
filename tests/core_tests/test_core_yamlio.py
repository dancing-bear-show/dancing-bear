"""Tests for core/yamlio.py YAML helpers."""

import tempfile
import unittest
from pathlib import Path

import yaml

from core.yamlio import dump_config, dump_yaml_text, load_config


class TestLoadConfig(unittest.TestCase):
    """Tests for load_config function."""

    def test_load_valid_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("key: value\nnumber: 42\n", encoding="utf-8")
            result = load_config(str(path))
            self.assertEqual(result, {"key": "value", "number": 42})

    def test_load_missing_file_returns_empty(self):
        result = load_config("/nonexistent/path/config.yaml")
        self.assertEqual(result, {})

    def test_load_none_path_returns_empty(self):
        result = load_config(None)
        self.assertEqual(result, {})

    def test_load_empty_path_returns_empty(self):
        result = load_config("")
        self.assertEqual(result, {})

    def test_load_empty_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.yaml"
            path.write_text("", encoding="utf-8")
            result = load_config(str(path))
            self.assertEqual(result, {})

    def test_load_whitespace_only_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "whitespace.yaml"
            path.write_text("   \n\n  \t  ", encoding="utf-8")
            result = load_config(str(path))
            self.assertEqual(result, {})

    def test_load_nested_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested.yaml"
            content = """
parent:
  child1: value1
  child2:
    - item1
    - item2
"""
            path.write_text(content, encoding="utf-8")
            result = load_config(str(path))
            self.assertEqual(result["parent"]["child1"], "value1")
            self.assertEqual(result["parent"]["child2"], ["item1", "item2"])

    def test_load_with_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unicode.yaml"
            path.write_text("message: こんにちは\n", encoding="utf-8")
            result = load_config(str(path))
            self.assertEqual(result, {"message": "こんにちは"})

    def test_load_yaml_null_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "null.yaml"
            path.write_text("~\n", encoding="utf-8")  # YAML null
            result = load_config(str(path))
            self.assertEqual(result, {})


class TestDumpConfig(unittest.TestCase):
    """Tests for dump_config function."""

    def test_dump_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output.yaml"
            dump_config(str(path), {"key": "value"})
            self.assertTrue(path.exists())

    def test_dump_content_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output.yaml"
            data = {"name": "test", "count": 5}
            dump_config(str(path), data)
            result = load_config(str(path))
            self.assertEqual(result, data)

    def test_dump_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "dir" / "config.yaml"
            dump_config(str(path), {"created": True})
            self.assertTrue(path.exists())

    def test_dump_preserves_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ordered.yaml"
            # Using dict with specific order (Python 3.7+ preserves insertion order)
            data = {"first": 1, "second": 2, "third": 3}
            dump_config(str(path), data)
            content = path.read_text(encoding="utf-8")
            # Check that keys appear in order
            first_pos = content.find("first")
            second_pos = content.find("second")
            third_pos = content.find("third")
            self.assertLess(first_pos, second_pos)
            self.assertLess(second_pos, third_pos)

    def test_dump_unicode_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unicode.yaml"
            data = {"greeting": "Привет мир"}
            dump_config(str(path), data)
            result = load_config(str(path))
            self.assertEqual(result["greeting"], "Привет мир")

    def test_dump_nested_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested.yaml"
            data = {"level1": {"level2": {"value": "deep"}}, "list": [1, 2, 3]}
            dump_config(str(path), data)
            result = load_config(str(path))
            self.assertEqual(result, data)

    def test_dump_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "overwrite.yaml"
            dump_config(str(path), {"original": True})
            dump_config(str(path), {"updated": True})
            result = load_config(str(path))
            self.assertNotIn("original", result)
            self.assertIn("updated", result)


class TestRoundTrip(unittest.TestCase):
    """Tests for load/dump round-trip consistency."""

    def test_roundtrip_simple(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roundtrip.yaml"
            original = {"key": "value", "number": 42, "flag": True}
            dump_config(str(path), original)
            loaded = load_config(str(path))
            self.assertEqual(loaded, original)

    def test_roundtrip_complex(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "complex.yaml"
            original = {
                "string": "hello",
                "integer": 123,
                "float": 3.14,
                "boolean": False,
                "null": None,
                "list": ["a", "b", "c"],
                "nested": {"inner": "value"},
            }
            dump_config(str(path), original)
            loaded = load_config(str(path))
            self.assertEqual(loaded, original)


class TestDumpYamlText(unittest.TestCase):
    def test_non_ascii_round_trip_unescaped(self):
        data = {"name": "café", "tags": ["日本語", "ñ"]}
        text = dump_yaml_text(data)
        self.assertIn("café", text)
        self.assertNotIn("\\u", text)
        self.assertEqual(yaml.safe_load(text), data)

    def test_preserves_key_order_by_default(self):
        self.assertEqual(dump_yaml_text({"b": 1, "a": 2}), "b: 1\na: 2\n")

    def test_sort_keys_opt_in(self):
        self.assertEqual(dump_yaml_text({"b": 1, "a": 2}, sort_keys=True), "a: 2\nb: 1\n")

    def test_block_style_for_collections(self):
        self.assertEqual(dump_yaml_text({"k": [1, 2]}), "k:\n- 1\n- 2\n")


if __name__ == "__main__":
    unittest.main()
