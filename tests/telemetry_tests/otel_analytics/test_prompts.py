"""Tests for telemetry/otel/analytics/prompts.py."""

import unittest
from datetime import datetime, timezone
from unittest import mock

from telemetry.otel.analytics.prompts import (
    _PromptAccumulator,
    _accumulate_prompt_events,
    _build_prompt_metrics,
    _dispatch_prompt_event,
    _int_attr,
    _process_api_request,
    _process_tool_result,
    _process_user_prompt,
    _update_time_range,
)
from telemetry.otel.models import OTLPAttribute, OTLPEvent, OTLPEventsRecord, OTLPResource, OTLPValue


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _nano(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


def _attr(key: str, value: str | None = None) -> OTLPAttribute:
    return OTLPAttribute(key=key, value=OTLPValue(string_value=value))


def _attr_float(key: str, value: float) -> OTLPAttribute:
    return OTLPAttribute(key=key, value=OTLPValue(double_value=value))


def _attr_int(key: str, value: int) -> OTLPAttribute:
    return OTLPAttribute(key=key, value=OTLPValue(int_value=value))


_BASE_TS = _utc(2026, 7, 1, 12)
_BASE_NANO = _nano(_BASE_TS)


def _make_event(
    body: str,
    attrs: list[OTLPAttribute] | None = None,
    time_nano: int = _BASE_NANO,
) -> OTLPEvent:
    return OTLPEvent(
        time_unix_nano=time_nano,
        observed_time_unix_nano=time_nano,
        body=body,
        attributes=attrs or [],
    )


def _make_record(events: list[OTLPEvent]) -> OTLPEventsRecord:
    return OTLPEventsRecord(
        resource=OTLPResource(service_name="test", service_version="0.0.1"),
        scope_name="test",
        log_records=events,
    )


def _make_user_prompt_event(
    prompt_id: str = "p1",
    session_id: str = "sess-1",
    prompt_length: int | None = None,
    time_nano: int = _BASE_NANO,
) -> OTLPEvent:
    attrs = [
        _attr("prompt.id", prompt_id),
        _attr("session.id", session_id),
    ]
    if prompt_length is not None:
        attrs.append(_attr("prompt_length", str(prompt_length)))
    return _make_event("user_prompt", attrs, time_nano)


def _make_api_request_event(
    prompt_id: str = "p1",
    session_id: str = "sess-1",
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_creation: int = 0,
    time_nano: int = _BASE_NANO,
) -> OTLPEvent:
    attrs = [
        _attr("prompt.id", prompt_id),
        _attr("session.id", session_id),
        _attr("model", model),
        _attr("input_tokens", str(input_tokens)),
        _attr("output_tokens", str(output_tokens)),
        _attr("cache_creation_input_tokens", str(cache_creation)),
    ]
    return _make_event("api_request", attrs, time_nano)


def _make_tool_result_event(
    prompt_id: str = "p1",
    session_id: str = "sess-1",
    success: str = "true",
    time_nano: int = _BASE_NANO,
) -> OTLPEvent:
    attrs = [
        _attr("prompt.id", prompt_id),
        _attr("session.id", session_id),
        _attr("success", success),
    ]
    return _make_event("tool_result", attrs, time_nano)


# ---------------------------------------------------------------------------
# _update_time_range
# ---------------------------------------------------------------------------

class TestUpdateTimeRange(unittest.TestCase):

    def test_sets_first_ts_when_none(self):
        acc = _PromptAccumulator()
        ts = _utc(2026, 7, 1)
        _update_time_range(ts, acc)
        self.assertEqual(acc.first_ts, ts)

    def test_sets_last_ts_when_none(self):
        acc = _PromptAccumulator()
        ts = _utc(2026, 7, 1)
        _update_time_range(ts, acc)
        self.assertEqual(acc.last_ts, ts)

    def test_updates_first_ts_to_earlier(self):
        acc = _PromptAccumulator()
        t1 = _utc(2026, 7, 1, 10)
        t2 = _utc(2026, 7, 1, 9)
        _update_time_range(t1, acc)
        _update_time_range(t2, acc)
        self.assertEqual(acc.first_ts, t2)

    def test_does_not_update_first_ts_to_later(self):
        acc = _PromptAccumulator()
        t1 = _utc(2026, 7, 1, 9)
        t2 = _utc(2026, 7, 1, 10)
        _update_time_range(t1, acc)
        _update_time_range(t2, acc)
        self.assertEqual(acc.first_ts, t1)

    def test_updates_last_ts_to_later(self):
        acc = _PromptAccumulator()
        t1 = _utc(2026, 7, 1, 9)
        t2 = _utc(2026, 7, 1, 11)
        _update_time_range(t1, acc)
        _update_time_range(t2, acc)
        self.assertEqual(acc.last_ts, t2)

    def test_does_not_update_last_ts_to_earlier(self):
        acc = _PromptAccumulator()
        t1 = _utc(2026, 7, 1, 11)
        t2 = _utc(2026, 7, 1, 9)
        _update_time_range(t1, acc)
        _update_time_range(t2, acc)
        self.assertEqual(acc.last_ts, t1)


# ---------------------------------------------------------------------------
# _process_user_prompt
# ---------------------------------------------------------------------------

class TestProcessUserPrompt(unittest.TestCase):

    def test_updates_time_range(self):
        acc = _PromptAccumulator()
        event = _make_user_prompt_event(prompt_length=42)
        _process_user_prompt(event, acc)
        self.assertIsNotNone(acc.first_ts)
        self.assertIsNotNone(acc.last_ts)

    def test_prompt_length_extracted(self):
        acc = _PromptAccumulator()
        event = _make_user_prompt_event(prompt_length=123)
        _process_user_prompt(event, acc)
        self.assertEqual(acc.prompt_length, 123)

    def test_no_prompt_length_attr_leaves_zero(self):
        acc = _PromptAccumulator()
        event = _make_event("user_prompt", [_attr("session.id", "s1")])
        _process_user_prompt(event, acc)
        self.assertEqual(acc.prompt_length, 0)

    def test_invalid_prompt_length_leaves_zero(self):
        acc = _PromptAccumulator()
        event = _make_event("user_prompt", [_attr("prompt_length", "not-a-number")])
        _process_user_prompt(event, acc)
        self.assertEqual(acc.prompt_length, 0)


# ---------------------------------------------------------------------------
# _process_api_request (prompts version)
# ---------------------------------------------------------------------------

class TestProcessApiRequestPrompts(unittest.TestCase):

    def test_increments_api_calls(self):
        acc = _PromptAccumulator()
        event = _make_api_request_event(input_tokens=100, output_tokens=50)
        _process_api_request(event, acc)
        self.assertEqual(acc.api_calls, 1)

    def test_accumulates_input_tokens(self):
        acc = _PromptAccumulator()
        _process_api_request(_make_api_request_event(input_tokens=100), acc)
        _process_api_request(_make_api_request_event(input_tokens=200), acc)
        self.assertEqual(acc.input_tokens, 300)

    def test_accumulates_output_tokens(self):
        acc = _PromptAccumulator()
        _process_api_request(_make_api_request_event(output_tokens=50), acc)
        _process_api_request(_make_api_request_event(output_tokens=80), acc)
        self.assertEqual(acc.output_tokens, 130)

    def test_accumulates_cache_creation_tokens(self):
        acc = _PromptAccumulator()
        _process_api_request(_make_api_request_event(cache_creation=20), acc)
        self.assertEqual(acc.cache_creation_tokens, 20)

    def test_cost_accumulated(self):
        acc = _PromptAccumulator()
        # haiku: $1/M input, $5/M output
        event = _make_api_request_event(
            model="claude-haiku-4-5",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        _process_api_request(event, acc)
        self.assertAlmostEqual(acc.cost, 6.0, places=4)

    def test_updates_time_range(self):
        acc = _PromptAccumulator()
        _process_api_request(_make_api_request_event(), acc)
        self.assertIsNotNone(acc.first_ts)


# ---------------------------------------------------------------------------
# _process_tool_result (prompts version)
# ---------------------------------------------------------------------------

class TestProcessToolResultPrompts(unittest.TestCase):

    def test_increments_tool_calls(self):
        acc = _PromptAccumulator()
        event = _make_tool_result_event(success="true")
        _process_tool_result(event, acc)
        self.assertEqual(acc.tool_calls, 1)

    def test_success_false_increments_tool_failures(self):
        acc = _PromptAccumulator()
        _process_tool_result(_make_tool_result_event(success="false"), acc)
        self.assertEqual(acc.tool_failures, 1)

    def test_success_False_increments_tool_failures(self):
        acc = _PromptAccumulator()
        _process_tool_result(_make_tool_result_event(success="False"), acc)
        self.assertEqual(acc.tool_failures, 1)

    def test_success_true_no_failure(self):
        acc = _PromptAccumulator()
        _process_tool_result(_make_tool_result_event(success="true"), acc)
        self.assertEqual(acc.tool_failures, 0)

    def test_updates_time_range(self):
        acc = _PromptAccumulator()
        _process_tool_result(_make_tool_result_event(), acc)
        self.assertIsNotNone(acc.first_ts)


# ---------------------------------------------------------------------------
# _dispatch_prompt_event
# ---------------------------------------------------------------------------

class TestDispatchPromptEvent(unittest.TestCase):

    def test_dispatches_user_prompt(self):
        acc = _PromptAccumulator()
        event = _make_user_prompt_event(prompt_length=10)
        _dispatch_prompt_event(event, acc)
        self.assertIsNotNone(acc.first_ts)

    def test_dispatches_api_request(self):
        acc = _PromptAccumulator()
        event = _make_api_request_event(input_tokens=100)
        _dispatch_prompt_event(event, acc)
        self.assertEqual(acc.api_calls, 1)

    def test_dispatches_tool_result(self):
        acc = _PromptAccumulator()
        event = _make_tool_result_event(success="true")
        _dispatch_prompt_event(event, acc)
        self.assertEqual(acc.tool_calls, 1)

    def test_unknown_event_body_is_noop(self):
        acc = _PromptAccumulator()
        event = _make_event("some_unknown_event")
        _dispatch_prompt_event(event, acc)
        self.assertEqual(acc.api_calls, 0)
        self.assertEqual(acc.tool_calls, 0)
        self.assertIsNone(acc.first_ts)


# ---------------------------------------------------------------------------
# _int_attr
# ---------------------------------------------------------------------------

class TestIntAttr(unittest.TestCase):

    def test_float_attr_returns_int(self):
        event = _make_event("x", [_attr_float("input_tokens", 100.5)])
        result = _int_attr(event, "input_tokens")
        self.assertEqual(result, 100)

    def test_string_attr_parsed_as_int(self):
        event = _make_event("x", [_attr("input_tokens", "42")])
        result = _int_attr(event, "input_tokens")
        self.assertEqual(result, 42)

    def test_missing_attr_returns_zero(self):
        event = _make_event("x", [])
        result = _int_attr(event, "input_tokens")
        self.assertEqual(result, 0)

    def test_invalid_string_returns_zero(self):
        event = _make_event("x", [_attr("input_tokens", "not-a-number")])
        result = _int_attr(event, "input_tokens")
        self.assertEqual(result, 0)

    def test_int_attr_value_returned(self):
        event = _make_event("x", [_attr_int("output_tokens", 99)])
        result = _int_attr(event, "output_tokens")
        self.assertEqual(result, 99)

    def test_raw_string_fallback_when_get_attr_as_float_returns_none(self):
        """Cover lines 195-199: raw fallback path used when get_attr_as_float returns None."""
        event = mock.MagicMock()
        event.get_attr_as_float.return_value = None
        event.get_attr.return_value = "77"
        result = _int_attr(event, "input_tokens")
        self.assertEqual(result, 77)

    def test_raw_string_invalid_in_fallback_returns_zero(self):
        """Cover lines 198-199: except branch when raw string is non-numeric."""
        event = mock.MagicMock()
        event.get_attr_as_float.return_value = None
        event.get_attr.return_value = "bad-val"
        result = _int_attr(event, "input_tokens")
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# _build_prompt_metrics
# ---------------------------------------------------------------------------

class TestBuildPromptMetrics(unittest.TestCase):

    def test_empty_dict_returns_empty_list(self):
        result = _build_prompt_metrics({})
        self.assertEqual(result, [])

    def test_single_prompt_returned(self):
        acc = _PromptAccumulator()
        acc.session_id = "sess-1"
        acc.api_calls = 2
        acc.input_tokens = 100
        acc.output_tokens = 50
        acc.tool_calls = 3
        acc.cost = 0.005
        result = _build_prompt_metrics({"pid-1": acc})
        self.assertEqual(len(result), 1)
        pm = result[0]
        self.assertEqual(pm.prompt_id, "pid-1")
        self.assertEqual(pm.session_id, "sess-1")
        self.assertEqual(pm.api_calls, 2)
        self.assertEqual(pm.input_tokens, 100)
        self.assertEqual(pm.output_tokens, 50)
        self.assertEqual(pm.tool_calls, 3)

    def test_duration_ms_computed_from_timestamps(self):
        from datetime import timedelta
        acc = _PromptAccumulator()
        acc.first_ts = _utc(2026, 7, 1, 12, 0)
        acc.last_ts = _utc(2026, 7, 1, 12, 0) + timedelta(seconds=5)
        result = _build_prompt_metrics({"p1": acc})
        self.assertAlmostEqual(result[0].duration_ms, 5000.0, places=0)

    def test_duration_ms_zero_when_timestamps_missing(self):
        acc = _PromptAccumulator()
        result = _build_prompt_metrics({"p1": acc})
        self.assertAlmostEqual(result[0].duration_ms, 0.0, places=0)

    def test_sorted_by_timestamp_most_recent_first(self):
        acc1 = _PromptAccumulator()
        acc1.first_ts = _utc(2026, 7, 1)
        acc2 = _PromptAccumulator()
        acc2.first_ts = _utc(2026, 7, 3)
        acc3 = _PromptAccumulator()
        acc3.first_ts = _utc(2026, 7, 2)
        result = _build_prompt_metrics({"p1": acc1, "p2": acc2, "p3": acc3})
        timestamps = [r.timestamp for r in result]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_none_timestamp_sorts_last(self):
        acc_with_ts = _PromptAccumulator()
        acc_with_ts.first_ts = _utc(2026, 7, 1)
        acc_no_ts = _PromptAccumulator()
        result = _build_prompt_metrics({"p_with": acc_with_ts, "p_no": acc_no_ts})
        # The one with timestamp should come first (sorted reverse by ts, None becomes "")
        ts_values = [r.timestamp for r in result]
        self.assertIsNotNone(ts_values[0])

    def test_timestamp_field_is_iso_format(self):
        acc = _PromptAccumulator()
        acc.first_ts = _utc(2026, 7, 1, 12)
        result = _build_prompt_metrics({"p1": acc})
        self.assertIn("2026-07-01", result[0].timestamp)

    def test_cost_rounded_to_6_decimal_places(self):
        acc = _PromptAccumulator()
        acc.cost = 0.0000001234567
        result = _build_prompt_metrics({"p1": acc})
        self.assertEqual(result[0].cost, round(result[0].cost, 6))


# ---------------------------------------------------------------------------
# _accumulate_prompt_events
# ---------------------------------------------------------------------------

class TestAccumulatePromptEvents(unittest.TestCase):

    def test_empty_records_returns_empty(self):
        result = _accumulate_prompt_events([], since_dt=None, session_id=None)
        self.assertEqual(dict(result), {})

    def test_event_without_prompt_id_skipped(self):
        event = _make_event("user_prompt", [_attr("session.id", "s1")])
        record = _make_record([event])
        result = _accumulate_prompt_events([record], since_dt=None, session_id=None)
        self.assertEqual(dict(result), {})

    def test_event_with_prompt_id_accumulated(self):
        event = _make_user_prompt_event(prompt_id="p1", session_id="s1")
        record = _make_record([event])
        result = _accumulate_prompt_events([record], since_dt=None, session_id=None)
        self.assertIn("p1", result)
        self.assertEqual(result["p1"].session_id, "s1")

    def test_since_dt_filters_older_events(self):
        old_ts = _nano(_utc(2026, 1, 1))
        event = _make_user_prompt_event(prompt_id="p1", time_nano=old_ts)
        record = _make_record([event])
        since = _utc(2026, 7, 1)
        result = _accumulate_prompt_events([record], since_dt=since, session_id=None)
        # Event is before since_dt, so excluded
        self.assertEqual(dict(result), {})

    def test_session_id_filter_excludes_other_sessions(self):
        e1 = _make_user_prompt_event(prompt_id="p1", session_id="sess-a")
        e2 = _make_user_prompt_event(prompt_id="p2", session_id="sess-b")
        record = _make_record([e1, e2])
        result = _accumulate_prompt_events([record], since_dt=None, session_id="sess-a")
        self.assertIn("p1", result)
        self.assertNotIn("p2", result)

    def test_multiple_events_same_prompt_accumulated(self):
        e1 = _make_api_request_event(prompt_id="p1", input_tokens=100)
        e2 = _make_api_request_event(prompt_id="p1", input_tokens=200)
        record = _make_record([e1, e2])
        result = _accumulate_prompt_events([record], since_dt=None, session_id=None)
        self.assertEqual(result["p1"].input_tokens, 300)
        self.assertEqual(result["p1"].api_calls, 2)

    def test_two_different_prompts_tracked_separately(self):
        e1 = _make_user_prompt_event(prompt_id="p1")
        e2 = _make_user_prompt_event(prompt_id="p2")
        record = _make_record([e1, e2])
        result = _accumulate_prompt_events([record], since_dt=None, session_id=None)
        self.assertIn("p1", result)
        self.assertIn("p2", result)


# ---------------------------------------------------------------------------
# get_prompt_metrics — integration via mock
# ---------------------------------------------------------------------------

class TestGetPromptMetrics(unittest.TestCase):

    @mock.patch("telemetry.otel.analytics.prompts.OTLPReader")
    @mock.patch("telemetry.otel.analytics.prompts.OTLPDataDir")
    def test_no_data_dir_uses_from_env(self, mock_data_dir_cls, mock_reader_cls):
        from telemetry.otel.analytics.prompts import get_prompt_metrics
        mock_data_dir_cls.from_env.return_value = mock.MagicMock()
        mock_reader_cls.return_value.read_events.return_value = []
        get_prompt_metrics()
        mock_data_dir_cls.from_env.assert_called_once()

    @mock.patch("telemetry.otel.analytics.prompts.OTLPReader")
    def test_empty_events_returns_empty_list(self, mock_reader_cls):
        from telemetry.otel.analytics.prompts import get_prompt_metrics
        from telemetry.otel.reader import OTLPDataDir
        mock_reader_cls.return_value.read_events.return_value = []
        result = get_prompt_metrics(data_dir=OTLPDataDir.default())
        self.assertEqual(result, [])

    @mock.patch("telemetry.otel.analytics.prompts.OTLPReader")
    def test_returns_prompt_metrics_for_events(self, mock_reader_cls):
        from telemetry.otel.analytics.prompts import get_prompt_metrics
        from telemetry.otel.reader import OTLPDataDir
        e1 = _make_user_prompt_event(prompt_id="p1", prompt_length=100)
        e2 = _make_api_request_event(prompt_id="p1", input_tokens=500, output_tokens=100)
        record = _make_record([e1, e2])
        mock_reader_cls.return_value.read_events.return_value = [record]
        result = get_prompt_metrics(data_dir=OTLPDataDir.default())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].prompt_id, "p1")
        self.assertEqual(result[0].prompt_length, 100)
        self.assertEqual(result[0].api_calls, 1)

    @mock.patch("telemetry.otel.analytics.prompts.now_utc")
    @mock.patch("telemetry.otel.analytics.prompts.parse_window")
    @mock.patch("telemetry.otel.analytics.prompts.OTLPReader")
    def test_since_string_parsed_to_cutoff(self, mock_reader_cls, mock_parse_window, mock_now_utc):
        from telemetry.otel.analytics.prompts import get_prompt_metrics
        from telemetry.otel.reader import OTLPDataDir
        from datetime import timedelta
        now = _utc(2026, 7, 15)
        mock_now_utc.return_value = now
        mock_parse_window.return_value = timedelta(days=7)
        mock_reader_cls.return_value.read_events.return_value = []
        get_prompt_metrics(data_dir=OTLPDataDir.default(), since="7d")
        mock_parse_window.assert_called_once_with("7d")

    @mock.patch("telemetry.otel.analytics.prompts.OTLPReader")
    def test_session_id_filter_applied(self, mock_reader_cls):
        from telemetry.otel.analytics.prompts import get_prompt_metrics
        from telemetry.otel.reader import OTLPDataDir
        e_a = _make_user_prompt_event(prompt_id="pa", session_id="sess-a")
        e_b = _make_user_prompt_event(prompt_id="pb", session_id="sess-b")
        record = _make_record([e_a, e_b])
        mock_reader_cls.return_value.read_events.return_value = [record]
        result = get_prompt_metrics(data_dir=OTLPDataDir.default(), session_id="sess-a")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].prompt_id, "pa")


if __name__ == "__main__":
    unittest.main()
