"""Tests for telemetry/otel/cli/health.py."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telemetry.otel.cli.health import (
    DATA_FILES,
    _output_json,
    _output_text,
    main,
)
from telemetry.otel.reader import OTLPDataDir


# ---------------------------------------------------------------------------
# _output_json
# ---------------------------------------------------------------------------


class TestOutputJson(unittest.TestCase):
    def test_missing_file_has_missing_key(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = OTLPDataDir(path=Path(td))
            file_exists = {f: False for f in DATA_FILES}
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                _output_json(data_dir, file_exists)
            data = json.loads(buf.getvalue())
        self.assertIn("files", data)
        self.assertTrue(data["files"]["metrics.jsonl"]["missing"])

    def test_existing_file_has_size_and_records(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "metrics.jsonl").write_text('{"x":1}\n{"x":2}\n')
            data_dir = OTLPDataDir(path=p)
            file_exists = {f: (p / f).exists() for f in DATA_FILES}
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                _output_json(data_dir, file_exists)
            data = json.loads(buf.getvalue())
        self.assertIn("size", data["files"]["metrics.jsonl"])
        self.assertIn("records", data["files"]["metrics.jsonl"])
        self.assertEqual(data["files"]["metrics.jsonl"]["records"], 2)

    def test_status_is_healthy(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = OTLPDataDir(path=Path(td))
            file_exists = {f: False for f in DATA_FILES}
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                _output_json(data_dir, file_exists)
            data = json.loads(buf.getvalue())
        self.assertEqual(data["status"], "healthy")


# ---------------------------------------------------------------------------
# _output_text
# ---------------------------------------------------------------------------


class TestOutputText(unittest.TestCase):
    def test_existing_file_shows_ok(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "metrics.jsonl").write_text('{"x":1}\n')
            data_dir = OTLPDataDir(path=p)
            file_exists = {f: (p / f).exists() for f in DATA_FILES}
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                _output_text(data_dir, file_exists)
        output = buf.getvalue()
        self.assertIn("OK", output)
        self.assertIn("metrics.jsonl", output)

    def test_missing_file_shows_not_created(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = OTLPDataDir(path=Path(td))
            file_exists = {f: False for f in DATA_FILES}
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                _output_text(data_dir, file_exists)
        output = buf.getvalue()
        self.assertIn("not yet created", output)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestHealthMain(unittest.TestCase):
    def test_infra_not_ok_returns_1(self):
        with patch("telemetry.otel.cli.health.OTLPDataDir.from_env") as mock_dir:
            mock_dir.return_value = MagicMock()
            with patch("telemetry.otel.cli.health.check_otel_infrastructure", return_value=False):
                result = main([])
        self.assertEqual(result, 1)

    def test_text_format_healthy(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "metrics.jsonl").write_text('{"x":1}\n')
            data_dir = OTLPDataDir(path=p)
            with patch("telemetry.otel.cli.health.OTLPDataDir.from_env", return_value=data_dir):
                with patch("telemetry.otel.cli.health.check_otel_infrastructure", return_value=True):
                    buf = io.StringIO()
                    with patch("sys.stdout", buf):
                        result = main(["--format", "text"])
        self.assertEqual(result, 0)
        self.assertIn("healthy", buf.getvalue())

    def test_json_format_healthy(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "events.jsonl").write_text('{"y":2}\n')
            data_dir = OTLPDataDir(path=p)
            with patch("telemetry.otel.cli.health.OTLPDataDir.from_env", return_value=data_dir):
                with patch("telemetry.otel.cli.health.check_otel_infrastructure", return_value=True):
                    buf = io.StringIO()
                    with patch("sys.stdout", buf):
                        result = main(["--format", "json"])
        self.assertEqual(result, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["status"], "healthy")


# Needed for test_infra_not_ok_returns_1
from unittest.mock import MagicMock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
