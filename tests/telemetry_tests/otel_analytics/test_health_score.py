"""Tests for telemetry/otel/analytics/health_score.py."""

import unittest

from telemetry.otel.analytics.health_score import (
    _score_to_grade,
    calculate_health_score,
)

from tests.telemetry_tests.otel_analytics._shared_helpers import (
    _make_perf,
    _make_session_cost,
)


# ---------------------------------------------------------------------------
# _score_to_grade
# ---------------------------------------------------------------------------

class TestScoreToGrade(unittest.TestCase):

    def test_exactly_1_0_is_A(self):
        self.assertEqual(_score_to_grade(1.0), "A")

    def test_0_9_is_A(self):
        self.assertEqual(_score_to_grade(0.9), "A")

    def test_0_89_is_B(self):
        self.assertEqual(_score_to_grade(0.89), "B")

    def test_0_75_is_B(self):
        self.assertEqual(_score_to_grade(0.75), "B")

    def test_0_74_is_C(self):
        self.assertEqual(_score_to_grade(0.74), "C")

    def test_0_6_is_C(self):
        self.assertEqual(_score_to_grade(0.6), "C")

    def test_0_59_is_D(self):
        self.assertEqual(_score_to_grade(0.59), "D")

    def test_0_4_is_D(self):
        self.assertEqual(_score_to_grade(0.4), "D")

    def test_0_39_is_F(self):
        self.assertEqual(_score_to_grade(0.39), "F")

    def test_0_0_is_F(self):
        self.assertEqual(_score_to_grade(0.0), "F")


# ---------------------------------------------------------------------------
# calculate_health_score — no perf data
# ---------------------------------------------------------------------------

class TestCalculateHealthScoreNoPerfData(unittest.TestCase):

    def test_no_perf_returns_perfect_score(self):
        session = _make_session_cost(session_id="s1", perf=None)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.score, 1.0)

    def test_no_perf_returns_grade_A(self):
        session = _make_session_cost(perf=None)
        result = calculate_health_score(session)
        self.assertEqual(result.grade, "A")

    def test_no_perf_all_penalties_zero(self):
        session = _make_session_cost(perf=None)
        result = calculate_health_score(session)
        self.assertEqual(result.error_penalty, 0.0)
        self.assertEqual(result.tool_failure_penalty, 0.0)
        self.assertEqual(result.latency_penalty, 0.0)

    def test_no_perf_session_id_preserved(self):
        session = _make_session_cost(session_id="abc-xyz", perf=None)
        result = calculate_health_score(session)
        self.assertEqual(result.session_id, "abc-xyz")


# ---------------------------------------------------------------------------
# calculate_health_score — perfect perf (no errors/failures/latency)
# ---------------------------------------------------------------------------

class TestCalculateHealthScorePerfectPerf(unittest.TestCase):

    def test_perfect_perf_score_is_1(self):
        session = _make_session_cost(perf=_make_perf())
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.score, 1.0)

    def test_perfect_perf_grade_A(self):
        session = _make_session_cost(perf=_make_perf())
        result = calculate_health_score(session)
        self.assertEqual(result.grade, "A")

    def test_perfect_perf_all_penalties_zero(self):
        session = _make_session_cost(perf=_make_perf())
        result = calculate_health_score(session)
        self.assertEqual(result.error_penalty, 0.0)
        self.assertEqual(result.tool_failure_penalty, 0.0)
        self.assertEqual(result.latency_penalty, 0.0)


# ---------------------------------------------------------------------------
# calculate_health_score — error penalty
# ---------------------------------------------------------------------------

class TestCalculateHealthScoreErrorPenalty(unittest.TestCase):

    def test_error_rate_10pct_subtracts_0_3(self):
        # error_penalty = min(0.1 * 3, 0.4) = 0.3
        perf = _make_perf(error_rate=0.1)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.error_penalty, 0.3, places=3)
        self.assertAlmostEqual(result.score, 0.7, places=3)

    def test_error_penalty_capped_at_0_4(self):
        # error_penalty = min(0.2 * 3, 0.4) = min(0.6, 0.4) = 0.4
        perf = _make_perf(error_rate=0.2)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.error_penalty, 0.4, places=3)

    def test_high_error_rate_penalty_still_capped(self):
        perf = _make_perf(error_rate=1.0)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.error_penalty, 0.4, places=3)

    def test_error_penalty_low_rate(self):
        # error_penalty = min(0.01 * 3, 0.4) = 0.03
        perf = _make_perf(error_rate=0.01)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.error_penalty, 0.03, places=3)


# ---------------------------------------------------------------------------
# calculate_health_score — tool failure penalty
# ---------------------------------------------------------------------------

class TestCalculateHealthScoreToolPenalty(unittest.TestCase):

    def test_tool_failure_rate_10pct_subtracts_0_2(self):
        # tool_penalty = min(0.1 * 2, 0.3) = 0.2
        perf = _make_perf(tool_failure_rate=0.1)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.tool_failure_penalty, 0.2, places=3)
        self.assertAlmostEqual(result.score, 0.8, places=3)

    def test_tool_penalty_capped_at_0_3(self):
        # tool_penalty = min(0.2 * 2, 0.3) = min(0.4, 0.3) = 0.3
        perf = _make_perf(tool_failure_rate=0.2)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.tool_failure_penalty, 0.3, places=3)

    def test_tool_penalty_100pct_still_capped(self):
        perf = _make_perf(tool_failure_rate=1.0)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.tool_failure_penalty, 0.3, places=3)


# ---------------------------------------------------------------------------
# calculate_health_score — latency penalty
# ---------------------------------------------------------------------------

class TestCalculateHealthScoreLatencyPenalty(unittest.TestCase):

    def test_latency_below_5000ms_no_penalty(self):
        # max(0, (4999 - 5000) / 30000) = max(0, negative) = 0
        perf = _make_perf(avg_api_latency_ms=4999.0)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertEqual(result.latency_penalty, 0.0)

    def test_latency_exactly_5000ms_no_penalty(self):
        perf = _make_perf(avg_api_latency_ms=5000.0)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertEqual(result.latency_penalty, 0.0)

    def test_latency_35000ms_penalty_1_30th(self):
        # (35000 - 5000) / 30000 = 1.0; min(1.0, 0.3) = 0.3
        perf = _make_perf(avg_api_latency_ms=35000.0)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.latency_penalty, 0.3, places=3)

    def test_latency_penalty_capped_at_0_3_for_huge_latency(self):
        perf = _make_perf(avg_api_latency_ms=100000.0)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.latency_penalty, 0.3, places=3)

    def test_latency_20000ms_midrange_penalty(self):
        # (20000 - 5000) / 30000 = 0.5; min(0.5, 0.3) = 0.3
        perf = _make_perf(avg_api_latency_ms=20000.0)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.latency_penalty, 0.3, places=3)

    def test_latency_8000ms_small_penalty(self):
        # (8000 - 5000) / 30000 = 0.1
        perf = _make_perf(avg_api_latency_ms=8000.0)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.latency_penalty, 0.1, places=3)


# ---------------------------------------------------------------------------
# calculate_health_score — combined penalties and score floor at 0
# ---------------------------------------------------------------------------

class TestCalculateHealthScoreCombined(unittest.TestCase):

    def test_combined_penalties_summed(self):
        # error_penalty=0.3 + tool_penalty=0.2 + latency=0 = 0.5, score=0.5
        perf = _make_perf(error_rate=0.1, tool_failure_rate=0.1)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.score, 0.5, places=3)

    def test_score_floored_at_zero_when_all_penalties_max(self):
        # All three maxed: 0.4 + 0.3 + 0.3 = 1.0, score = max(0, 0.0) = 0.0
        perf = _make_perf(error_rate=1.0, tool_failure_rate=1.0, avg_api_latency_ms=100000.0)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertAlmostEqual(result.score, 0.0, places=3)

    def test_score_not_negative(self):
        perf = _make_perf(error_rate=1.0, tool_failure_rate=1.0, avg_api_latency_ms=100000.0)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertGreaterEqual(result.score, 0.0)

    def test_grade_F_when_worst_penalties(self):
        perf = _make_perf(error_rate=1.0, tool_failure_rate=1.0, avg_api_latency_ms=100000.0)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        self.assertEqual(result.grade, "F")

    def test_result_is_session_health_score_type(self):
        from telemetry.otel.cost_models import SessionHealthScore
        session = _make_session_cost(perf=_make_perf())
        result = calculate_health_score(session)
        self.assertIsInstance(result, SessionHealthScore)

    def test_score_is_rounded_to_3_decimal_places(self):
        # error_rate=1/3 → penalty = min(1/3 * 3, 0.4) = min(1.0, 0.4) = 0.4, score=0.6
        perf = _make_perf(error_rate=1 / 3)
        session = _make_session_cost(perf=perf)
        result = calculate_health_score(session)
        # Verify it's a 3-decimal-place number by checking round(0.6, 3)
        self.assertEqual(result.score, round(result.score, 3))


if __name__ == "__main__":
    unittest.main()
