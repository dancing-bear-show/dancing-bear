"""Tests for telemetry/otel/cli/inspect.py."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from telemetry.otel.cli.inspect import (
    _build_json_rows,
    _build_table_rows,
    main,
)


def _make_timestamp(year: int = 2026, month: int = 4, day: int = 16) -> datetime:
    return datetime(year, month, day, 10, 0, 0, tzinfo=timezone.utc)


def _make_metric_record():
    m = MagicMock()
    m.name = "cpu.usage"
    m.data_points = [MagicMock()]
    record = MagicMock()
    record.resource.service_name = "claude"
    record.metrics = [m]
    ts = _make_timestamp()
    record.earliest_timestamp.return_value = ts
    return record


def _make_event_record():
    ts = _make_timestamp()
    evt = MagicMock()
    evt.timestamp = ts
    record = MagicMock()
    record.resource.service_name = "claude"
    record.log_records = [evt]
    return record


def _make_span_record():
    ts = _make_timestamp()
    span = MagicMock()
    span.start_timestamp = ts
    record = MagicMock()
    record.resource.service_name = "claude"
    record.spans = [span]
    return record


# ---------------------------------------------------------------------------
# _build_json_rows
# ---------------------------------------------------------------------------


class TestBuildJsonRows(unittest.TestCase):
    def test_metrics_rows(self):
        records = [_make_metric_record()]
        rows = _build_json_rows(records, "metrics")
        self.assertEqual(len(rows), 1)
        self.assertIn("service", rows[0])
        self.assertIn("metrics", rows[0])

    def test_events_rows(self):
        records = [_make_event_record()]
        rows = _build_json_rows(records, "events")
        self.assertEqual(len(rows), 1)
        self.assertIn("events", rows[0])

    def test_spans_rows(self):
        records = [_make_span_record()]
        rows = _build_json_rows(records, "spans")
        self.assertEqual(len(rows), 1)
        self.assertIn("spans", rows[0])

    def test_empty_records(self):
        rows = _build_json_rows([], "metrics")
        self.assertEqual(rows, [])


# ---------------------------------------------------------------------------
# _build_table_rows
# ---------------------------------------------------------------------------


class TestBuildTableRows(unittest.TestCase):
    def test_metrics_has_headers(self):
        records = [_make_metric_record()]
        _, headers = _build_table_rows(records, "metrics")
        self.assertIn("Service", headers)
        self.assertIn("Metrics", headers)

    def test_events_has_headers(self):
        records = [_make_event_record()]
        _, headers = _build_table_rows(records, "events")
        self.assertIn("Events", headers)

    def test_spans_has_headers(self):
        records = [_make_span_record()]
        _, headers = _build_table_rows(records, "spans")
        self.assertIn("Spans", headers)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestInspectMain(unittest.TestCase):
    def _make_reader(self, metrics=None, events=None, spans=None):
        reader = MagicMock()
        reader.read_metrics.return_value = metrics if metrics is not None else [_make_metric_record()]
        reader.read_events.return_value = events if events is not None else [_make_event_record()]
        reader.read_spans.return_value = spans if spans is not None else [_make_span_record()]
        return reader

    def test_default_type_metrics_returns_0(self):
        # Table format uses Rich Console (writes to real stdout, not patched)
        with patch("telemetry.otel.cli.inspect.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.inspect.OTLPReader", return_value=self._make_reader()):
                with patch("telemetry.otel.cli.inspect.emit_rows", return_value=0) as mock_emit:
                    result = main([])
        self.assertEqual(result, 0)
        mock_emit.assert_called_once()

    def test_events_type(self):
        with patch("telemetry.otel.cli.inspect.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.inspect.OTLPReader", return_value=self._make_reader()):
                with patch("telemetry.otel.cli.inspect.emit_rows", return_value=0):
                    result = main(["--type", "events"])
        self.assertEqual(result, 0)

    def test_spans_type(self):
        with patch("telemetry.otel.cli.inspect.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.inspect.OTLPReader", return_value=self._make_reader()):
                with patch("telemetry.otel.cli.inspect.emit_rows", return_value=0):
                    result = main(["--type", "spans"])
        self.assertEqual(result, 0)

    def test_json_format_metrics(self):
        with patch("telemetry.otel.cli.inspect.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.inspect.OTLPReader", return_value=self._make_reader()):
                with patch("telemetry.otel.cli.inspect.emit_rows", return_value=0):
                    result = main(["--format", "json"])
        self.assertEqual(result, 0)

    def test_limit_flag(self):
        records = [_make_metric_record() for _ in range(5)]
        with patch("telemetry.otel.cli.inspect.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.inspect.OTLPReader") as mock_cls:
                mock_cls.return_value.read_metrics.return_value = records
                with patch("telemetry.otel.cli.inspect.emit_rows", return_value=0):
                    result = main(["--limit", "2"])
        self.assertEqual(result, 0)

    def test_data_dir_flag(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with patch("telemetry.otel.cli.inspect.OTLPReader", return_value=self._make_reader()):
                with patch("telemetry.otel.cli.inspect.emit_rows", return_value=0):
                    result = main(["--data-dir", td])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
