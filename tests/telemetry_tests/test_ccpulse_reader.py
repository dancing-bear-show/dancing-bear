"""Tests for telemetry/ccpulse_reader.py — ccpulse session insights reader."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from telemetry.ccpulse_reader import read_current, _STALE_AFTER_SECONDS, _SUPPORTED_SCHEMAS


def _write_payload(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


class TestReadCurrentMissingFile(unittest.TestCase):
    def test_missing_file_returns_none(self) -> None:
        result = read_current(Path("/tmp/nonexistent_ccpulse_test.json"))  # nosec B108 - intentionally nonexistent path to test missing-file behavior
        self.assertIsNone(result)


class TestReadCurrentStaleFile(unittest.TestCase):
    def test_stale_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            _write_payload(path, {"schema": 1, "tips": []})
            # Pass a now that makes the file appear stale
            stale_now = time.time() + _STALE_AFTER_SECONDS + 1
            result = read_current(path, now=stale_now)
            self.assertIsNone(result)

    def test_fresh_file_not_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            _write_payload(path, {"schema": 1, "tips": []})
            # now = current time, file was just written
            result = read_current(path, now=time.time())
            self.assertIsNotNone(result)


class TestReadCurrentInvalidJson(unittest.TestCase):
    def test_invalid_json_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            path.write_text("not json {{{{")
            result = read_current(path, now=time.time())
            self.assertIsNone(result)


class TestReadCurrentSchemaValidation(unittest.TestCase):
    def test_supported_schema_returns_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            schema = next(iter(_SUPPORTED_SCHEMAS))
            _write_payload(path, {"schema": schema, "tips": []})
            result = read_current(path, now=time.time())
            self.assertIsNotNone(result)
            self.assertEqual(result["schema"], schema)

    def test_unsupported_schema_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            _write_payload(path, {"schema": 999, "tips": []})
            result = read_current(path, now=time.time())
            self.assertIsNone(result)

    def test_missing_schema_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            _write_payload(path, {"tips": []})
            result = read_current(path, now=time.time())
            self.assertIsNone(result)

    def test_null_schema_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            _write_payload(path, {"schema": None, "tips": []})
            result = read_current(path, now=time.time())
            self.assertIsNone(result)


class TestReadCurrentErrorKey(unittest.TestCase):
    def test_payload_with_error_key_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            _write_payload(path, {"schema": 1, "error": "something went wrong"})
            result = read_current(path, now=time.time())
            self.assertIsNone(result)


class TestReadCurrentNonDict(unittest.TestCase):
    def test_list_payload_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            path.write_text(json.dumps([1, 2, 3]))
            result = read_current(path, now=time.time())
            self.assertIsNone(result)

    def test_string_payload_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            path.write_text(json.dumps("hello"))
            result = read_current(path, now=time.time())
            self.assertIsNone(result)


class TestReadCurrentValidPayload(unittest.TestCase):
    def test_full_payload_returned_intact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            payload = {
                "schema": 1,
                "efficiency_score": 80.0,
                "cost_usd": 0.05,
                "tips": [{"waste_reason": "redundant-read", "count": 3}],
            }
            _write_payload(path, payload)
            result = read_current(path, now=time.time())
            self.assertIsNotNone(result)
            self.assertEqual(result["efficiency_score"], 80.0)
            self.assertEqual(len(result["tips"]), 1)

    def test_custom_stale_after_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "current-tips.json"
            _write_payload(path, {"schema": 1})
            # With a very short stale window and now=slightly_in_future, should be stale
            now = time.time() + 5
            result = read_current(path, stale_after_seconds=1, now=now)
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
