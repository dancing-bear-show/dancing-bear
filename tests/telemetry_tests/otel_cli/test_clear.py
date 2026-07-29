"""Tests for telemetry/otel/cli/clear.py."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telemetry.otel.cli.clear import main
from telemetry.otel.reader import OTLPDataDir


class TestClearMain(unittest.TestCase):
    def test_confirm_clears_all_files(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "metrics.jsonl").write_text("data")
            (p / "events.jsonl").write_text("data")
            (p / "spans.jsonl").write_text("data")
            data_dir = OTLPDataDir(path=p)
            with patch("telemetry.otel.cli.clear.OTLPDataDir.from_env", return_value=data_dir):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    result = main(["--confirm"])
            self.assertEqual(result, 0)
            self.assertFalse((p / "metrics.jsonl").exists())
            self.assertFalse((p / "events.jsonl").exists())
            self.assertFalse((p / "spans.jsonl").exists())

    def test_confirm_clears_only_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "metrics.jsonl").write_text("data")
            (p / "events.jsonl").write_text("data")
            data_dir = OTLPDataDir(path=p)
            with patch("telemetry.otel.cli.clear.OTLPDataDir.from_env", return_value=data_dir):
                with patch("sys.stdout", io.StringIO()):
                    result = main(["--confirm", "--type", "metrics"])
            self.assertEqual(result, 0)
            self.assertFalse((p / "metrics.jsonl").exists())
            self.assertTrue((p / "events.jsonl").exists())

    def test_confirm_clears_only_events(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "events.jsonl").write_text("data")
            (p / "spans.jsonl").write_text("data")
            data_dir = OTLPDataDir(path=p)
            with patch("telemetry.otel.cli.clear.OTLPDataDir.from_env", return_value=data_dir):
                with patch("sys.stdout", io.StringIO()):
                    result = main(["--confirm", "--type", "events"])
            self.assertEqual(result, 0)
            self.assertFalse((p / "events.jsonl").exists())
            self.assertTrue((p / "spans.jsonl").exists())

    def test_confirm_clears_only_spans(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "metrics.jsonl").write_text("data")
            (p / "spans.jsonl").write_text("data")
            data_dir = OTLPDataDir(path=p)
            with patch("telemetry.otel.cli.clear.OTLPDataDir.from_env", return_value=data_dir):
                with patch("sys.stdout", io.StringIO()):
                    result = main(["--confirm", "--type", "spans"])
            self.assertEqual(result, 0)
            self.assertFalse((p / "spans.jsonl").exists())
            self.assertTrue((p / "metrics.jsonl").exists())

    def test_missing_files_cleared_with_no_error(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = OTLPDataDir(path=Path(td))
            with patch("telemetry.otel.cli.clear.OTLPDataDir.from_env", return_value=data_dir):
                with patch("sys.stdout", io.StringIO()):
                    result = main(["--confirm"])
        self.assertEqual(result, 0)

    def test_without_confirm_cancelled_when_not_yes(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "metrics.jsonl").write_text("data")
            data_dir = OTLPDataDir(path=Path(td))
            with patch("telemetry.otel.cli.clear.OTLPDataDir.from_env", return_value=data_dir):
                with patch("builtins.input", return_value="no"):
                    buf = io.StringIO()
                    with patch("sys.stdout", buf):
                        result = main([])
            self.assertEqual(result, 0)
            self.assertIn("Cancelled", buf.getvalue())
            self.assertTrue((Path(td) / "metrics.jsonl").exists())

    def test_without_confirm_proceeds_when_yes(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "metrics.jsonl").write_text("data")
            (Path(td) / "events.jsonl").write_text("data")
            (Path(td) / "spans.jsonl").write_text("data")
            data_dir = OTLPDataDir(path=Path(td))
            with patch("telemetry.otel.cli.clear.OTLPDataDir.from_env", return_value=data_dir):
                with patch("builtins.input", return_value="yes"):
                    with patch("sys.stdout", io.StringIO()):
                        result = main([])
            self.assertEqual(result, 0)
            self.assertFalse((Path(td) / "metrics.jsonl").exists())

    def test_data_dir_flag_used(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("sys.stdout", io.StringIO()):
                result = main(["--confirm", "--data-dir", td])
        self.assertEqual(result, 0)

    def test_output_confirms_files_cleared(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = OTLPDataDir(path=Path(td))
            with patch("telemetry.otel.cli.clear.OTLPDataDir.from_env", return_value=data_dir):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    main(["--confirm"])
        output = buf.getvalue()
        self.assertIn("metrics.jsonl", output)
        self.assertIn("events.jsonl", output)
        self.assertIn("spans.jsonl", output)


if __name__ == "__main__":
    unittest.main()
