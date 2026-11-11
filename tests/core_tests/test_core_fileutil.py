"""Tests for core.fileutil."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.cli_errors import CLIError
from core.fileutil import (
    SymlinkDestinationError,
    atomic_write_json,
    atomic_write_text,
    load_json_or_exit,
    safe_load_json,
    write_once,
)


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
            self.assertEqual(json.loads(p.read_text()), [1, 2, 3])

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

    def test_no_tmp_file_left_on_serialization_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.json"
            with self.assertRaises(TypeError):
                atomic_write_json(p, {"bad": object()})
            self.assertEqual(list(Path(td).glob("*.tmp")), [])


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
        with self.assertRaises(CLIError) as cm:
            load_json_or_exit("/nonexistent/missing.json")
        self.assertIn("missing.json", str(cm.exception))

    def test_exits_on_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text("{bad json", encoding="utf-8")
            with self.assertRaises(CLIError) as cm:
                load_json_or_exit(p)
        self.assertIn("bad.json", str(cm.exception))

    def test_exit_message_mentions_path(self) -> None:
        with self.assertRaises(CLIError) as cm:
            load_json_or_exit("/no/such/file.json")
        self.assertIn("file.json", str(cm.exception))



class TestAtomicWriteText(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def _leftovers(self):
        return [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")]

    def test_creates_parent_dirs_and_writes_utf8(self):
        target = self.dir / "a" / "b.txt"
        atomic_write_text(target, "caf\u00e9\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "caf\u00e9\n")

    def test_new_file_mode_respects_requested_bits(self):
        target = self.dir / "secret.md"
        atomic_write_text(target, "x", new_file_mode=0o600)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_overwrite_preserves_existing_mode(self):
        target = self.dir / "keep.txt"
        target.write_text("old")
        target.chmod(0o640)
        atomic_write_text(target, "new", new_file_mode=0o600)
        self.assertEqual(target.read_text(), "new")
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_symlink_replaced_not_written_through(self):
        real = self.dir / "real.txt"
        real.write_text("untouched")
        link = self.dir / "link.txt"
        link.symlink_to(real)
        atomic_write_text(link, "replaced")
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_text(), "replaced")
        self.assertEqual(real.read_text(), "untouched")

    def test_symlink_refused_when_requested(self):
        real = self.dir / "real.txt"
        real.write_text("untouched")
        link = self.dir / "link.txt"
        link.symlink_to(real)
        with self.assertRaises(SymlinkDestinationError):
            atomic_write_text(link, "nope", refuse_symlink=True)
        self.assertTrue(link.is_symlink())
        self.assertEqual(real.read_text(), "untouched")

    def test_directory_destination_rejected(self):
        target = self.dir / "adir"
        target.mkdir()
        with self.assertRaises(IsADirectoryError):
            atomic_write_text(target, "x")
        self.assertEqual(self._leftovers(), [])

    def test_failed_write_removes_temp_and_keeps_old_content(self):
        target = self.dir / "t.txt"
        target.write_text("old")
        with self.assertRaises(UnicodeEncodeError):
            atomic_write_text(target, "\ud800")  # lone surrogate cannot encode
        self.assertEqual(target.read_text(), "old")
        self.assertEqual(self._leftovers(), [])

if __name__ == "__main__":
    unittest.main()
