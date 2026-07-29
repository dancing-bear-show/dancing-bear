"""Tests for telemetry/otel/analytics/perf.py."""

import unittest
from collections import defaultdict
from datetime import datetime, timezone

from telemetry.otel.models import OTLPAttribute, OTLPEvent, OTLPEventsRecord, OTLPResource, OTLPValue
from telemetry.otel.cost_models import SessionPerf
from telemetry.otel.analytics.perf import (
    _build_session_perf_objects,
    _calc_p95,
    _dispatch_event,
    _extract_all_events,
    _new_perf_accumulator,
    _parse_token_attribute,
    _process_api_error,
    _process_api_request,
    _process_tool_result,
    _process_user_prompt,
    get_session_id,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _attr(key: str, string_value: str | None = None, int_value: int | None = None,
          double_value: float | None = None, bool_value: bool | None = None) -> OTLPAttribute:
    """Build a real OTLPAttribute with a typed value."""
    return OTLPAttribute(key=key, value=OTLPValue(
        string_value=string_value,
        int_value=int_value,
        double_value=double_value,
        bool_value=bool_value,
    ))


# Unix nano for a known UTC moment: 2026-01-01 00:00:00 UTC
_TS_2026_NANO = 1_767_225_600_000_000_000
_TS_2026 = datetime(2026, 1, 1, tzinfo=timezone.utc)

# A slightly earlier timestamp for cutoff tests
_TS_2025_NANO = 1_735_689_600_000_000_000  # 2025-01-01 00:00:00 UTC
_TS_2025 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _make_event(body: str, attrs: list[OTLPAttribute] | None = None,
                time_nano: int = _TS_2026_NANO) -> OTLPEvent:
    """Build a real OTLPEvent with the given body and attributes."""
    return OTLPEvent(
        time_unix_nano=time_nano,
        observed_time_unix_nano=time_nano,
        body=body,
        attributes=attrs or [],
    )


def _make_resource() -> OTLPResource:
    return OTLPResource(service_name="test", service_version="0.0.1")


def _make_record(events: list[OTLPEvent]) -> OTLPEventsRecord:
    """Wrap events in a real OTLPEventsRecord."""
    return OTLPEventsRecord(
        resource=_make_resource(),
        scope_name="test",
        log_records=events,
    )


def _fresh_acc() -> dict:
    return _new_perf_accumulator()


# ---------------------------------------------------------------------------
# _parse_token_attribute
# ---------------------------------------------------------------------------

class TestParseTokenAttribute(unittest.TestCase):

    def _event_dict(self) -> dict:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }

    def test_input_tokens_parsed(self):
        d = self._event_dict()
        _parse_token_attribute(_attr("input_tokens", string_value="42"), d)
        self.assertEqual(d["input_tokens"], 42)

    def test_output_tokens_parsed(self):
        d = self._event_dict()
        _parse_token_attribute(_attr("output_tokens", string_value="10"), d)
        self.assertEqual(d["output_tokens"], 10)

    def test_cache_creation_tokens_parsed(self):
        d = self._event_dict()
        _parse_token_attribute(_attr("cache_creation_tokens", string_value="5"), d)
        self.assertEqual(d["cache_creation_tokens"], 5)

    def test_cache_read_tokens_parsed(self):
        d = self._event_dict()
        _parse_token_attribute(_attr("cache_read_tokens", string_value="99"), d)
        self.assertEqual(d["cache_read_tokens"], 99)

    def test_float_string_truncated_to_int(self):
        """Values like "100.0" should coerce via int(float(...))."""
        d = self._event_dict()
        _parse_token_attribute(_attr("input_tokens", string_value="100.9"), d)
        self.assertEqual(d["input_tokens"], 100)

    def test_unrecognized_key_is_noop(self):
        d = self._event_dict()
        _parse_token_attribute(_attr("total_tokens", string_value="500"), d)
        # None of the recognized keys should have changed
        self.assertEqual(d["input_tokens"], 0)
        self.assertEqual(d["output_tokens"], 0)

    def test_invalid_value_does_not_raise(self):
        d = self._event_dict()
        _parse_token_attribute(_attr("input_tokens", string_value="not_a_number"), d)
        # Should silently leave value unchanged
        self.assertEqual(d["input_tokens"], 0)

    def test_none_value_does_not_raise(self):
        """OTLPValue with no data yields empty string from as_str(); int(float('')) raises."""
        d = self._event_dict()
        _parse_token_attribute(_attr("input_tokens"), d)
        self.assertEqual(d["input_tokens"], 0)


# ---------------------------------------------------------------------------
# _process_api_request
# ---------------------------------------------------------------------------

class TestProcessApiRequest(unittest.TestCase):

    def _make_api_event(self, model: str = "claude-sonnet-4-6",
                        duration_ms: float | None = 250.0,
                        terminal: str | None = None,
                        input_tokens: int = 10,
                        output_tokens: int = 5) -> OTLPEvent:
        attrs = [
            _attr("model", string_value=model),
            _attr("input_tokens", string_value=str(input_tokens)),
            _attr("output_tokens", string_value=str(output_tokens)),
        ]
        if duration_ms is not None:
            attrs.append(_attr("duration_ms", double_value=duration_ms))
        if terminal is not None:
            attrs.append(_attr("terminal.type", string_value=terminal))
        return _make_event("claude_code.api_request", attrs)

    def test_appends_event_dict(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        event = self._make_api_event()
        _process_api_request(event, "sess1", acc, reqs)
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]["session_id"], "sess1")
        self.assertEqual(reqs[0]["model"], "claude-sonnet-4-6")

    def test_token_fields_populated(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        event = self._make_api_event(input_tokens=100, output_tokens=50)
        _process_api_request(event, "s1", acc, reqs)
        self.assertEqual(reqs[0]["input_tokens"], 100)
        self.assertEqual(reqs[0]["output_tokens"], 50)

    def test_api_calls_incremented(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        _process_api_request(self._make_api_event(), "s1", acc, reqs)
        self.assertEqual(acc["api_calls"], 1)

    def test_model_mix_updated(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        _process_api_request(self._make_api_event(model="claude-opus-4-5"), "s1", acc, reqs)
        self.assertEqual(acc["model_mix"]["claude-opus-4-5"], 1)

    def test_model_fallback_to_unknown_when_absent(self):
        attrs = [_attr("input_tokens", string_value="5")]
        event = _make_event("claude_code.api_request", attrs)
        acc = _fresh_acc()
        reqs: list[dict] = []
        _process_api_request(event, "s1", acc, reqs)
        self.assertEqual(reqs[0]["model"], "unknown")

    def test_terminal_type_set_when_present(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        _process_api_request(self._make_api_event(terminal="iTerm.app"), "s1", acc, reqs)
        self.assertEqual(acc["terminal_type"], "iTerm.app")

    def test_terminal_type_not_set_when_absent(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        _process_api_request(self._make_api_event(terminal=None), "s1", acc, reqs)
        self.assertEqual(acc["terminal_type"], "")

    def test_terminal_type_not_set_when_empty_string(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        _process_api_request(self._make_api_event(terminal=""), "s1", acc, reqs)
        self.assertEqual(acc["terminal_type"], "")

    def test_positive_duration_appended_to_latencies(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        _process_api_request(self._make_api_event(duration_ms=500.0), "s1", acc, reqs)
        self.assertEqual(acc["api_latencies"], [500.0])

    def test_zero_duration_not_appended(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        _process_api_request(self._make_api_event(duration_ms=0.0), "s1", acc, reqs)
        self.assertEqual(acc["api_latencies"], [])

    def test_negative_duration_not_appended(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        _process_api_request(self._make_api_event(duration_ms=-1.0), "s1", acc, reqs)
        self.assertEqual(acc["api_latencies"], [])

    def test_missing_duration_not_appended(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        _process_api_request(self._make_api_event(duration_ms=None), "s1", acc, reqs)
        self.assertEqual(acc["api_latencies"], [])

    def test_duration_ms_in_event_dict(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        _process_api_request(self._make_api_event(duration_ms=123.0), "s1", acc, reqs)
        self.assertEqual(reqs[0]["duration_ms"], 123.0)

    def test_timestamp_in_event_dict(self):
        acc = _fresh_acc()
        reqs: list[dict] = []
        event = self._make_api_event()
        _process_api_request(event, "s1", acc, reqs)
        self.assertIsNotNone(reqs[0]["timestamp"])


# ---------------------------------------------------------------------------
# _process_api_error
# ---------------------------------------------------------------------------

class TestProcessApiError(unittest.TestCase):

    def _make_error_event(self, status_code: str | None = "429") -> OTLPEvent:
        attrs = []
        if status_code is not None:
            attrs.append(_attr("status_code", string_value=status_code))
        return _make_event("claude_code.api_error", attrs)

    def test_error_count_incremented(self):
        acc = _fresh_acc()
        _process_api_error(self._make_error_event(), acc)
        self.assertEqual(acc["error_count"], 1)

    def test_error_count_accumulates(self):
        acc = _fresh_acc()
        _process_api_error(self._make_error_event("500"), acc)
        _process_api_error(self._make_error_event("500"), acc)
        self.assertEqual(acc["error_count"], 2)

    def test_status_code_keyed_in_dict(self):
        acc = _fresh_acc()
        _process_api_error(self._make_error_event("429"), acc)
        self.assertEqual(acc["error_status_codes"]["429"], 1)

    def test_multiple_status_codes_tracked_separately(self):
        acc = _fresh_acc()
        _process_api_error(self._make_error_event("429"), acc)
        _process_api_error(self._make_error_event("500"), acc)
        _process_api_error(self._make_error_event("429"), acc)
        self.assertEqual(acc["error_status_codes"]["429"], 2)
        self.assertEqual(acc["error_status_codes"]["500"], 1)

    def test_missing_status_code_falls_back_to_unknown(self):
        acc = _fresh_acc()
        _process_api_error(self._make_error_event(status_code=None), acc)
        self.assertEqual(acc["error_status_codes"]["unknown"], 1)


# ---------------------------------------------------------------------------
# _process_tool_result
# ---------------------------------------------------------------------------

class TestProcessToolResult(unittest.TestCase):

    def _make_tool_event(self, tool_name: str | None = "Bash",
                         success: str | bool | None = "true") -> OTLPEvent:
        attrs = []
        if tool_name is not None:
            attrs.append(_attr("tool_name", string_value=tool_name))
        if success is not None:
            if isinstance(success, bool):
                attrs.append(_attr("success", bool_value=success))
            else:
                attrs.append(_attr("success", string_value=success))
        return _make_event("claude_code.tool_result", attrs)

    def test_tool_calls_incremented(self):
        acc = _fresh_acc()
        _process_tool_result(self._make_tool_event(), acc)
        self.assertEqual(acc["tool_calls"], 1)

    def test_tool_usage_keyed_by_name(self):
        acc = _fresh_acc()
        _process_tool_result(self._make_tool_event(tool_name="Read"), acc)
        self.assertEqual(acc["tool_usage"]["Read"], 1)

    def test_missing_tool_name_falls_back_to_unknown(self):
        acc = _fresh_acc()
        _process_tool_result(self._make_tool_event(tool_name=None), acc)
        self.assertEqual(acc["tool_usage"]["unknown"], 1)

    def test_success_true_string_no_failure(self):
        acc = _fresh_acc()
        _process_tool_result(self._make_tool_event(success="true"), acc)
        self.assertEqual(acc["tool_failures"], 0)

    def test_success_true_bool_no_failure(self):
        acc = _fresh_acc()
        _process_tool_result(self._make_tool_event(success=True), acc)
        self.assertEqual(acc["tool_failures"], 0)

    def test_success_false_string_lowercase_counts_as_failure(self):
        acc = _fresh_acc()
        _process_tool_result(self._make_tool_event(success="false"), acc)
        self.assertEqual(acc["tool_failures"], 1)

    def test_success_false_string_titlecase_counts_as_failure(self):
        acc = _fresh_acc()
        _process_tool_result(self._make_tool_event(success="False"), acc)
        self.assertEqual(acc["tool_failures"], 1)

    def test_success_false_bool_counts_as_failure(self):
        acc = _fresh_acc()
        _process_tool_result(self._make_tool_event(success=False), acc)
        self.assertEqual(acc["tool_failures"], 1)

    def test_multiple_tools_tracked(self):
        acc = _fresh_acc()
        _process_tool_result(self._make_tool_event(tool_name="Read"), acc)
        _process_tool_result(self._make_tool_event(tool_name="Read"), acc)
        _process_tool_result(self._make_tool_event(tool_name="Bash"), acc)
        self.assertEqual(acc["tool_usage"]["Read"], 2)
        self.assertEqual(acc["tool_usage"]["Bash"], 1)
        self.assertEqual(acc["tool_calls"], 3)


# ---------------------------------------------------------------------------
# _new_perf_accumulator
# ---------------------------------------------------------------------------

class TestNewPerfAccumulator(unittest.TestCase):

    def test_returns_dict_with_all_expected_keys(self):
        acc = _new_perf_accumulator()
        expected_keys = {
            "error_count", "error_status_codes", "tool_calls",
            "tool_failures", "api_latencies", "prompt_count",
            "api_calls", "model_mix", "terminal_type", "tool_usage",
        }
        self.assertEqual(set(acc.keys()), expected_keys)

    def test_numeric_fields_start_at_zero(self):
        acc = _new_perf_accumulator()
        self.assertEqual(acc["error_count"], 0)
        self.assertEqual(acc["tool_calls"], 0)
        self.assertEqual(acc["tool_failures"], 0)
        self.assertEqual(acc["prompt_count"], 0)
        self.assertEqual(acc["api_calls"], 0)

    def test_list_fields_start_empty(self):
        acc = _new_perf_accumulator()
        self.assertEqual(acc["api_latencies"], [])

    def test_terminal_type_starts_empty_string(self):
        acc = _new_perf_accumulator()
        self.assertEqual(acc["terminal_type"], "")

    def test_dict_fields_are_defaultdict(self):
        acc = _new_perf_accumulator()
        # defaultdict allows zero-value access without KeyError
        _ = acc["model_mix"]["new_model"]
        self.assertEqual(acc["model_mix"]["new_model"], 0)

    def test_fresh_call_returns_independent_dicts(self):
        acc1 = _new_perf_accumulator()
        acc2 = _new_perf_accumulator()
        acc1["api_calls"] += 1
        self.assertEqual(acc2["api_calls"], 0)


# ---------------------------------------------------------------------------
# get_session_id
# ---------------------------------------------------------------------------

class TestGetSessionId(unittest.TestCase):

    def test_session_dot_id_preferred(self):
        event = _make_event("body", [
            _attr("session.id", string_value="dotid-123"),
            _attr("session_id", string_value="underscoreid-456"),
        ])
        self.assertEqual(get_session_id(event), "dotid-123")

    def test_falls_back_to_session_id_when_dot_absent(self):
        event = _make_event("body", [
            _attr("session_id", string_value="underscoreid-456"),
        ])
        self.assertEqual(get_session_id(event), "underscoreid-456")

    def test_falls_back_to_unknown_when_both_absent(self):
        event = _make_event("body", [])
        self.assertEqual(get_session_id(event), "unknown")

    def test_falls_back_to_unknown_when_both_empty(self):
        event = _make_event("body", [
            _attr("session.id", string_value=""),
            _attr("session_id", string_value=""),
        ])
        self.assertEqual(get_session_id(event), "unknown")


# ---------------------------------------------------------------------------
# _process_user_prompt
# ---------------------------------------------------------------------------

class TestProcessUserPrompt(unittest.TestCase):

    def test_prompt_count_incremented(self):
        acc = _fresh_acc()
        _process_user_prompt(acc)
        self.assertEqual(acc["prompt_count"], 1)

    def test_prompt_count_accumulates(self):
        acc = _fresh_acc()
        _process_user_prompt(acc)
        _process_user_prompt(acc)
        _process_user_prompt(acc)
        self.assertEqual(acc["prompt_count"], 3)


# ---------------------------------------------------------------------------
# _dispatch_event / _EVENT_DISPATCH
# ---------------------------------------------------------------------------

class TestDispatchEvent(unittest.TestCase):

    def test_dispatches_api_request(self):
        event = _make_event("claude_code.api_request", [
            _attr("model", string_value="claude-sonnet-4-6"),
        ])
        acc = _fresh_acc()
        reqs: list[dict] = []
        _dispatch_event(event, "s1", acc, reqs)
        self.assertEqual(acc["api_calls"], 1)
        self.assertEqual(len(reqs), 1)

    def test_dispatches_api_error(self):
        event = _make_event("claude_code.api_error", [
            _attr("status_code", string_value="500"),
        ])
        acc = _fresh_acc()
        reqs: list[dict] = []
        _dispatch_event(event, "s1", acc, reqs)
        self.assertEqual(acc["error_count"], 1)

    def test_dispatches_tool_result(self):
        event = _make_event("claude_code.tool_result", [
            _attr("tool_name", string_value="Bash"),
            _attr("success", string_value="true"),
        ])
        acc = _fresh_acc()
        reqs: list[dict] = []
        _dispatch_event(event, "s1", acc, reqs)
        self.assertEqual(acc["tool_calls"], 1)

    def test_dispatches_user_prompt(self):
        event = _make_event("claude_code.user_prompt", [])
        acc = _fresh_acc()
        reqs: list[dict] = []
        _dispatch_event(event, "s1", acc, reqs)
        self.assertEqual(acc["prompt_count"], 1)

    def test_unknown_body_is_silent_noop(self):
        event = _make_event("claude_code.some_other_event", [])
        acc = _fresh_acc()
        reqs: list[dict] = []
        _dispatch_event(event, "s1", acc, reqs)
        # No accumulator fields should be mutated
        self.assertEqual(acc["api_calls"], 0)
        self.assertEqual(acc["error_count"], 0)
        self.assertEqual(acc["tool_calls"], 0)
        self.assertEqual(acc["prompt_count"], 0)
        self.assertEqual(reqs, [])

    def test_dispatch_uses_substring_matching(self):
        """Key in body check — "api_request" in "some.api_request.event" is True."""
        event = _make_event("prefix.api_request.suffix", [
            _attr("model", string_value="claude-sonnet-4-6"),
        ])
        acc = _fresh_acc()
        reqs: list[dict] = []
        _dispatch_event(event, "s1", acc, reqs)
        # Substring match means api_request handler fires
        self.assertEqual(acc["api_calls"], 1)


# ---------------------------------------------------------------------------
# _extract_all_events
# ---------------------------------------------------------------------------

class TestExtractAllEvents(unittest.TestCase):

    def _api_request_event(self, session_id: str = "s1",
                           time_nano: int = _TS_2026_NANO) -> OTLPEvent:
        return _make_event("claude_code.api_request", [
            _attr("session.id", string_value=session_id),
            _attr("model", string_value="claude-sonnet-4-6"),
            _attr("input_tokens", string_value="10"),
            _attr("duration_ms", double_value=100.0),
        ], time_nano=time_nano)

    def test_empty_input_returns_empty_structures(self):
        reqs, sessions = _extract_all_events([])
        self.assertEqual(reqs, [])
        self.assertEqual(sessions, {})

    def test_single_api_request_extracted(self):
        record = _make_record([self._api_request_event()])
        reqs, sessions = _extract_all_events([record])
        self.assertEqual(len(reqs), 1)
        self.assertIn("s1", sessions)
        self.assertEqual(sessions["s1"]["api_calls"], 1)

    def test_since_cutoff_excludes_older_events(self):
        old_event = self._api_request_event(time_nano=_TS_2025_NANO)
        new_event = self._api_request_event(time_nano=_TS_2026_NANO)
        record = _make_record([old_event, new_event])
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        reqs, _ = _extract_all_events([record], since=cutoff)
        self.assertEqual(len(reqs), 1)

    def test_since_cutoff_at_exact_timestamp_included(self):
        event = self._api_request_event(time_nano=_TS_2026_NANO)
        record = _make_record([event])
        reqs, _ = _extract_all_events([record], since=_TS_2026)
        self.assertEqual(len(reqs), 1)

    def test_multiple_sessions_accumulate_separately(self):
        e1 = self._api_request_event(session_id="sess-a")
        e2 = self._api_request_event(session_id="sess-b")
        e3 = self._api_request_event(session_id="sess-a")
        record = _make_record([e1, e2, e3])
        reqs, sessions = _extract_all_events([record])
        self.assertIn("sess-a", sessions)
        self.assertIn("sess-b", sessions)
        self.assertEqual(sessions["sess-a"]["api_calls"], 2)
        self.assertEqual(sessions["sess-b"]["api_calls"], 1)
        self.assertEqual(len(reqs), 3)

    def test_multiple_records_processed(self):
        r1 = _make_record([self._api_request_event(session_id="s1")])
        r2 = _make_record([self._api_request_event(session_id="s2")])
        reqs, sessions = _extract_all_events([r1, r2])
        self.assertEqual(len(reqs), 2)
        self.assertIn("s1", sessions)
        self.assertIn("s2", sessions)

    def test_no_since_processes_all_events(self):
        old_event = self._api_request_event(time_nano=_TS_2025_NANO)
        new_event = self._api_request_event(time_nano=_TS_2026_NANO)
        record = _make_record([old_event, new_event])
        reqs, _ = _extract_all_events([record], since=None)
        self.assertEqual(len(reqs), 2)

    def test_returns_perf_sessions_dict(self):
        record = _make_record([self._api_request_event()])
        _reqs, sessions = _extract_all_events([record])
        self.assertIsInstance(sessions, dict)
        self.assertIn("s1", sessions)
        self.assertIsInstance(sessions["s1"], dict)


# ---------------------------------------------------------------------------
# _calc_p95
# ---------------------------------------------------------------------------

class TestCalcP95(unittest.TestCase):

    def test_empty_list_returns_zero(self):
        self.assertEqual(_calc_p95([]), 0.0)

    def test_single_element_returns_that_element(self):
        self.assertEqual(_calc_p95([42.0]), 42.0)

    def test_small_list_under_20_returns_max(self):
        data = sorted([10.0, 50.0, 200.0, 500.0])
        self.assertEqual(_calc_p95(data), 500.0)

    def test_list_of_19_returns_last(self):
        data = sorted(float(i) for i in range(1, 20))  # 19 items
        self.assertEqual(_calc_p95(data), 19.0)

    def test_list_of_exactly_20_uses_index_formula(self):
        # 20 items, 0.95 index = int(20 * 0.95) = 19 → last element (clamped)
        data = sorted(float(i) for i in range(1, 21))  # [1.0 ... 20.0]
        idx = min(int(20 * 0.95), 19)  # = min(19, 19) = 19
        self.assertEqual(_calc_p95(data), data[idx])

    def test_list_of_100_uses_p95_index(self):
        data = sorted(float(i) for i in range(1, 101))  # [1.0 ... 100.0]
        idx = min(int(100 * 0.95), 99)  # = 95
        self.assertEqual(_calc_p95(data), data[idx])

    def test_large_list_clamped_to_last_index(self):
        """Verify the min(..., len-1) clamp guards edge cases."""
        data = [1.0] * 100
        # All same value, index is irrelevant — should return 1.0 not raise
        self.assertEqual(_calc_p95(data), 1.0)


# ---------------------------------------------------------------------------
# _build_session_perf_objects
# ---------------------------------------------------------------------------

class TestBuildSessionPerfObjects(unittest.TestCase):

    def _acc_with(self, **overrides) -> dict:
        acc = _new_perf_accumulator()
        for k, v in overrides.items():
            acc[k] = v
        return acc

    def test_returns_session_perf_instances(self):
        acc = self._acc_with(api_calls=2, error_count=0)
        result = _build_session_perf_objects({"s1": acc})
        self.assertIsInstance(result["s1"], SessionPerf)

    def test_error_rate_zero_guard_no_api_calls(self):
        acc = self._acc_with(api_calls=0, error_count=5)
        result = _build_session_perf_objects({"s1": acc})
        self.assertEqual(result["s1"].error_rate, 0.0)

    def test_error_rate_computed_when_api_calls_nonzero(self):
        acc = self._acc_with(api_calls=4, error_count=1)
        result = _build_session_perf_objects({"s1": acc})
        self.assertAlmostEqual(result["s1"].error_rate, 0.25)

    def test_tool_failure_rate_zero_guard_no_tool_calls(self):
        acc = self._acc_with(tool_calls=0, tool_failures=3)
        result = _build_session_perf_objects({"s1": acc})
        self.assertEqual(result["s1"].tool_failure_rate, 0.0)

    def test_tool_failure_rate_computed_when_tool_calls_nonzero(self):
        acc = self._acc_with(tool_calls=10, tool_failures=2)
        result = _build_session_perf_objects({"s1": acc})
        self.assertAlmostEqual(result["s1"].tool_failure_rate, 0.2)

    def test_avg_api_latency_computed(self):
        acc = self._acc_with(api_latencies=[100.0, 200.0, 300.0])
        result = _build_session_perf_objects({"s1": acc})
        self.assertAlmostEqual(result["s1"].avg_api_latency_ms, 200.0)

    def test_avg_api_latency_zero_when_no_latencies(self):
        acc = self._acc_with(api_latencies=[])
        result = _build_session_perf_objects({"s1": acc})
        self.assertEqual(result["s1"].avg_api_latency_ms, 0.0)

    def test_p95_api_latency_computed(self):
        # 5 items → small list, returns max
        acc = self._acc_with(api_latencies=[10.0, 20.0, 30.0, 40.0, 500.0])
        result = _build_session_perf_objects({"s1": acc})
        self.assertEqual(result["s1"].p95_api_latency_ms, 500.0)

    def test_total_api_wait_ms_is_sum_of_latencies(self):
        acc = self._acc_with(api_latencies=[100.0, 200.0, 700.0])
        result = _build_session_perf_objects({"s1": acc})
        self.assertAlmostEqual(result["s1"].total_api_wait_ms, 1000.0)

    def test_autonomy_ratio_zero_guard_no_prompt_count(self):
        acc = self._acc_with(api_calls=10, prompt_count=0)
        result = _build_session_perf_objects({"s1": acc})
        self.assertEqual(result["s1"].autonomy_ratio, 0.0)

    def test_autonomy_ratio_computed_when_prompt_count_nonzero(self):
        acc = self._acc_with(api_calls=10, prompt_count=2)
        result = _build_session_perf_objects({"s1": acc})
        self.assertAlmostEqual(result["s1"].autonomy_ratio, 5.0)

    def test_model_mix_converted_to_plain_dict(self):
        mm = defaultdict(int)
        mm["claude-sonnet-4-6"] = 3
        acc = self._acc_with(model_mix=mm)
        result = _build_session_perf_objects({"s1": acc})
        self.assertIsInstance(result["s1"].model_mix, dict)
        self.assertEqual(result["s1"].model_mix, {"claude-sonnet-4-6": 3})

    def test_error_status_codes_converted_to_plain_dict(self):
        esc = defaultdict(int)
        esc["429"] = 2
        acc = self._acc_with(error_status_codes=esc)
        result = _build_session_perf_objects({"s1": acc})
        self.assertIsInstance(result["s1"].error_status_codes, dict)
        self.assertEqual(result["s1"].error_status_codes, {"429": 2})

    def test_tool_usage_converted_to_plain_dict(self):
        tu = defaultdict(int)
        tu["Bash"] = 5
        acc = self._acc_with(tool_usage=tu)
        result = _build_session_perf_objects({"s1": acc})
        self.assertIsInstance(result["s1"].tool_usage, dict)
        self.assertEqual(result["s1"].tool_usage, {"Bash": 5})

    def test_multiple_sessions_each_get_independent_objects(self):
        acc_a = self._acc_with(error_count=0, tool_calls=2)
        acc_b = self._acc_with(error_count=3, tool_calls=7)
        result = _build_session_perf_objects({"sess-a": acc_a, "sess-b": acc_b})
        self.assertIn("sess-a", result)
        self.assertIn("sess-b", result)
        self.assertEqual(result["sess-a"].error_count, 0)
        self.assertEqual(result["sess-b"].error_count, 3)
        self.assertEqual(result["sess-a"].tool_calls, 2)
        self.assertEqual(result["sess-b"].tool_calls, 7)

    def test_empty_input_returns_empty_dict(self):
        result = _build_session_perf_objects({})
        self.assertEqual(result, {})

    def test_latencies_are_sorted_before_p95(self):
        # Unsorted input should still produce correct p95 via sorted()
        # 5 items → max is 400.0
        acc = self._acc_with(api_latencies=[400.0, 10.0, 50.0, 200.0, 5.0])
        result = _build_session_perf_objects({"s1": acc})
        # max of sorted [5, 10, 50, 200, 400] = 400
        self.assertEqual(result["s1"].p95_api_latency_ms, 400.0)

    def test_session_perf_has_correct_error_count(self):
        acc = self._acc_with(error_count=7)
        result = _build_session_perf_objects({"s1": acc})
        self.assertEqual(result["s1"].error_count, 7)

    def test_session_perf_has_correct_tool_calls(self):
        acc = self._acc_with(tool_calls=15)
        result = _build_session_perf_objects({"s1": acc})
        self.assertEqual(result["s1"].tool_calls, 15)

    def test_session_perf_terminal_type_preserved(self):
        acc = self._acc_with(terminal_type="tmux")
        result = _build_session_perf_objects({"s1": acc})
        self.assertEqual(result["s1"].terminal_type, "tmux")

    def test_session_perf_prompt_count_preserved(self):
        acc = self._acc_with(prompt_count=8)
        result = _build_session_perf_objects({"s1": acc})
        self.assertEqual(result["s1"].prompt_count, 8)


if __name__ == "__main__":
    unittest.main()
