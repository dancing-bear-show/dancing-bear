"""workflow.json_read and the error wording of the loaders built on it."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from workflow.cli_dispatch_review import _load_json_object, _read_json_file
from workflow.json_read import JsonReadError, JsonReadFailure, read_json
from workflow.sweep_record import SweepRecordError, _load_json


class _TmpDir(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.missing = self.dir / "absent.json"
        self.garbage = self.dir / "garbage.json"
        self.garbage.write_text("{not json", encoding="utf-8")
        self.non_utf8 = self.dir / "latin1.json"
        self.non_utf8.write_bytes(b"\xff\xfe{}")
        self.listdoc = self.dir / "list.json"
        self.listdoc.write_text("[1]", encoding="utf-8")
        self.obj = self.dir / "obj.json"
        self.obj.write_text('{"a": 1}', encoding="utf-8")


class TestReadJson(_TmpDir):
    def test_valid_documents_of_any_type_are_returned(self) -> None:
        self.assertEqual(read_json(self.obj), {"a": 1})
        self.assertEqual(read_json(str(self.listdoc)), [1])

    def test_failures_are_classified(self) -> None:
        cases = {
            self.missing: (JsonReadFailure.MISSING, FileNotFoundError),
            self.dir: (JsonReadFailure.UNREADABLE, OSError),
            self.non_utf8: (JsonReadFailure.UNREADABLE, UnicodeDecodeError),
            self.garbage: (JsonReadFailure.INVALID, json.JSONDecodeError),
        }
        for path, (kind, cause_type) in cases.items():
            with self.subTest(path=path.name), self.assertRaises(JsonReadError) as cm:
                read_json(path)
            self.assertIs(cm.exception.kind, kind)
            self.assertIsInstance(cm.exception.cause, cause_type)
            self.assertEqual(cm.exception.path, path)

    def test_detail_is_strerror_or_parser_message(self) -> None:
        with self.assertRaises(JsonReadError) as cm:
            read_json(self.missing)
        self.assertEqual(cm.exception.detail, "No such file or directory")
        with self.assertRaises(JsonReadError) as cm:
            read_json(self.garbage)
        self.assertEqual(cm.exception.detail, "Expecting property name enclosed in double quotes")


class TestSweepRecordLoadJson(_TmpDir):
    def test_missing_wording(self) -> None:
        with self.assertRaises(SweepRecordError) as cm:
            _load_json(self.missing, "idx")
        self.assertEqual(str(cm.exception), f"idx not found: {self.missing}")

    def test_invalid_and_non_utf8_wording(self) -> None:
        for path in (self.garbage, self.non_utf8):
            with self.subTest(path=path.name), self.assertRaises(SweepRecordError) as cm:
                _load_json(path, "idx")
            self.assertTrue(
                str(cm.exception).startswith(f"idx is unreadable or not JSON: {path} (")
            )

    def test_valid_document_is_returned(self) -> None:
        self.assertEqual(_load_json(self.listdoc, "idx"), [1])


class TestLoadJsonObject(_TmpDir):
    def test_unreadable_wording_keeps_the_original_exception(self) -> None:
        for path in (self.missing, self.garbage, self.non_utf8):
            with self.subTest(path=path.name), self.assertRaises(ValueError) as cm:
                _load_json_object(str(path), "ctx")
            self.assertTrue(str(cm.exception).startswith("ctx unreadable: "))
            self.assertIsInstance(cm.exception.__cause__, (OSError, ValueError))
            self.assertNotIsInstance(cm.exception.__cause__, JsonReadError)

    def test_non_object_is_rejected_and_object_returned(self) -> None:
        with self.assertRaises(ValueError) as cm:
            _load_json_object(str(self.listdoc), "ctx")
        self.assertEqual(str(cm.exception), "ctx is not a JSON object")
        self.assertEqual(_load_json_object(str(self.obj), "ctx"), {"a": 1})


class TestReadJsonFile(_TmpDir):
    def _call(self, path: Path) -> tuple[object, bool, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            doc, ok = _read_json_file(str(path), "fix-results")
        return doc, ok, err.getvalue()

    def test_wording_per_failure(self) -> None:
        cases = {
            self.missing: "merge-fix-results: fix-results is unreadable: No such file or directory\n",
            self.garbage: (
                "merge-fix-results: fix-results is not valid JSON: "
                "Expecting property name enclosed in double quotes\n"
            ),
        }
        for path, expected in cases.items():
            with self.subTest(path=path.name):
                self.assertEqual(self._call(path), (None, False, expected))
        doc, ok, err = self._call(self.non_utf8)
        self.assertEqual((doc, ok), (None, False))
        self.assertTrue(
            err.startswith("merge-fix-results: fix-results is unreadable: 'utf-8' codec")
        )

    def test_valid_document_is_returned_silently(self) -> None:
        self.assertEqual(self._call(self.listdoc), ([1], True, ""))


if __name__ == "__main__":
    unittest.main()
