"""Tests for telemetry/otel/cli/size.py."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock, patch

from telemetry.otel.cli.size import main


def _make_reader(
    *,
    file_sizes: dict | None = None,
    total_size: int = 1024,
):
    reader = MagicMock()
    reader.file_sizes.return_value = file_sizes or {
        "metrics.jsonl": 512,
        "events.jsonl": 256,
        "spans.jsonl": 256,
    }
    reader.data_dir_size.return_value = total_size
    return reader


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestSizeMain(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        with patch("telemetry.otel.cli.size.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.size.OTLPReader", return_value=_make_reader()):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    result = main(argv)
        return result, buf.getvalue()

    def test_table_returns_0(self):
        result, _ = self._run([])
        self.assertEqual(result, 0)

    def test_table_shows_file_names(self):
        _, output = self._run([])
        self.assertIn("metrics.jsonl", output)
        self.assertIn("events.jsonl", output)
        self.assertIn("spans.jsonl", output)

    def test_json_format_has_expected_keys(self):
        with patch("telemetry.otel.cli.size.OTLPDataDir.from_env") as mock_env:
            mock_env.return_value = MagicMock()
            with patch("telemetry.otel.cli.size.OTLPReader", return_value=_make_reader()):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    main(["--format", "json"])
        data = json.loads(buf.getvalue())
        self.assertIn("total_bytes", data)
        self.assertIn("files", data)
        self.assertIn("data_dir", data)

    def test_breakdown_none_shows_total(self):
        _, output = self._run(["--breakdown", "none"])
        self.assertIn("Total", output)

    def test_data_dir_flag(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with patch("telemetry.otel.cli.size.OTLPReader", return_value=_make_reader()):
                with patch("telemetry.otel.cli.size.emit_rows", return_value=0):
                    result = main(["--data-dir", td])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
