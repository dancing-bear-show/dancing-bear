"""Tests for telemetry/otel/cli/query.py."""

from __future__ import annotations

import io
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from telemetry.otel.cli.query import (
    _build_metric_result,
    _filter_data_points,
    _filter_metrics,
    main,
)


def _make_data_point(*, timestamp: datetime | None = None, value: float = 1.0):
    dp = MagicMock()
    dp.timestamp = timestamp or datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
    dp.value = value
    return dp


def _make_metric(*, name: str = "cpu.usage", unit: str = "percent", data_points_count: int = 2):
    m = MagicMock()
    m.name = name
    m.unit = unit
    m.data_points = [_make_data_point() for _ in range(data_points_count)]
    return m


def _make_record(metrics: list | None = None):
    record = MagicMock()
    record.metrics = metrics or [_make_metric()]
    record.metrics_by_name.return_value = []
    return record


# ---------------------------------------------------------------------------
# _filter_data_points
# ---------------------------------------------------------------------------


class TestFilterDataPoints(unittest.TestCase):
    def test_no_cutoff_returns_all(self):
        dps = [_make_data_point(), _make_data_point()]
        result = _filter_data_points(dps, cutoff_time=None)
        self.assertEqual(len(result), 2)

    def test_cutoff_filters_old(self):
        old_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        new_ts = datetime(2026, 4, 16, tzinfo=timezone.utc)
        cutoff = datetime(2026, 3, 1, tzinfo=timezone.utc)
        dps = [_make_data_point(timestamp=old_ts), _make_data_point(timestamp=new_ts)]
        result = _filter_data_points(dps, cutoff_time=cutoff)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].timestamp, new_ts)


# ---------------------------------------------------------------------------
# _build_metric_result
# ---------------------------------------------------------------------------


class TestBuildMetricResult(unittest.TestCase):
    def test_builds_dict(self):
        m = _make_metric(name="cpu.usage", unit="percent")
        dps = m.data_points
        result = _build_metric_result(m, dps)
        self.assertEqual(result["name"], "cpu.usage")
        self.assertEqual(result["unit"], "percent")
        self.assertEqual(result["points"], len(dps))

    def test_empty_data_points(self):
        m = _make_metric()
        result = _build_metric_result(m, [])
        self.assertIsNone(result["latest"])


# ---------------------------------------------------------------------------
# _filter_metrics
# ---------------------------------------------------------------------------


class TestFilterMetrics(unittest.TestCase):
    def test_no_pattern_returns_all(self):
        records = [_make_record()]
        result = _filter_metrics(records, metric_pattern=None, cutoff_time=None)
        self.assertEqual(len(result), 1)

    def test_pattern_uses_metrics_by_name(self):
        record = _make_record()
        record.metrics_by_name.return_value = [_make_metric(name="matched")]
        result = _filter_metrics([record], metric_pattern="matched*", cutoff_time=None)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "matched")

    def test_empty_data_points_excluded(self):
        m = _make_metric(data_points_count=0)
        record = MagicMock()
        record.metrics = [m]
        result = _filter_metrics([record], metric_pattern=None, cutoff_time=None)
        self.assertEqual(len(result), 0)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestQueryMain(unittest.TestCase):
    def _run(self, argv: list[str], records: list | None = None) -> tuple[int, str]:
        if records is None:
            records = [_make_record()]
        with patch("telemetry.otel.cli.query.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.query.OTLPReader") as mock_reader_cls:
                mock_reader_cls.return_value.read_metrics.return_value = records
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    result = main(argv)
        return result, buf.getvalue()

    def test_table_returns_0(self):
        result, _ = self._run([])
        self.assertEqual(result, 0)

    def test_no_metrics_prints_no_metrics(self):
        result, output = self._run([], records=[])
        self.assertEqual(result, 0)
        self.assertIn("No metrics", output)

    def test_json_format_returns_0(self):
        result, _ = self._run(["--format", "json"])
        self.assertEqual(result, 0)

    def test_invalid_since_returns_2(self):
        with patch("telemetry.otel.cli.query.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.query.OTLPReader") as mock_reader_cls:
                mock_reader_cls.return_value.read_metrics.return_value = []
                with patch("sys.stderr", io.StringIO()):
                    result = main(["--since", "bad!!!"])
        self.assertEqual(result, 2)

    def test_data_dir_flag(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with patch("telemetry.otel.cli.query.OTLPReader") as mock_reader_cls:
                mock_reader_cls.return_value.read_metrics.return_value = []
                result = main(["--data-dir", td])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
