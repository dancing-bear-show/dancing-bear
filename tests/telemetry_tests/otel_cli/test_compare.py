"""Tests for telemetry/otel/cli/compare.py."""

from __future__ import annotations

import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from telemetry.otel.cli.compare import _format_delta, main
from telemetry.otel.cost_models import SessionComparison, SessionCost


def _make_session_cost(
    *,
    session_id: str = "session-a",
    cost: float = 0.05,
    api_calls: int = 10,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_creation_tokens: int = 50,
    cache_read_tokens: int = 200,
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
        efficiency_ratio=0.5,
        first_seen=first_seen,
        last_seen=last_seen,
    )


def _make_comparison(
    *,
    cost_delta: float = 0.01,
    token_delta: int = 100,
    duration_delta: timedelta | None = None,
    error_delta: int = 0,
) -> SessionComparison:
    a = _make_session_cost(session_id="session-a", cost=0.05)
    b = _make_session_cost(session_id="session-b", cost=0.06)
    return SessionComparison(
        session_a=a,
        session_b=b,
        cost_delta=cost_delta,
        token_delta=token_delta,
        duration_delta=duration_delta,
        error_delta=error_delta,
    )


# ---------------------------------------------------------------------------
# _format_delta
# ---------------------------------------------------------------------------


class TestFormatDelta(unittest.TestCase):
    def test_positive_float(self):
        result = _format_delta(0.05)
        self.assertIn("+", result)

    def test_negative_float(self):
        result = _format_delta(-0.02)
        self.assertIn("-", result)

    def test_positive_int(self):
        result = _format_delta(100)
        self.assertIn("+", result)

    def test_zero_has_no_plus(self):
        result = _format_delta(0)
        self.assertNotIn("+", result)

    def test_suffix_appended(self):
        result = _format_delta(5.0, suffix="%")
        self.assertIn("%", result)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestCompareMain(unittest.TestCase):
    def _run(self, argv: list[str], comparison: SessionComparison | None = None) -> tuple[int, str]:
        if comparison is None:
            comparison = _make_comparison()
        with patch("telemetry.otel.cli.compare.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.compare.compare_sessions", return_value=comparison):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    result = main(argv)
        return result, buf.getvalue()

    def test_table_format_returns_0(self):
        result, _ = self._run(["session-a", "session-b"])
        self.assertEqual(result, 0)

    def test_table_shows_both_sessions(self):
        _, output = self._run(["session-a", "session-b"])
        self.assertIn("session-a", output)
        self.assertIn("session-b", output)

    def test_json_format_returns_0(self):
        result, output = self._run(["session-a", "session-b", "--format", "json"])
        self.assertEqual(result, 0)
        data = json.loads(output)
        self.assertIn("session_a", data)
        self.assertIn("session_b", data)
        self.assertIn("deltas", data)

    def test_compare_error_returns_1(self):
        with patch("telemetry.otel.cli.compare.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.compare.compare_sessions", side_effect=ValueError("not found")):
                buf = io.StringIO()
                with patch("sys.stderr", buf):
                    result = main(["session-a", "session-b"])
        self.assertEqual(result, 1)
        self.assertIn("not found", buf.getvalue())

    def test_duration_delta_shown_in_table(self):
        comp = _make_comparison(duration_delta=timedelta(minutes=15))
        _, output = self._run(["session-a", "session-b"], comparison=comp)
        self.assertIn("Duration", output)

    def test_data_dir_flag(self):
        import tempfile
        comp = _make_comparison()
        with tempfile.TemporaryDirectory() as td:
            with patch("telemetry.otel.cli.compare.compare_sessions", return_value=comp):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    result = main(["session-a", "session-b", "--data-dir", td])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
