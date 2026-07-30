"""Tests for telemetry/otel/analytics/anomaly.py."""

import unittest
from unittest import mock

from telemetry.otel.analytics.anomaly import _detect_from_metrics
from telemetry.otel.cost_models import AnomalyFlag, SessionCost

from tests.telemetry_tests.otel_analytics._shared_helpers import (
    _make_cost_metrics,
    _make_perf,
    _make_session_cost,
)


# ---------------------------------------------------------------------------
# _detect_from_metrics — fewer than 3 sessions
# ---------------------------------------------------------------------------

class TestDetectFromMetricsFewerThan3(unittest.TestCase):

    def test_empty_sessions_returns_empty(self):
        metrics = _make_cost_metrics([])
        result = _detect_from_metrics(metrics, threshold=2.0)
        self.assertEqual(result, [])

    def test_one_session_returns_empty(self):
        metrics = _make_cost_metrics([_make_session_cost("s1", cost=10.0)])
        result = _detect_from_metrics(metrics, threshold=2.0)
        self.assertEqual(result, [])

    def test_two_sessions_returns_empty(self):
        sessions = [
            _make_session_cost("s1", cost=1.0),
            _make_session_cost("s2", cost=100.0),
        ]
        metrics = _make_cost_metrics(sessions)
        result = _detect_from_metrics(metrics, threshold=2.0)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# _detect_from_metrics — all-identical values (zero std_dev)
# ---------------------------------------------------------------------------

class TestDetectFromMetricsZeroStdDev(unittest.TestCase):

    def test_all_identical_cost_no_flags(self):
        sessions = [_make_session_cost(f"s{i}", cost=5.0) for i in range(5)]
        metrics = _make_cost_metrics(sessions)
        result = _detect_from_metrics(metrics, threshold=2.0)
        # Cost metric has zero std_dev, so no cost flags
        cost_flags = [f for f in result if f.metric == "cost"]
        self.assertEqual(cost_flags, [])

    def test_all_identical_tokens_no_flags(self):
        # All have same billable_tokens (same input/output/cache_creation)
        sessions = [
            _make_session_cost(f"s{i}", input_tokens=100, output_tokens=50)
            for i in range(5)
        ]
        metrics = _make_cost_metrics(sessions)
        result = _detect_from_metrics(metrics, threshold=2.0)
        token_flags = [f for f in result if f.metric == "tokens"]
        self.assertEqual(token_flags, [])


# ---------------------------------------------------------------------------
# _detect_from_metrics — outlier detection
# ---------------------------------------------------------------------------

class TestDetectFromMetricsOutlierDetection(unittest.TestCase):

    def _make_outlier_sessions(self) -> list[SessionCost]:
        """10 normal sessions + 1 extreme cost outlier (z > 3.0 with population std_dev)."""
        return [
            _make_session_cost(f"normal-{i}", cost=1.0)
            for i in range(10)
        ] + [_make_session_cost("outlier", cost=1000.0)]

    def test_cost_outlier_flagged(self):
        metrics = _make_cost_metrics(self._make_outlier_sessions())
        result = _detect_from_metrics(metrics, threshold=2.0)
        cost_flags = [f for f in result if f.metric == "cost"]
        flagged_ids = [f.session_id for f in cost_flags]
        self.assertIn("outlier", flagged_ids)

    def test_normal_sessions_not_flagged_for_cost(self):
        metrics = _make_cost_metrics(self._make_outlier_sessions())
        result = _detect_from_metrics(metrics, threshold=2.0)
        cost_flags = [f for f in result if f.metric == "cost"]
        flagged_ids = [f.session_id for f in cost_flags]
        # The normal sessions should not be flagged
        self.assertNotIn("normal-0", flagged_ids)
        self.assertNotIn("normal-1", flagged_ids)
        self.assertNotIn("normal-2", flagged_ids)

    def test_anomaly_flag_fields_populated(self):
        metrics = _make_cost_metrics(self._make_outlier_sessions())
        result = _detect_from_metrics(metrics, threshold=2.0)
        cost_flags = [f for f in result if f.metric == "cost" and f.session_id == "outlier"]
        self.assertEqual(len(cost_flags), 1)
        flag = cost_flags[0]
        self.assertEqual(flag.session_id, "outlier")
        self.assertEqual(flag.metric, "cost")
        self.assertAlmostEqual(flag.value, 1000.0, places=3)
        self.assertGreater(flag.z_score, 2.0)
        self.assertGreater(flag.std_dev, 0.0)

    def test_threshold_higher_suppresses_flag(self):
        # With a very high threshold, even an outlier won't be flagged
        metrics = _make_cost_metrics(self._make_outlier_sessions())
        result = _detect_from_metrics(metrics, threshold=100.0)
        self.assertEqual(result, [])

    def test_flag_is_anomaly_flag_instance(self):
        # 10 normal + 1 extreme outlier ensures z > 2.0 so flags are produced
        sessions = [
            _make_session_cost(f"n{i}", cost=1.0) for i in range(10)
        ] + [_make_session_cost("out", cost=1000.0)]
        metrics = _make_cost_metrics(sessions)
        result = _detect_from_metrics(metrics, threshold=2.0)
        self.assertGreater(len(result), 0)
        for flag in result:
            self.assertIsInstance(flag, AnomalyFlag)


# ---------------------------------------------------------------------------
# _detect_from_metrics — latency metric
# ---------------------------------------------------------------------------

class TestDetectFromMetricsLatency(unittest.TestCase):

    def test_latency_outlier_flagged_when_perf_available(self):
        # 10 normal + 1 extreme slow to get z > 2.0 with population std_dev
        sessions = [
            _make_session_cost(f"n{i}", perf=_make_perf(avg_api_latency_ms=100.0))
            for i in range(10)
        ] + [_make_session_cost("slow", perf=_make_perf(avg_api_latency_ms=100000.0))]
        metrics = _make_cost_metrics(sessions)
        result = _detect_from_metrics(metrics, threshold=2.0)
        latency_flags = [f for f in result if f.metric == "latency"]
        flagged_ids = [f.session_id for f in latency_flags]
        self.assertIn("slow", flagged_ids)

    def test_latency_skipped_when_fewer_than_3_perf_sessions(self):
        # Only 2 sessions have perf — latency metric should be skipped
        sessions = [
            _make_session_cost("n1", perf=_make_perf(100.0)),
            _make_session_cost("n2", perf=_make_perf(100.0)),
            _make_session_cost("n3", perf=None),  # no perf
            _make_session_cost("n4", perf=None),  # no perf
        ]
        metrics = _make_cost_metrics(sessions)
        result = _detect_from_metrics(metrics, threshold=2.0)
        latency_flags = [f for f in result if f.metric == "latency"]
        self.assertEqual(latency_flags, [])

    def test_sessions_without_perf_excluded_from_latency(self):
        # 3 sessions with perf + 1 without — the without-perf should not appear in latency flags
        sessions = [
            _make_session_cost("n1", perf=_make_perf(100.0)),
            _make_session_cost("n2", perf=_make_perf(100.0)),
            _make_session_cost("n3", perf=_make_perf(100.0)),
            _make_session_cost("no-perf", perf=None),
        ]
        metrics = _make_cost_metrics(sessions)
        result = _detect_from_metrics(metrics, threshold=2.0)
        latency_flags = [f for f in result if f.metric == "latency"]
        flagged_ids = [f.session_id for f in latency_flags]
        self.assertNotIn("no-perf", flagged_ids)


# ---------------------------------------------------------------------------
# _detect_from_metrics — token metric
# ---------------------------------------------------------------------------

class TestDetectFromMetricsTokens(unittest.TestCase):

    def test_token_outlier_flagged(self):
        # billable_tokens = input + output + cache_creation.
        # Need 10 normal + 1 extreme outlier so z > 2.0 (with population std_dev,
        # 3 normal + 1 outlier only achieves z ≈ 1.73 which is below threshold).
        sessions = [
            _make_session_cost(f"n{i}", input_tokens=100, output_tokens=50)
            for i in range(10)
        ] + [_make_session_cost("big", input_tokens=100000, output_tokens=50000)]
        metrics = _make_cost_metrics(sessions)
        result = _detect_from_metrics(metrics, threshold=2.0)
        token_flags = [f for f in result if f.metric == "tokens"]
        flagged_ids = [f.session_id for f in token_flags]
        self.assertIn("big", flagged_ids)

    def test_all_three_metrics_appear_independently(self):
        # Force outliers in all three dimensions simultaneously.
        # 10 normal + 1 extreme outlier gives z > 3.0.
        sessions = [
            _make_session_cost(f"n{i}", cost=1.0, input_tokens=100, perf=_make_perf(100.0))
            for i in range(10)
        ] + [
            _make_session_cost("out", cost=1000.0, input_tokens=100000, perf=_make_perf(100000.0)),
        ]
        metrics = _make_cost_metrics(sessions)
        result = _detect_from_metrics(metrics, threshold=2.0)
        metric_types = {f.metric for f in result}
        # Should have cost and tokens flags for the outlier
        self.assertIn("cost", metric_types)
        self.assertIn("tokens", metric_types)


# ---------------------------------------------------------------------------
# detect_anomalies — integration test via mock
# ---------------------------------------------------------------------------

class TestDetectAnomaliesIntegration(unittest.TestCase):

    @mock.patch("telemetry.otel.analytics.anomaly.get_all_costs")
    def test_calls_get_all_costs_with_data_dir_and_since(self, mock_get_all_costs):
        from telemetry.otel.analytics.anomaly import detect_anomalies
        from telemetry.otel.reader import OTLPDataDir

        mock_get_all_costs.return_value = _make_cost_metrics([])
        data_dir = OTLPDataDir.default()

        from datetime import datetime, timezone
        since = datetime(2026, 7, 1, tzinfo=timezone.utc)

        detect_anomalies(data_dir=data_dir, since=since, threshold=2.5)

        mock_get_all_costs.assert_called_once_with(data_dir=data_dir, since=since)

    @mock.patch("telemetry.otel.analytics.anomaly.get_all_costs")
    def test_returns_empty_when_no_sessions(self, mock_get_all_costs):
        from telemetry.otel.analytics.anomaly import detect_anomalies
        mock_get_all_costs.return_value = _make_cost_metrics([])
        result = detect_anomalies()
        self.assertEqual(result, [])

    @mock.patch("telemetry.otel.analytics.anomaly.get_all_costs")
    def test_flags_outlier_session(self, mock_get_all_costs):
        from telemetry.otel.analytics.anomaly import detect_anomalies
        # 10 normal + 1 extreme outlier ensures z > 2.0
        sessions = [
            _make_session_cost(f"n{i}", cost=1.0) for i in range(10)
        ] + [_make_session_cost("outlier", cost=1000.0)]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = detect_anomalies(threshold=2.0)
        flagged_ids = [f.session_id for f in result]
        self.assertIn("outlier", flagged_ids)


if __name__ == "__main__":
    unittest.main()
