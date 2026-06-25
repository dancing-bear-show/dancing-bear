"""Tests for core.fileutil."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.fileutil import atomic_write_json, load_json_or_exit, safe_load_json, write_once


class TestAtomicWriteJson(unittest.TestCase):
    def test_creates_file_with_correct_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.json"
            atomic_write_json(p, {"key": "val"})
            self.assertEqual(json.loads(p.read_text()), {"key": "val"})

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a" / "b" / "out.json"
            atomic_write_json(p, [1, 2, 3])
            self.assertTrue(p.exists())

    def test_overwrites_existing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.json"
            atomic_write_json(p, {"v": 1})
            atomic_write_json(p, {"v": 2})
            self.assertEqual(json.loads(p.read_text())["v"], 2)

    def test_no_tmp_file_left_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.json"
            atomic_write_json(p, {})
            tmp_files = list(Path(td).glob("*.tmp"))
            self.assertEqual(tmp_files, [])

    def test_respects_indent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.json"
            atomic_write_json(p, {"a": 1}, indent=4)
            text = p.read_text()
            self.assertIn("    ", text)


class TestWriteOnce(unittest.TestCase):
    def test_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "new.txt"
            write_once(p, "hello")
            self.assertEqual(p.read_bytes(), b"hello")

    def test_accepts_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bytes.bin"
            write_once(p, b"\x00\x01")
            self.assertEqual(p.read_bytes(), b"\x00\x01")

    def test_raises_file_exists_error_on_second_call(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "once.txt"
            write_once(p, "first")
            with self.assertRaises(FileExistsError):
                write_once(p, "second")

    def test_original_content_unchanged_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "once.txt"
            write_once(p, "first")
            with self.assertRaises(FileExistsError):
                write_once(p, "second")
            self.assertEqual(p.read_bytes(), b"first")


class TestSafeLoadJson(unittest.TestCase):
    def test_returns_data_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "data.json"
            p.write_text('{"x": 42}', encoding="utf-8")
            result = safe_load_json(p)
            self.assertEqual(result["x"], 42)

    def test_returns_none_default_on_missing_file(self) -> None:
        result = safe_load_json("/nonexistent/path/file.json")
        self.assertIsNone(result)

    def test_returns_custom_default_on_missing_file(self) -> None:
        result = safe_load_json("/nonexistent/path/file.json", default={})
        self.assertEqual(result, {})

    def test_returns_default_on_bad_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text("not json {{", encoding="utf-8")
            result = safe_load_json(p, default="fallback")
            self.assertEqual(result, "fallback")

    def test_returns_list_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "list.json"
            p.write_text("[1, 2, 3]", encoding="utf-8")
            result = safe_load_json(p)
            self.assertEqual(result, [1, 2, 3])


class TestLoadJsonOrExit(unittest.TestCase):
    def test_returns_data_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cfg.json"
            p.write_text('{"ok": true}', encoding="utf-8")
            result = load_json_or_exit(p)
            self.assertTrue(result["ok"])

    def test_exits_on_missing_file(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            load_json_or_exit("/nonexistent/missing.json")
        self.assertEqual(cm.exception.code if isinstance(cm.exception.code, int) else 1, 1)

    def test_exits_on_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text("{bad json", encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_json_or_exit(p)

    def test_exit_message_mentions_path(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            load_json_or_exit("/no/such/file.json")
        self.assertIn("file.json", str(cm.exception.code))


if __name__ == "__main__":
    unittest.main()
