"""Tests for telemetry/otel/cost_models.py."""

import unittest
from datetime import datetime, timedelta, timezone

from telemetry.otel.cost_models import (
    AnomalyFlag,
    CostMetrics,
    DailyCost,
    ModelCost,
    ModelPerformance,
    PromptMetrics,
    SessionCluster,
    SessionComparison,
    SessionCost,
    SessionHealthScore,
    SessionPerf,
    ToolErrorSummary,
)


def _make_session_cost(**overrides) -> SessionCost:
    defaults = dict(
        session_id="sess-1",
        api_calls=10,
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=20,
        cache_read_tokens=300,
        cost=0.05,
        efficiency_ratio=1.5,
    )
    defaults.update(overrides)
    return SessionCost(**defaults)


def _make_model_cost(**overrides) -> ModelCost:
    defaults = dict(
        model_name="claude-sonnet",
        api_calls=5,
        input_tokens=200,
        output_tokens=80,
        cache_creation_tokens=10,
        cache_read_tokens=150,
        cost=0.03,
        efficiency_ratio=2.0,
    )
    defaults.update(overrides)
    return ModelCost(**defaults)


def _make_cost_metrics(**overrides) -> CostMetrics:
    defaults = dict(
        total_api_calls=20,
        total_input_tokens=400,
        total_output_tokens=200,
        total_cache_creation_tokens=50,
        total_cache_read_tokens=500,
        total_cost=0.10,
        total_cache_savings=0.02,
        efficiency_ratio=1.8,
    )
    defaults.update(overrides)
    return CostMetrics(**defaults)


class TestSessionCostBillableTokens(unittest.TestCase):
    def test_billable_tokens_sums_input_output_cache_creation(self):
        sc = _make_session_cost(input_tokens=100, output_tokens=50, cache_creation_tokens=20)
        self.assertEqual(sc.billable_tokens, 170)

    def test_billable_tokens_excludes_cache_read(self):
        sc = _make_session_cost(
            input_tokens=100,
            output_tokens=50,
            cache_creation_tokens=20,
            cache_read_tokens=9999,
        )
        self.assertEqual(sc.billable_tokens, 170)

    def test_billable_tokens_all_zero(self):
        sc = _make_session_cost(input_tokens=0, output_tokens=0, cache_creation_tokens=0)
        self.assertEqual(sc.billable_tokens, 0)


class TestSessionCostDurationMinutes(unittest.TestCase):
    def test_duration_minutes_with_timestamps(self):
        t0 = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 4, 16, 10, 30, 0, tzinfo=timezone.utc)
        sc = _make_session_cost(first_seen=t0, last_seen=t1)
        self.assertAlmostEqual(sc.duration_minutes, 30.0, places=5)

    def test_duration_minutes_none_when_no_timestamps(self):
        sc = _make_session_cost(first_seen=None, last_seen=None)
        self.assertIsNone(sc.duration_minutes)

    def test_duration_minutes_none_when_only_first_seen(self):
        t0 = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
        sc = _make_session_cost(first_seen=t0, last_seen=None)
        self.assertIsNone(sc.duration_minutes)

    def test_duration_minutes_none_when_only_last_seen(self):
        t1 = datetime(2026, 4, 16, 10, 30, 0, tzinfo=timezone.utc)
        sc = _make_session_cost(first_seen=None, last_seen=t1)
        self.assertIsNone(sc.duration_minutes)

    def test_duration_minutes_fractional(self):
        t0 = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(seconds=90)  # 90 seconds = 1.5 minutes
        sc = _make_session_cost(first_seen=t0, last_seen=t1)
        self.assertAlmostEqual(sc.duration_minutes, 1.5, places=5)


class TestModelCostBillableTokens(unittest.TestCase):
    def test_billable_tokens_sums_correctly(self):
        mc = _make_model_cost(input_tokens=200, output_tokens=80, cache_creation_tokens=10)
        self.assertEqual(mc.billable_tokens, 290)

    def test_billable_tokens_excludes_cache_read(self):
        mc = _make_model_cost(
            input_tokens=200,
            output_tokens=80,
            cache_creation_tokens=10,
            cache_read_tokens=9999,
        )
        self.assertEqual(mc.billable_tokens, 290)

    def test_billable_tokens_zero(self):
        mc = _make_model_cost(input_tokens=0, output_tokens=0, cache_creation_tokens=0)
        self.assertEqual(mc.billable_tokens, 0)


class TestCostMetricsTotalBillableTokens(unittest.TestCase):
    def test_total_billable_tokens_sums_correctly(self):
        cm = _make_cost_metrics(
            total_input_tokens=400,
            total_output_tokens=200,
            total_cache_creation_tokens=50,
        )
        self.assertEqual(cm.total_billable_tokens, 650)

    def test_total_billable_tokens_excludes_cache_read(self):
        cm = _make_cost_metrics(
            total_input_tokens=400,
            total_output_tokens=200,
            total_cache_creation_tokens=50,
            total_cache_read_tokens=9999,
        )
        self.assertEqual(cm.total_billable_tokens, 650)


class TestCostMetricsCacheSavingsPercent(unittest.TestCase):
    def test_cache_savings_percent_normal(self):
        # billable = 400+200+50 = 650, cache_read = 500, total = 1150
        # expected = 500/1150 * 100
        cm = _make_cost_metrics(
            total_input_tokens=400,
            total_output_tokens=200,
            total_cache_creation_tokens=50,
            total_cache_read_tokens=500,
        )
        expected = (500 / 1150) * 100.0
        self.assertAlmostEqual(cm.cache_savings_percent, expected, places=5)

    def test_cache_savings_percent_zero_division_guard(self):
        cm = _make_cost_metrics(
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_creation_tokens=0,
            total_cache_read_tokens=0,
        )
        self.assertEqual(cm.cache_savings_percent, 0.0)

    def test_cache_savings_percent_no_cache_reads(self):
        cm = _make_cost_metrics(
            total_input_tokens=100,
            total_output_tokens=50,
            total_cache_creation_tokens=10,
            total_cache_read_tokens=0,
        )
        self.assertEqual(cm.cache_savings_percent, 0.0)

    def test_cache_savings_percent_all_cache(self):
        # billable = 0, cache_read = 500 → 100%
        cm = _make_cost_metrics(
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_creation_tokens=0,
            total_cache_read_tokens=500,
        )
        self.assertAlmostEqual(cm.cache_savings_percent, 100.0, places=5)


class TestSessionPerfMutableDefaults(unittest.TestCase):
    def test_error_status_codes_independent_instances(self):
        sp1 = SessionPerf()
        sp2 = SessionPerf()
        # SessionPerf is frozen so we verify they are distinct objects
        self.assertIsNot(sp1.error_status_codes, sp2.error_status_codes)

    def test_model_mix_independent_instances(self):
        sp1 = SessionPerf()
        sp2 = SessionPerf()
        self.assertIsNot(sp1.model_mix, sp2.model_mix)

    def test_tool_usage_independent_instances(self):
        sp1 = SessionPerf()
        sp2 = SessionPerf()
        self.assertIsNot(sp1.tool_usage, sp2.tool_usage)


class TestCostMetricsMutableDefaults(unittest.TestCase):
    def test_by_session_independent_instances(self):
        cm1 = _make_cost_metrics()
        cm2 = _make_cost_metrics()
        self.assertIsNot(cm1.by_session, cm2.by_session)

    def test_by_model_independent_instances(self):
        cm1 = _make_cost_metrics()
        cm2 = _make_cost_metrics()
        self.assertIsNot(cm1.by_model, cm2.by_model)


class TestSessionClusterMutableDefault(unittest.TestCase):
    def test_features_independent_instances(self):
        sc1 = SessionCluster(session_id="a", cluster_id=0, cluster_label="low-cost")
        sc2 = SessionCluster(session_id="b", cluster_id=1, cluster_label="high-cost")
        self.assertIsNot(sc1.features, sc2.features)


class TestDailyCostConstruction(unittest.TestCase):
    def test_fields_accessible(self):
        dc = DailyCost(
            date="2026-04-16",
            api_calls=5,
            cost=0.02,
            input_tokens=100,
            output_tokens=40,
            cache_creation_tokens=10,
            cache_read_tokens=50,
        )
        self.assertEqual(dc.date, "2026-04-16")
        self.assertEqual(dc.api_calls, 5)
        self.assertAlmostEqual(dc.cost, 0.02, places=6)
        self.assertEqual(dc.cache_read_tokens, 50)


class TestToolErrorSummaryConstruction(unittest.TestCase):
    def test_fields_accessible(self):
        tes = ToolErrorSummary(
            tool_name="Bash",
            total_calls=20,
            failures=4,
            failure_rate=0.2,
            avg_duration_ms=150.0,
            sessions_affected=3,
        )
        self.assertEqual(tes.tool_name, "Bash")
        self.assertEqual(tes.failures, 4)
        self.assertAlmostEqual(tes.failure_rate, 0.2, places=5)
        self.assertEqual(tes.sessions_affected, 3)


class TestModelPerformanceConstruction(unittest.TestCase):
    def test_fields_accessible(self):
        mp = ModelPerformance(
            model_name="claude-haiku",
            api_calls=30,
            error_count=2,
            error_rate=0.067,
            avg_latency_ms=200.0,
            p95_latency_ms=500.0,
            cost=0.01,
            input_tokens=300,
            output_tokens=120,
        )
        self.assertEqual(mp.model_name, "claude-haiku")
        self.assertEqual(mp.error_count, 2)
        self.assertAlmostEqual(mp.p95_latency_ms, 500.0, places=5)


class TestPromptMetricsConstruction(unittest.TestCase):
    def test_fields_accessible(self):
        pm = PromptMetrics(
            prompt_id="p1",
            session_id="s1",
            timestamp="2026-04-16T10:00:00Z",
            prompt_length=512,
            api_calls=3,
            input_tokens=200,
            output_tokens=80,
            cost=0.005,
            tool_calls=5,
            tool_failures=1,
            duration_ms=1200.0,
        )
        self.assertEqual(pm.prompt_id, "p1")
        self.assertEqual(pm.prompt_length, 512)
        self.assertAlmostEqual(pm.duration_ms, 1200.0, places=5)

    def test_timestamp_can_be_none(self):
        pm = PromptMetrics(
            prompt_id="p2",
            session_id="s2",
            timestamp=None,
            prompt_length=0,
            api_calls=0,
            input_tokens=0,
            output_tokens=0,
            cost=0.0,
            tool_calls=0,
            tool_failures=0,
            duration_ms=0.0,
        )
        self.assertIsNone(pm.timestamp)


class TestSessionHealthScoreConstruction(unittest.TestCase):
    def test_fields_accessible(self):
        shs = SessionHealthScore(
            session_id="s1",
            score=0.85,
            error_penalty=0.05,
            tool_failure_penalty=0.03,
            latency_penalty=0.07,
            grade="B",
        )
        self.assertEqual(shs.session_id, "s1")
        self.assertAlmostEqual(shs.score, 0.85, places=5)
        self.assertEqual(shs.grade, "B")


class TestSessionComparisonConstruction(unittest.TestCase):
    def test_fields_accessible(self):
        sa = _make_session_cost(session_id="a")
        sb = _make_session_cost(session_id="b")
        sc = SessionComparison(
            session_a=sa,
            session_b=sb,
            cost_delta=0.01,
            token_delta=50,
            duration_delta=timedelta(minutes=5),
            error_delta=2,
        )
        self.assertIs(sc.session_a, sa)
        self.assertIs(sc.session_b, sb)
        self.assertEqual(sc.token_delta, 50)
        self.assertEqual(sc.duration_delta, timedelta(minutes=5))

    def test_duration_delta_can_be_none(self):
        sa = _make_session_cost(session_id="a")
        sb = _make_session_cost(session_id="b")
        sc = SessionComparison(
            session_a=sa,
            session_b=sb,
            cost_delta=0.0,
            token_delta=0,
            duration_delta=None,
            error_delta=0,
        )
        self.assertIsNone(sc.duration_delta)


class TestAnomalyFlagConstruction(unittest.TestCase):
    def test_fields_accessible(self):
        af = AnomalyFlag(
            session_id="s1",
            metric="cost",
            value=5.0,
            mean=1.0,
            std_dev=0.5,
            z_score=8.0,
        )
        self.assertEqual(af.metric, "cost")
        self.assertAlmostEqual(af.z_score, 8.0, places=5)


class TestSessionClusterConstruction(unittest.TestCase):
    def test_fields_accessible(self):
        sc = SessionCluster(
            session_id="s1",
            cluster_id=2,
            cluster_label="high-cost",
            features={"cost": 5.0, "tokens": 1000.0},
        )
        self.assertEqual(sc.cluster_id, 2)
        self.assertEqual(sc.cluster_label, "high-cost")
        self.assertEqual(sc.features["cost"], 5.0)

    def test_features_defaults_to_empty_dict(self):
        sc = SessionCluster(session_id="s2", cluster_id=0, cluster_label="low-cost")
        self.assertEqual(sc.features, {})


if __name__ == "__main__":
    unittest.main()
