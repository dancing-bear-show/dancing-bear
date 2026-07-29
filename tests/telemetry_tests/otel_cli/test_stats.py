"""Tests for telemetry/otel/cli/stats.py."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock, patch

from telemetry.otel.cli.stats import (
    _aggregate_by_metric,
    _aggregate_by_resource,
    _output_stats,
    main,
)


def _make_metric_record(name: str = "cpu.usage", data_points_count: int = 3):
    dp = MagicMock()
    metric = MagicMock()
    metric.name = name
    metric.data_points = [dp] * data_points_count
    record = MagicMock()
    record.metrics = [metric]
    return record


def _make_event_record(service: str = "claude", log_count: int = 2):
    record = MagicMock()
    record.resource.service_name = service
    record.log_records = [MagicMock()] * log_count
    return record


def _make_spans_record(service: str = "claude", span_count: int = 1):
    record = MagicMock()
    record.resource.service_name = service
    record.spans = [MagicMock()] * span_count
    return record


def _make_metric_record_with_service(service: str = "claude", name: str = "cpu.usage", data_points_count: int = 3):
    record = _make_metric_record(name, data_points_count)
    record.resource.service_name = service
    return record


# ---------------------------------------------------------------------------
# _aggregate_by_metric
# ---------------------------------------------------------------------------


class TestAggregateByMetric(unittest.TestCase):
    def test_empty_records(self):
        result = _aggregate_by_metric([])
        self.assertEqual(result, {})

    def test_counts_data_points(self):
        records = [_make_metric_record("cpu.usage", 3)]
        result = _aggregate_by_metric(records)
        self.assertEqual(result["cpu.usage"], 3)

    def test_accumulates_across_records(self):
        records = [
            _make_metric_record("cpu.usage", 2),
            _make_metric_record("cpu.usage", 3),
        ]
        result = _aggregate_by_metric(records)
        self.assertEqual(result["cpu.usage"], 5)


# ---------------------------------------------------------------------------
# _aggregate_by_resource
# ---------------------------------------------------------------------------


class TestAggregateByResource(unittest.TestCase):
    def test_empty_all(self):
        result = _aggregate_by_resource([], [], [])
        self.assertEqual(result, {})

    def test_counts_metrics_events_spans(self):
        metrics = [_make_metric_record_with_service("svc", "m", 2)]
        events = [_make_event_record("svc", 3)]
        spans = [_make_spans_record("svc", 1)]
        result = _aggregate_by_resource(metrics, events, spans)
        self.assertEqual(result["svc"]["metrics"], 2)
        self.assertEqual(result["svc"]["events"], 3)
        self.assertEqual(result["svc"]["spans"], 1)


# ---------------------------------------------------------------------------
# _output_stats
# ---------------------------------------------------------------------------


class TestOutputStats(unittest.TestCase):
    def test_table_format_returns_0(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            result = _output_stats({"cpu": 5}, "Metrics", "table")
        self.assertEqual(result, 0)
        self.assertIn("cpu", buf.getvalue())

    def test_json_format_returns_none(self):
        # emit_one returns None
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            result = _output_stats({"cpu": 5}, "Metrics", "json")
        self.assertIsNone(result)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["cpu"], 5)

    def test_table_resource_format(self):
        stats = {"svc": {"metrics": 2, "events": 3, "spans": 1}}
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            result = _output_stats(stats, "Resource Stats", "table")
        self.assertEqual(result, 0)
        self.assertIn("svc", buf.getvalue())


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestStatsMain(unittest.TestCase):
    def _make_reader(self, metrics=None, events=None, spans=None):
        reader = MagicMock()
        reader.read_metrics.return_value = metrics or [_make_metric_record()]
        reader.read_events.return_value = events or []
        reader.read_spans.return_value = spans or []
        return reader

    def test_group_by_metric_returns_0(self):
        with patch("telemetry.otel.cli.stats.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.stats.OTLPReader", return_value=self._make_reader()):
                result = main([])
        self.assertEqual(result, 0)

    def test_group_by_resource_returns_0(self):
        with patch("telemetry.otel.cli.stats.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.stats.OTLPReader", return_value=self._make_reader()):
                result = main(["--group-by", "resource"])
        self.assertEqual(result, 0)

    def test_json_format(self):
        with patch("telemetry.otel.cli.stats.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.stats.OTLPReader", return_value=self._make_reader()):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    main(["--format", "json"])
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, dict)

    def test_data_dir_flag(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with patch("telemetry.otel.cli.stats.OTLPReader", return_value=self._make_reader()):
                result = main(["--data-dir", td])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
