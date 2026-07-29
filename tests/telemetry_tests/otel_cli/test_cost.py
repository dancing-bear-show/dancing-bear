"""Tests for telemetry/otel/cli/cost.py."""

from __future__ import annotations

import io
import json
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from unittest.mock import patch

from telemetry.otel.cli.cost import main
from telemetry.otel.cost_models import CostMetrics, DailyCost, ModelCost, ModelPerformance, SessionCost


def _make_session_cost(
    *,
    session_id: str = "abc123def456",
    api_calls: int = 10,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_creation_tokens: int = 50,
    cache_read_tokens: int = 200,
    cost: float = 0.05,
    efficiency_ratio: float = 0.5,
    first_seen: datetime | None = None,
    last_seen: datetime | None = None,
) -> SessionCost:
    return SessionCost(
        session_id=session_id,
        api_calls=api_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        cost=cost,
        efficiency_ratio=efficiency_ratio,
        first_seen=first_seen,
        last_seen=last_seen,
    )


def _make_cost_metrics(
    *,
    by_session: list[SessionCost] | None = None,
    by_model: list[ModelCost] | None = None,
    total_cost: float = 0.05,
) -> CostMetrics:
    return CostMetrics(
        total_api_calls=10,
        total_input_tokens=1000,
        total_output_tokens=500,
        total_cache_creation_tokens=50,
        total_cache_read_tokens=200,
        total_cost=total_cost,
        total_cache_savings=0.01,
        efficiency_ratio=0.5,
        by_session=by_session or [],
        by_model=by_model or [],
    )


def _make_model_cost(
    *,
    model_name: str = "claude-sonnet-4-6",
    api_calls: int = 5,
    cost: float = 0.03,
) -> ModelCost:
    return ModelCost(
        model_name=model_name,
        api_calls=api_calls,
        input_tokens=500,
        output_tokens=250,
        cache_creation_tokens=25,
        cache_read_tokens=100,
        cost=cost,
        efficiency_ratio=0.5,
    )


def _make_daily_cost(date: str = "2026-04-16") -> DailyCost:
    return DailyCost(
        date=date,
        api_calls=5,
        cost=0.02,
        input_tokens=500,
        output_tokens=250,
        cache_creation_tokens=25,
        cache_read_tokens=100,
    )


def _make_model_perf() -> ModelPerformance:
    return ModelPerformance(
        model_name="claude-sonnet-4-6",
        api_calls=10,
        error_count=1,
        error_rate=0.1,
        avg_latency_ms=800.0,
        p95_latency_ms=1500.0,
        cost=0.05,
        input_tokens=1000,
        output_tokens=500,
    )


# ---------------------------------------------------------------------------
# main — table format
# ---------------------------------------------------------------------------


class TestCostMainTable(unittest.TestCase):
    def _run(self, argv: list[str], metrics: CostMetrics) -> tuple[int, str]:
        with patch("telemetry.otel.cli.cost.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.cost.get_all_costs", return_value=metrics):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    result = main(argv)
        return result, buf.getvalue()

    def test_table_format_returns_0(self):
        result, _ = self._run([], _make_cost_metrics())
        self.assertEqual(result, 0)

    def test_table_shows_total_cost(self):
        _, output = self._run([], _make_cost_metrics(total_cost=1.23))
        self.assertIn("1.23", output)

    def test_session_breakdown_in_output(self):
        sc = _make_session_cost()
        metrics = _make_cost_metrics(by_session=[sc])
        _, output = self._run(["--breakdown", "session"], metrics)
        self.assertIn("Sessions", output)

    def test_model_breakdown_in_output(self):
        mc = _make_model_cost()
        metrics = _make_cost_metrics(by_model=[mc])
        _, output = self._run(["--breakdown", "model"], metrics)
        self.assertIn("Model", output)


# ---------------------------------------------------------------------------
# main — json format
# ---------------------------------------------------------------------------


class TestCostMainJson(unittest.TestCase):
    def _run_json(self, argv: list[str], metrics: CostMetrics) -> tuple[int, str]:
        with patch("telemetry.otel.cli.cost.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.cost.get_all_costs", return_value=metrics):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    result = main(["--format", "json"] + argv)
        return result, buf.getvalue()

    def test_json_output_has_total_cost(self):
        _, output = self._run_json([], _make_cost_metrics(total_cost=0.05))
        data = json.loads(output)
        self.assertIn("total_cost", data)

    def test_json_session_breakdown(self):
        sc = _make_session_cost()
        metrics = _make_cost_metrics(by_session=[sc])
        _, output = self._run_json(["--breakdown", "session"], metrics)
        data = json.loads(output)
        self.assertIn("by_session", data)


# ---------------------------------------------------------------------------
# main — --by-date
# ---------------------------------------------------------------------------


class TestCostMainByDate(unittest.TestCase):
    def test_by_date_table_returns_0(self):
        daily = [_make_daily_cost()]
        with patch("telemetry.otel.cli.cost.get_daily_costs", return_value=daily):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                result = main(["--by-date"])
        self.assertEqual(result, 0)
        self.assertIn("2026-04-16", buf.getvalue())

    def test_by_date_no_data_returns_0(self):
        with patch("telemetry.otel.cli.cost.get_daily_costs", return_value=[]):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                result = main(["--by-date"])
        self.assertEqual(result, 0)
        self.assertIn("No cost data", buf.getvalue())

    def test_by_date_json_returns_0(self):
        daily = [_make_daily_cost()]
        with patch("telemetry.otel.cli.cost.get_daily_costs", return_value=daily):
            result = main(["--by-date", "--format", "json"])
        self.assertEqual(result, 0)

    def test_by_date_invalid_since_returns_1(self):
        with patch("telemetry.otel.cli.cost.get_daily_costs", side_effect=ValueError("bad")):
            result = main(["--by-date", "--since", "bad"])
        self.assertEqual(result, 1)


# ---------------------------------------------------------------------------
# main — --perf --breakdown model
# ---------------------------------------------------------------------------


class TestCostMainModelPerf(unittest.TestCase):
    def test_model_perf_table_returns_0(self):
        perfs = [_make_model_perf()]
        with patch("telemetry.otel.cli.cost.get_model_performance", return_value=perfs):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                result = main(["--breakdown", "model", "--perf"])
        self.assertEqual(result, 0)
        self.assertIn("claude-sonnet-4-6", buf.getvalue())

    def test_model_perf_no_data_returns_0(self):
        with patch("telemetry.otel.cli.cost.get_model_performance", return_value=[]):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                result = main(["--breakdown", "model", "--perf"])
        self.assertEqual(result, 0)

    def test_model_perf_json_returns_0(self):
        perfs = [_make_model_perf()]
        with patch("telemetry.otel.cli.cost.get_model_performance", return_value=perfs):
            result = main(["--breakdown", "model", "--perf", "--format", "json"])
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# main — validation errors
# ---------------------------------------------------------------------------


class TestCostValidation(unittest.TestCase):
    def test_invalid_since_returns_2(self):
        with patch("telemetry.otel.cli.cost.OTLPDataDir.from_env"):
            result = main(["--since", "bad-value!!"])
        self.assertEqual(result, 2)

    def test_data_dir_flag_used(self):
        import tempfile
        metrics = _make_cost_metrics()
        with tempfile.TemporaryDirectory() as td:
            with patch("telemetry.otel.cli.cost.get_all_costs", return_value=metrics):
                result = main(["--data-dir", td])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
