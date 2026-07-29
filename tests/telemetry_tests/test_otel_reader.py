"""Tests for telemetry.otel.reader — OTLPDataDir and OTLPReader."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from telemetry.otel.reader import (
    EVENTS_FILE,
    METRICS_FILE,
    SPANS_FILE,
    OTLPDataDir,
    OTLPReader,
)


# Minimal valid JSONL lines for each record type.
# OTLPMetricsRecord.from_dict handles missing keys with empty defaults.
# Use the simplified format (no resourceMetrics wrapper) for brevity.
_METRICS_LINE = json.dumps({})
_EVENTS_LINE = json.dumps({})
_SPANS_LINE = json.dumps({})


def _write_jsonl(path: Path, lines: list[str]) -> None:
    """Write a list of JSON strings as a JSONL file."""
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestOTLPDataDirDefault(unittest.TestCase):
    def test_returns_home_config_otel(self):
        expected = Path.home() / ".config" / "otel"
        result = OTLPDataDir.default()
        self.assertEqual(result.path, expected)

    def test_returns_otlp_data_dir_instance(self):
        self.assertIsInstance(OTLPDataDir.default(), OTLPDataDir)


class TestOTLPDataDirFromEnv(unittest.TestCase):
    def test_env_var_set_uses_that_path(self):
        with mock.patch.dict(os.environ, {"TELEMETRY_DATA_DIR": "/custom/otel"}):
            result = OTLPDataDir.from_env()
        self.assertEqual(result.path, Path("/custom/otel"))

    def test_env_var_unset_falls_back_to_default(self):
        env = {k: v for k, v in os.environ.items() if k != "TELEMETRY_DATA_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            result = OTLPDataDir.from_env()
        self.assertEqual(result.path, OTLPDataDir.default().path)

    def test_env_var_empty_string_falls_back_to_default(self):
        # os.getenv returns "" for unset via an empty string in the dict;
        # the code checks truthiness, so empty string falls back to default.
        with mock.patch.dict(os.environ, {"TELEMETRY_DATA_DIR": ""}, clear=False):
            result = OTLPDataDir.from_env()
        self.assertEqual(result.path, OTLPDataDir.default().path)


class TestOTLPReaderInit(unittest.TestCase):
    def test_explicit_data_dir_used(self):
        dd = OTLPDataDir(path=Path("/some/path"))
        reader = OTLPReader(data_dir=dd)
        self.assertEqual(reader.data_dir, dd)

    def test_none_data_dir_calls_from_env(self):
        with mock.patch.dict(os.environ, {"TELEMETRY_DATA_DIR": "/env/path"}):
            reader = OTLPReader(data_dir=None)
        self.assertEqual(reader.data_dir.path, Path("/env/path"))


class TestOTLPReaderReadMethods(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmppath = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_reader(self) -> OTLPReader:
        return OTLPReader(data_dir=OTLPDataDir(path=self.tmppath))

    def test_read_metrics_returns_records(self):
        _write_jsonl(self.tmppath / METRICS_FILE, [_METRICS_LINE, _METRICS_LINE])
        reader = self._make_reader()
        records = reader.read_metrics()
        self.assertEqual(len(records), 2)

    def test_read_events_returns_records(self):
        _write_jsonl(self.tmppath / EVENTS_FILE, [_EVENTS_LINE])
        reader = self._make_reader()
        records = reader.read_events()
        self.assertEqual(len(records), 1)

    def test_read_spans_returns_records(self):
        _write_jsonl(self.tmppath / SPANS_FILE, [_SPANS_LINE])
        reader = self._make_reader()
        records = reader.read_spans()
        self.assertEqual(len(records), 1)

    def test_read_metrics_missing_file_returns_empty(self):
        reader = self._make_reader()
        self.assertEqual(reader.read_metrics(), [])

    def test_read_events_missing_file_returns_empty(self):
        reader = self._make_reader()
        self.assertEqual(reader.read_events(), [])

    def test_read_spans_missing_file_returns_empty(self):
        reader = self._make_reader()
        self.assertEqual(reader.read_spans(), [])

    def test_malformed_json_line_skipped(self):
        # iter_jsonl_file with tolerant=True skips bad JSON; from_dict KeyError also skipped.
        path = self.tmppath / METRICS_FILE
        path.write_text(
            _METRICS_LINE + "\n" + "NOT_JSON_AT_ALL\n" + _METRICS_LINE + "\n",
            encoding="utf-8",
        )
        reader = self._make_reader()
        records = reader.read_metrics()
        # Bad JSON line silently skipped; 2 valid lines remain
        self.assertEqual(len(records), 2)

    def test_read_metrics_multiple_valid_lines(self):
        _write_jsonl(self.tmppath / METRICS_FILE, [_METRICS_LINE] * 5)
        reader = self._make_reader()
        self.assertEqual(len(reader.read_metrics()), 5)

    def test_from_dict_key_error_skipped(self):
        # A valid JSON object that causes from_dict to raise KeyError gets skipped.
        # Patch OTLPMetricsRecord.from_dict as a classmethod side_effect.
        from telemetry.otel.models import OTLPMetricsRecord as _OMR
        call_count = {"n": 0}
        original_from_dict = _OMR.from_dict

        def patched_from_dict(cls_or_d, d=None):
            # called as classmethod: cls_or_d is the class, d is the dict
            # called as staticmethod mock: cls_or_d is the dict
            actual_d = d if d is not None else cls_or_d
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise KeyError("simulated key error")
            return original_from_dict(actual_d)

        _write_jsonl(self.tmppath / METRICS_FILE, [_METRICS_LINE, _METRICS_LINE])
        reader = self._make_reader()
        with mock.patch("telemetry.otel.reader.OTLPMetricsRecord.from_dict", side_effect=patched_from_dict):
            records = reader.read_metrics()
        # First line triggers KeyError (skipped), second line succeeds
        self.assertEqual(len(records), 1)


class TestOTLPReaderRotatedFiles(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmppath = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_reader(self) -> OTLPReader:
        return OTLPReader(data_dir=OTLPDataDir(path=self.tmppath))

    def test_read_events_picks_up_rotated_file(self):
        # Write primary and rotation file
        _write_jsonl(self.tmppath / EVENTS_FILE, [_EVENTS_LINE])
        _write_jsonl(self.tmppath / (EVENTS_FILE + ".1"), [_EVENTS_LINE, _EVENTS_LINE])
        reader = self._make_reader()
        records = reader.read_events()
        # Primary: 1 record; rotation: 2 records = 3 total
        self.assertEqual(len(records), 3)

    def test_file_sizes_includes_rotated_file(self):
        primary_content = _EVENTS_LINE + "\n"
        rotated_content = _EVENTS_LINE + "\n" + _EVENTS_LINE + "\n"
        (self.tmppath / EVENTS_FILE).write_text(primary_content, encoding="utf-8")
        (self.tmppath / (EVENTS_FILE + ".1")).write_text(rotated_content, encoding="utf-8")
        reader = self._make_reader()
        sizes = reader.file_sizes()
        expected = len(primary_content.encode()) + len(rotated_content.encode())
        self.assertEqual(sizes[EVENTS_FILE], expected)

    def test_data_dir_size_includes_rotated_file(self):
        primary_content = _METRICS_LINE + "\n"
        rotated_content = _METRICS_LINE + "\n"
        (self.tmppath / METRICS_FILE).write_text(primary_content, encoding="utf-8")
        (self.tmppath / (METRICS_FILE + ".1")).write_text(rotated_content, encoding="utf-8")
        reader = self._make_reader()
        total = reader.data_dir_size()
        self.assertGreaterEqual(total, len(primary_content.encode()) + len(rotated_content.encode()))


class TestOTLPReaderSizes(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmppath = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_reader(self) -> OTLPReader:
        return OTLPReader(data_dir=OTLPDataDir(path=self.tmppath))

    def test_data_dir_size_sums_all_files(self):
        metrics_content = _METRICS_LINE + "\n"
        events_content = _EVENTS_LINE + "\n"
        spans_content = _SPANS_LINE + "\n"
        (self.tmppath / METRICS_FILE).write_text(metrics_content, encoding="utf-8")
        (self.tmppath / EVENTS_FILE).write_text(events_content, encoding="utf-8")
        (self.tmppath / SPANS_FILE).write_text(spans_content, encoding="utf-8")
        reader = self._make_reader()
        total = reader.data_dir_size()
        expected = (
            len(metrics_content.encode())
            + len(events_content.encode())
            + len(spans_content.encode())
        )
        self.assertEqual(total, expected)

    def test_data_dir_size_empty_dir_is_zero(self):
        reader = self._make_reader()
        self.assertEqual(reader.data_dir_size(), 0)

    def test_file_sizes_returns_per_file_dict(self):
        metrics_content = _METRICS_LINE + "\n"
        events_content = _EVENTS_LINE + "\n" + _EVENTS_LINE + "\n"
        (self.tmppath / METRICS_FILE).write_text(metrics_content, encoding="utf-8")
        (self.tmppath / EVENTS_FILE).write_text(events_content, encoding="utf-8")
        reader = self._make_reader()
        sizes = reader.file_sizes()
        self.assertEqual(sizes[METRICS_FILE], len(metrics_content.encode()))
        self.assertEqual(sizes[EVENTS_FILE], len(events_content.encode()))
        self.assertEqual(sizes[SPANS_FILE], 0)

    def test_file_sizes_keys_are_filenames(self):
        reader = self._make_reader()
        sizes = reader.file_sizes()
        self.assertIn(METRICS_FILE, sizes)
        self.assertIn(EVENTS_FILE, sizes)
        self.assertIn(SPANS_FILE, sizes)

    def test_file_sizes_missing_files_are_zero(self):
        reader = self._make_reader()
        sizes = reader.file_sizes()
        self.assertEqual(sizes[METRICS_FILE], 0)
        self.assertEqual(sizes[EVENTS_FILE], 0)
        self.assertEqual(sizes[SPANS_FILE], 0)


if __name__ == "__main__":
    unittest.main()
