"""Tests for telemetry/otel/analytics/compare.py."""

import unittest
from datetime import timedelta
from unittest import mock

from tests.telemetry_tests.otel_analytics._shared_helpers import (
    _make_cost_metrics,
    _make_perf,
    _make_session_cost,
    _utc,
)


# ---------------------------------------------------------------------------
# compare_sessions — happy path
# ---------------------------------------------------------------------------

class TestCompareSessions(unittest.TestCase):

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_cost_delta_computed_correctly(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        sessions = [
            _make_session_cost("a", cost=1.0),
            _make_session_cost("b", cost=3.0),
        ]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = compare_sessions("a", "b")
        self.assertAlmostEqual(result.cost_delta, 2.0, places=6)

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_cost_delta_negative_when_b_cheaper(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        sessions = [
            _make_session_cost("a", cost=5.0),
            _make_session_cost("b", cost=2.0),
        ]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = compare_sessions("a", "b")
        self.assertAlmostEqual(result.cost_delta, -3.0, places=6)

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_token_delta_computed(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        # billable_tokens sums input, output, and cache_creation tokens
        sessions = [
            _make_session_cost("a", input_tokens=1000, output_tokens=500),  # 1500 billable
            _make_session_cost("b", input_tokens=2000, output_tokens=1000),  # 3000 billable
        ]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = compare_sessions("a", "b")
        self.assertEqual(result.token_delta, 1500)

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_session_a_and_b_attached_to_result(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        sa = _make_session_cost("alpha")
        sb = _make_session_cost("beta")
        mock_get_all_costs.return_value = _make_cost_metrics([sa, sb])
        result = compare_sessions("alpha", "beta")
        self.assertEqual(result.session_a.session_id, "alpha")
        self.assertEqual(result.session_b.session_id, "beta")

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_duration_delta_computed_when_timestamps_available(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        t0 = _utc(2026, 7, 1, 10)
        sessions = [
            _make_session_cost("a", first_seen=t0, last_seen=t0 + timedelta(minutes=30)),
            _make_session_cost("b", first_seen=t0, last_seen=t0 + timedelta(minutes=60)),
        ]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = compare_sessions("a", "b")
        self.assertIsNotNone(result.duration_delta)
        self.assertAlmostEqual(result.duration_delta.total_seconds(), 1800.0, places=0)

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_duration_delta_none_when_timestamps_missing(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        sessions = [
            _make_session_cost("a"),
            _make_session_cost("b"),
        ]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = compare_sessions("a", "b")
        self.assertIsNone(result.duration_delta)

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_error_delta_computed_from_perf(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        sessions = [
            _make_session_cost("a", perf=_make_perf(error_count=1)),
            _make_session_cost("b", perf=_make_perf(error_count=4)),
        ]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = compare_sessions("a", "b")
        self.assertEqual(result.error_delta, 3)

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_error_delta_zero_when_no_perf(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        sessions = [
            _make_session_cost("a", perf=None),
            _make_session_cost("b", perf=None),
        ]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = compare_sessions("a", "b")
        self.assertEqual(result.error_delta, 0)

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_error_delta_negative_when_b_has_fewer_errors(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        sessions = [
            _make_session_cost("a", perf=_make_perf(error_count=5)),
            _make_session_cost("b", perf=_make_perf(error_count=2)),
        ]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = compare_sessions("a", "b")
        self.assertEqual(result.error_delta, -3)

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_passes_data_dir_to_get_all_costs(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        from telemetry.otel.reader import OTLPDataDir
        sessions = [_make_session_cost("a"), _make_session_cost("b")]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        data_dir = OTLPDataDir.default()
        compare_sessions("a", "b", data_dir=data_dir)
        mock_get_all_costs.assert_called_once_with(data_dir=data_dir)

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_result_is_session_comparison_type(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        from telemetry.otel.cost_models import SessionComparison
        sessions = [_make_session_cost("a"), _make_session_cost("b")]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = compare_sessions("a", "b")
        self.assertIsInstance(result, SessionComparison)


# ---------------------------------------------------------------------------
# compare_sessions — error paths
# ---------------------------------------------------------------------------

class TestCompareSessionsErrors(unittest.TestCase):

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_raises_when_session_a_not_found(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        mock_get_all_costs.return_value = _make_cost_metrics([
            _make_session_cost("b"),
        ])
        with self.assertRaises(ValueError) as ctx:
            compare_sessions("missing-a", "b")
        self.assertIn("missing-a", str(ctx.exception))

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_raises_when_session_b_not_found(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        mock_get_all_costs.return_value = _make_cost_metrics([
            _make_session_cost("a"),
        ])
        with self.assertRaises(ValueError) as ctx:
            compare_sessions("a", "missing-b")
        self.assertIn("missing-b", str(ctx.exception))

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_raises_when_no_sessions(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        mock_get_all_costs.return_value = _make_cost_metrics([])
        with self.assertRaises(ValueError):
            compare_sessions("a", "b")

    @mock.patch("telemetry.otel.analytics.compare.get_all_costs")
    def test_same_session_compared_to_itself_zero_deltas(self, mock_get_all_costs):
        from telemetry.otel.analytics.compare import compare_sessions
        sessions = [_make_session_cost("a", cost=2.5)]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = compare_sessions("a", "a")
        self.assertAlmostEqual(result.cost_delta, 0.0, places=6)
        self.assertEqual(result.token_delta, 0)
        self.assertEqual(result.error_delta, 0)


if __name__ == "__main__":
    unittest.main()
