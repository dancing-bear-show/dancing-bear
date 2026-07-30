"""Tests for telemetry/otel/cli/sessions.py."""

from __future__ import annotations

import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from telemetry.otel.cli.sessions import (
    _extract_event_detail,
    _extract_tool_result_detail,
    _filter_sessions,
    _format_api_request_detail,
    _format_model_mix,
    _format_timeline_entry,
    _has_errors,
    _print_error_codes_standalone,
    _print_perf_details,
    _print_perf_summary,
    _print_session_header,
    main,
)
from telemetry.otel.cost_models import CostMetrics, SessionCost, SessionPerf


def _make_perf(
    *,
    error_count: int = 0,
    tool_failures: int = 0,
    error_rate: float = 0.0,
    tool_failure_rate: float = 0.0,
    avg_api_latency_ms: float = 0.0,
    p95_api_latency_ms: float = 0.0,
    prompt_count: int = 0,
    autonomy_ratio: float = 0.0,
    model_mix: dict | None = None,
    terminal_type: str = "",
    total_api_wait_ms: float = 0.0,
    tool_usage: dict | None = None,
    error_status_codes: dict | None = None,
) -> SessionPerf:
    return SessionPerf(
        error_count=error_count,
        error_rate=error_rate,
        error_status_codes=error_status_codes or {},
        tool_calls=0,
        tool_failures=tool_failures,
        tool_failure_rate=tool_failure_rate,
        avg_api_latency_ms=avg_api_latency_ms,
        p95_api_latency_ms=p95_api_latency_ms,
        prompt_count=prompt_count,
        autonomy_ratio=autonomy_ratio,
        model_mix=model_mix or {},
        terminal_type=terminal_type,
        total_api_wait_ms=total_api_wait_ms,
        tool_usage=tool_usage or {},
    )


def _make_session(
    *,
    session_id: str = "abc123def456",
    cost: float = 0.05,
    api_calls: int = 10,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_creation_tokens: int = 50,
    cache_read_tokens: int = 200,
    perf: SessionPerf | None = None,
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
        perf=perf,
    )


def _make_metrics(by_session: list[SessionCost] | None = None) -> CostMetrics:
    sessions = by_session if by_session is not None else [_make_session()]
    return CostMetrics(
        total_api_calls=10,
        total_input_tokens=1000,
        total_output_tokens=500,
        total_cache_creation_tokens=50,
        total_cache_read_tokens=200,
        total_cost=0.05,
        total_cache_savings=0.01,
        efficiency_ratio=0.5,
        by_session=sessions,
    )


# ---------------------------------------------------------------------------
# _format_model_mix
# ---------------------------------------------------------------------------


class TestFormatModelMix(unittest.TestCase):
    def test_empty_returns_empty_string(self):
        self.assertEqual(_format_model_mix({}), "")

    def test_opus_counted(self):
        result = _format_model_mix({"claude-opus-4": 5})
        self.assertIn("opus:5", result)

    def test_sonnet_counted(self):
        result = _format_model_mix({"claude-sonnet-4-6": 10})
        self.assertIn("sonnet:10", result)

    def test_haiku_counted(self):
        result = _format_model_mix({"claude-haiku-3-5": 3})
        self.assertIn("haiku:3", result)

    def test_unknown_model_shown_as_key(self):
        result = _format_model_mix({"unknown-model": 2})
        self.assertIn("unknown-model:2", result)


# ---------------------------------------------------------------------------
# _has_errors
# ---------------------------------------------------------------------------


class TestHasErrors(unittest.TestCase):
    def test_no_perf_returns_false(self):
        s = _make_session()
        self.assertFalse(_has_errors(s))

    def test_with_errors_returns_true(self):
        s = _make_session(perf=_make_perf(error_count=3))
        self.assertTrue(_has_errors(s))

    def test_with_tool_failures_returns_true(self):
        s = _make_session(perf=_make_perf(tool_failures=2))
        self.assertTrue(_has_errors(s))

    def test_no_errors_returns_false(self):
        s = _make_session(perf=_make_perf(error_count=0, tool_failures=0))
        self.assertFalse(_has_errors(s))


# ---------------------------------------------------------------------------
# _filter_sessions
# ---------------------------------------------------------------------------


class TestFilterSessions(unittest.TestCase):
    def test_no_filters(self):
        sessions = [_make_session(session_id="a"), _make_session(session_id="b")]
        result = _filter_sessions(sessions, errors_only=False, limit=0)
        self.assertEqual(len(result), 2)

    def test_errors_only(self):
        sessions = [
            _make_session(session_id="a", perf=_make_perf(error_count=2)),
            _make_session(session_id="b"),
        ]
        result = _filter_sessions(sessions, errors_only=True, limit=0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].session_id, "a")

    def test_limit(self):
        sessions = [_make_session(session_id=str(i)) for i in range(10)]
        result = _filter_sessions(sessions, errors_only=False, limit=3)
        self.assertEqual(len(result), 3)

    def test_session_id_filter(self):
        sessions = [
            _make_session(session_id="target"),
            _make_session(session_id="other"),
        ]
        result = _filter_sessions(sessions, errors_only=False, limit=0, session_id="target")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].session_id, "target")


# ---------------------------------------------------------------------------
# _format_timeline_entry
# ---------------------------------------------------------------------------


class TestFormatTimelineEntry(unittest.TestCase):
    def test_entry_with_timestamp(self):
        entry = {
            "timestamp": datetime(2026, 4, 16, 10, 30, 0, tzinfo=timezone.utc),
            "event_type": "claude_code.api_request",
            "detail": "sonnet",
        }
        result = _format_timeline_entry(entry)
        self.assertIn("10:30:00", result)
        self.assertIn("api_request", result)

    def test_entry_without_detail(self):
        entry = {
            "timestamp": datetime(2026, 4, 16, 10, 30, 0, tzinfo=timezone.utc),
            "event_type": "user_prompt",
            "detail": "",
        }
        result = _format_timeline_entry(entry)
        self.assertNotIn("()", result)

    def test_entry_with_none_timestamp(self):
        entry = {
            "timestamp": None,
            "event_type": "api_request",
            "detail": "x",
        }
        result = _format_timeline_entry(entry)
        self.assertIn("??:??:??", result)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestSessionsMain(unittest.TestCase):
    def _run(self, argv: list[str], by_session: list | None = None) -> tuple[int, str]:
        metrics = _make_metrics(by_session=by_session)
        with patch("telemetry.otel.cli.sessions.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.sessions.get_all_costs", return_value=metrics):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    result = main(argv)
        return result, buf.getvalue()

    def test_table_returns_0(self):
        result, _ = self._run([])
        self.assertEqual(result, 0)

    def test_no_sessions_shows_no_sessions(self):
        result, output = self._run([], by_session=[])
        self.assertEqual(result, 0)
        self.assertIn("No sessions", output)

    def test_json_format(self):
        result, output = self._run(["--format", "json"])
        self.assertEqual(result, 0)
        data = json.loads(output)
        self.assertIn("sessions", data)

    def test_invalid_since_returns_2(self):
        with patch("telemetry.otel.cli.sessions.OTLPDataDir.from_env"):
            result = main(["--since", "bad!!!"])
        self.assertEqual(result, 2)

    def test_timeline_without_session_id_returns_2(self):
        result = main(["--timeline"])
        self.assertEqual(result, 2)

    def test_errors_only_filter(self):
        perf = _make_perf(error_count=1)
        s_with = _make_session(session_id="err", perf=perf)
        s_without = _make_session(session_id="ok")
        result, output = self._run(["--errors-only"], by_session=[s_with, s_without])
        self.assertEqual(result, 0)
        self.assertIn("err", output)

    def test_limit_flag(self):
        sessions = [_make_session(session_id=str(i)) for i in range(5)]
        result, _ = self._run(["--limit", "2"], by_session=sessions)
        self.assertEqual(result, 0)

    def test_sort_flag_cost(self):
        sessions = [
            _make_session(session_id="cheap", cost=0.01),
            _make_session(session_id="expensive", cost=0.99),
        ]
        result, _ = self._run(["--sort", "cost"], by_session=sessions)
        self.assertEqual(result, 0)

    def test_json_with_session_id_filter(self):
        sessions = [_make_session(session_id="target"), _make_session(session_id="other")]
        result, output = self._run(
            ["--format", "json", "--session-id", "target"], by_session=sessions
        )
        self.assertEqual(result, 0)
        data = json.loads(output)
        ids = [s["session_id"] for s in data["sessions"]]
        self.assertNotIn("other", ids)

    def test_health_flag(self):
        result, _ = self._run(["--health"])
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# Private print helpers
# ---------------------------------------------------------------------------


class TestPrintSessionHeader(unittest.TestCase):
    def test_prints_session_id(self):
        s = _make_session(session_id="myses123")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_session_header(s, "myses123", 50.0)
        self.assertIn("myses123", buf.getvalue())

    def test_prints_with_terminal_type(self):
        s = _make_session(perf=_make_perf())
        # terminal_type is "" by default so header won't show []
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_session_header(s, "s", 10.0)
        self.assertIsNotNone(buf.getvalue())

    def test_prints_with_terminal_type_shown(self):
        perf = _make_perf(terminal_type="tmux")
        s = _make_session(perf=perf)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_session_header(s, "s", 10.0)
        self.assertIn("tmux", buf.getvalue())


class TestPrintPerfSummary(unittest.TestCase):
    def test_shows_avg_latency(self):
        perf = _make_perf(avg_api_latency_ms=500.0)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_perf_summary(perf, api_calls=10)
        self.assertIn("avg", buf.getvalue())

    def test_shows_errors(self):
        perf = _make_perf(error_count=3, error_rate=0.3)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_perf_summary(perf, api_calls=10)
        self.assertIn("errors", buf.getvalue())

    def test_shows_tool_failures(self):
        perf = _make_perf(tool_failures=2)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_perf_summary(perf, api_calls=10)
        self.assertIn("tool failures", buf.getvalue())

    def test_shows_prompts(self):
        perf = _make_perf(prompt_count=5, autonomy_ratio=2.0)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_perf_summary(perf, api_calls=10)
        self.assertIn("prompts", buf.getvalue())

    def test_no_output_when_no_data(self):
        perf = _make_perf()
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_perf_summary(perf, api_calls=10)
        self.assertEqual(buf.getvalue(), "")


class TestPrintPerfDetails(unittest.TestCase):
    def test_shows_p95_latency(self):
        perf = _make_perf(p95_api_latency_ms=1500.0, total_api_wait_ms=10000.0)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_perf_details(perf)
        self.assertIn("latency", buf.getvalue())

    def test_shows_error_codes(self):
        perf = _make_perf(error_status_codes={"429": 3, "500": 1})
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_perf_details(perf)
        self.assertIn("429", buf.getvalue())

    def test_shows_top_tools(self):
        perf = _make_perf(tool_usage={"Bash": 50, "Read": 30})
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_perf_details(perf)
        self.assertIn("tools", buf.getvalue())


class TestPrintErrorCodesStandalone(unittest.TestCase):
    def test_not_shown_when_show_error_codes_false(self):
        perf = _make_perf(error_status_codes={"429": 3})
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_error_codes_standalone(perf, show_error_codes=False, show_perf=False)
        self.assertEqual(buf.getvalue(), "")

    def test_not_shown_when_show_perf_true(self):
        perf = _make_perf(error_status_codes={"429": 3})
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_error_codes_standalone(perf, show_error_codes=True, show_perf=True)
        self.assertEqual(buf.getvalue(), "")

    def test_shown_when_show_error_codes_and_not_perf(self):
        perf = _make_perf(error_status_codes={"429": 3})
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_error_codes_standalone(perf, show_error_codes=True, show_perf=False)
        self.assertIn("429", buf.getvalue())

    def test_no_output_when_no_error_codes(self):
        perf = _make_perf()
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_error_codes_standalone(perf, show_error_codes=True, show_perf=False)
        self.assertEqual(buf.getvalue(), "")


# ---------------------------------------------------------------------------
# Timeline helpers
# ---------------------------------------------------------------------------


class TestExtractEventDetail(unittest.TestCase):
    def test_api_request_event(self):
        event = MagicMock()
        event.get_attr.return_value = "claude-sonnet-4-6"
        event.get_attr_as_float.return_value = 1500.0
        event.attributes = []
        result = _extract_event_detail(event, "claude_code.api_request")
        self.assertIn("sonnet", result)

    def test_api_error_event(self):
        event = MagicMock()
        event.get_attr.return_value = "429"
        result = _extract_event_detail(event, "claude_code.api_error")
        self.assertIn("429", result)

    def test_tool_result_event(self):
        event = MagicMock()
        event.get_attr.side_effect = lambda k: "Bash" if "tool_name" in k else "true"
        event.get_attr_as_float.return_value = 100.0
        result = _extract_event_detail(event, "claude_code.tool_result")
        self.assertIn("Bash", result)

    def test_user_prompt_event_with_length(self):
        event = MagicMock()
        event.get_attr.return_value = "500"
        result = _extract_event_detail(event, "claude_code.user_prompt")
        self.assertIn("chars", result)

    def test_unknown_event_returns_empty(self):
        event = MagicMock()
        result = _extract_event_detail(event, "other_event_type")
        self.assertEqual(result, "")


class TestFormatApiRequestDetail(unittest.TestCase):
    def test_opus_model(self):
        result = _format_api_request_detail("claude-opus-4", 2000.0, 1500)
        self.assertIn("opus", result)

    def test_sonnet_model(self):
        result = _format_api_request_detail("claude-sonnet-4-6", 1000.0, 500)
        self.assertIn("sonnet", result)

    def test_haiku_model(self):
        result = _format_api_request_detail("claude-haiku-3-5", 500.0, 200)
        self.assertIn("haiku", result)

    def test_unknown_model(self):
        result = _format_api_request_detail("unknown-model", None, 0)
        self.assertIn("unknown-model", result)

    def test_large_token_count(self):
        result = _format_api_request_detail("claude-sonnet-4-6", 1000.0, 5000)
        self.assertIn("K tokens", result)

    def test_small_token_count(self):
        result = _format_api_request_detail("claude-sonnet-4-6", None, 500)
        self.assertIn("500 tokens", result)


class TestExtractToolResultDetail(unittest.TestCase):
    def test_successful_tool(self):
        event = MagicMock()
        event.get_attr.side_effect = lambda k: {
            "tool_name": "Bash",
            "success": "true",
        }.get(k)
        event.get_attr_as_float.return_value = 100.0
        result = _extract_tool_result_detail(event)
        self.assertIn("Bash", result)
        self.assertIn("ok", result)

    def test_failed_tool(self):
        event = MagicMock()
        event.get_attr.side_effect = lambda k: {
            "tool_name": "Edit",
            "success": "false",
        }.get(k)
        event.get_attr_as_float.return_value = None
        result = _extract_tool_result_detail(event)
        self.assertIn("fail", result)


# ---------------------------------------------------------------------------
# main with perf and error_codes flags
# ---------------------------------------------------------------------------


class TestSessionsMainPerfFlags(unittest.TestCase):
    def _run(self, argv: list[str], by_session: list | None = None) -> tuple[int, str]:
        metrics = _make_metrics(by_session=by_session)
        with patch("telemetry.otel.cli.sessions.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.sessions.get_all_costs", return_value=metrics):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    result = main(argv)
        return result, buf.getvalue()

    def test_perf_flag(self):
        perf = _make_perf(avg_api_latency_ms=500.0, p95_api_latency_ms=1000.0, total_api_wait_ms=5000.0)
        s = _make_session(perf=perf)
        result, _ = self._run(["--perf"], by_session=[s])
        self.assertEqual(result, 0)

    def test_error_codes_flag(self):
        perf = _make_perf(error_status_codes={"429": 5})
        s = _make_session(perf=perf)
        result, _ = self._run(["--error-codes"], by_session=[s])
        self.assertEqual(result, 0)

    def test_json_with_health_flag(self):
        s = _make_session(perf=_make_perf())
        result, output = self._run(["--format", "json", "--health"], by_session=[s])
        self.assertEqual(result, 0)
        data = json.loads(output)
        self.assertIn("health", data["sessions"][0])

    def test_json_with_error_codes_flag(self):
        perf = _make_perf(error_status_codes={"429": 2})
        s = _make_session(perf=perf)
        result, output = self._run(
            ["--format", "json", "--error-codes"], by_session=[s]
        )
        self.assertEqual(result, 0)
        data = json.loads(output)
        self.assertIn("error_codes", data["sessions"][0])

    def test_json_with_perf_data(self):
        perf = _make_perf(error_count=1, tool_failures=1)
        s = _make_session(perf=perf)
        result, output = self._run(["--format", "json"], by_session=[s])
        self.assertEqual(result, 0)
        data = json.loads(output)
        self.assertIn("perf", data["sessions"][0])


if __name__ == "__main__":
    unittest.main()
