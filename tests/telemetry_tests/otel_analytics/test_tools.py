"""Tests for telemetry/otel/analytics/tools.py."""

import unittest
from datetime import datetime
from unittest import mock

from telemetry.otel.analytics.tools import (
    _ToolAccumulator,
    _accumulate_tool_events,
    _build_tool_summaries,
    _process_tool_event,
)
from telemetry.otel.cost_models import ToolErrorSummary
from telemetry.otel.models import OTLPAttribute, OTLPEvent, OTLPEventsRecord, OTLPResource, OTLPValue

from tests.telemetry_tests.otel_analytics._shared_helpers import _utc


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _nano(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


def _attr(key: str, value: str | None = None) -> OTLPAttribute:
    return OTLPAttribute(key=key, value=OTLPValue(string_value=value))


def _attr_float(key: str, value: float) -> OTLPAttribute:
    return OTLPAttribute(key=key, value=OTLPValue(double_value=value))


def _attr_bool(key: str, value: bool) -> OTLPAttribute:
    return OTLPAttribute(key=key, value=OTLPValue(bool_value=value))


_BASE_NANO = _nano(_utc(2026, 7, 1))


def _make_tool_event(
    tool_name: str | None = "Bash",
    session_id: str = "sess-1",
    success: str | bool | None = "true",
    duration_ms: float | None = None,
    body: str = "tool_result",
    time_nano: int | None = None,
) -> OTLPEvent:
    attrs = []
    if tool_name is not None:
        attrs.append(_attr("tool_name", tool_name))
    attrs.append(_attr("session.id", session_id))
    if success is not None:
        if isinstance(success, bool):
            attrs.append(_attr_bool("success", success))
        else:
            attrs.append(_attr("success", success))
    if duration_ms is not None:
        attrs.append(_attr_float("duration_ms", duration_ms))
    ts = time_nano if time_nano is not None else _BASE_NANO
    return OTLPEvent(
        time_unix_nano=ts,
        observed_time_unix_nano=ts,
        body=body,
        attributes=attrs,
    )


def _make_record(events: list[OTLPEvent]) -> OTLPEventsRecord:
    return OTLPEventsRecord(
        resource=OTLPResource(service_name="test", service_version="0.0.1"),
        scope_name="test",
        log_records=events,
    )


# ---------------------------------------------------------------------------
# _process_tool_event
# ---------------------------------------------------------------------------

class TestProcessToolEvent(unittest.TestCase):

    def test_increments_total_calls(self):
        tools: dict = {}
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        event = _make_tool_event(tool_name="Read")
        _process_tool_event(event, tools)
        self.assertEqual(tools["Read"].total_calls, 1)

    def test_multiple_events_accumulate_calls(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        _process_tool_event(_make_tool_event(tool_name="Bash"), tools)
        _process_tool_event(_make_tool_event(tool_name="Bash"), tools)
        self.assertEqual(tools["Bash"].total_calls, 2)

    def test_different_tools_tracked_separately(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        _process_tool_event(_make_tool_event(tool_name="Read"), tools)
        _process_tool_event(_make_tool_event(tool_name="Bash"), tools)
        self.assertEqual(tools["Read"].total_calls, 1)
        self.assertEqual(tools["Bash"].total_calls, 1)

    def test_missing_tool_name_falls_back_to_unknown(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        event = _make_tool_event(tool_name=None)
        _process_tool_event(event, tools)
        self.assertEqual(tools["unknown"].total_calls, 1)

    def test_session_id_added_to_sessions_set(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        event = _make_tool_event(tool_name="Bash", session_id="sess-abc")
        _process_tool_event(event, tools)
        self.assertIn("sess-abc", tools["Bash"].sessions)

    def test_multiple_sessions_tracked_in_set(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        _process_tool_event(_make_tool_event("Bash", session_id="s1"), tools)
        _process_tool_event(_make_tool_event("Bash", session_id="s2"), tools)
        _process_tool_event(_make_tool_event("Bash", session_id="s1"), tools)  # duplicate
        self.assertEqual(tools["Bash"].sessions, {"s1", "s2"})

    def test_success_false_string_counted_as_failure(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        _process_tool_event(_make_tool_event(success="false"), tools)
        self.assertEqual(tools["Bash"].failures, 1)

    def test_success_False_string_counted_as_failure(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        _process_tool_event(_make_tool_event(success="False"), tools)
        self.assertEqual(tools["Bash"].failures, 1)

    def test_success_false_bool_counted_as_failure(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        _process_tool_event(_make_tool_event(success=False), tools)
        self.assertEqual(tools["Bash"].failures, 1)

    def test_success_true_string_not_counted_as_failure(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        _process_tool_event(_make_tool_event(success="true"), tools)
        self.assertEqual(tools["Bash"].failures, 0)

    def test_positive_duration_appended_to_durations(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        _process_tool_event(_make_tool_event(duration_ms=250.0), tools)
        self.assertEqual(tools["Bash"].durations, [250.0])

    def test_zero_duration_not_appended(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        _process_tool_event(_make_tool_event(duration_ms=0.0), tools)
        self.assertEqual(tools["Bash"].durations, [])

    def test_no_duration_not_appended(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        _process_tool_event(_make_tool_event(duration_ms=None), tools)
        self.assertEqual(tools["Bash"].durations, [])


# ---------------------------------------------------------------------------
# _accumulate_tool_events
# ---------------------------------------------------------------------------

class TestAccumulateToolEvents(unittest.TestCase):

    def test_empty_records_returns_empty(self):
        result = _accumulate_tool_events([], since=None)
        self.assertEqual(dict(result), {})

    def test_non_tool_result_event_ignored(self):
        event = _make_tool_event(body="api_request")
        record = _make_record([event])
        result = _accumulate_tool_events([record], since=None)
        self.assertEqual(dict(result), {})

    def test_tool_result_event_accumulated(self):
        event = _make_tool_event(tool_name="Read", body="tool_result")
        record = _make_record([event])
        result = _accumulate_tool_events([record], since=None)
        self.assertIn("Read", result)
        self.assertEqual(result["Read"].total_calls, 1)

    def test_since_cutoff_excludes_old_events(self):
        old_ts = _nano(_utc(2026, 1, 1))
        new_ts = _nano(_utc(2026, 7, 1))
        old_event = _make_tool_event("Bash", time_nano=old_ts)
        new_event = _make_tool_event("Read", time_nano=new_ts)
        record = _make_record([old_event, new_event])
        since = _utc(2026, 7, 1)
        result = _accumulate_tool_events([record], since=since)
        # old_event timestamp equals since (not strictly less), so not excluded
        # Read is at new_ts which equals since
        self.assertIn("Read", result)

    def test_since_cutoff_excludes_strictly_earlier_events(self):
        old_ts = _nano(_utc(2026, 1, 1))
        event = _make_tool_event("Bash", time_nano=old_ts)
        record = _make_record([event])
        since = _utc(2026, 7, 1)  # strictly after old_ts
        result = _accumulate_tool_events([record], since=since)
        self.assertNotIn("Bash", result)

    def test_multiple_records_processed(self):
        r1 = _make_record([_make_tool_event("Read")])
        r2 = _make_record([_make_tool_event("Bash")])
        result = _accumulate_tool_events([r1, r2], since=None)
        self.assertIn("Read", result)
        self.assertIn("Bash", result)

    def test_mixed_success_and_failure(self):
        events = [
            _make_tool_event("Bash", success="true"),
            _make_tool_event("Bash", success="false"),
            _make_tool_event("Bash", success="true"),
        ]
        record = _make_record(events)
        result = _accumulate_tool_events([record], since=None)
        self.assertEqual(result["Bash"].total_calls, 3)
        self.assertEqual(result["Bash"].failures, 1)


# ---------------------------------------------------------------------------
# _build_tool_summaries
# ---------------------------------------------------------------------------

class TestBuildToolSummaries(unittest.TestCase):

    def test_empty_input_returns_empty(self):
        result = _build_tool_summaries({})
        self.assertEqual(result, [])

    def test_single_tool_summary_correct(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        acc = tools["Bash"]
        acc.total_calls = 5
        acc.failures = 1
        acc.durations = [100.0, 200.0, 300.0]
        acc.sessions.add("s1")
        acc.sessions.add("s2")
        result = _build_tool_summaries(tools)
        self.assertEqual(len(result), 1)
        s = result[0]
        self.assertEqual(s.tool_name, "Bash")
        self.assertEqual(s.total_calls, 5)
        self.assertEqual(s.failures, 1)
        self.assertAlmostEqual(s.failure_rate, 0.2, places=6)
        self.assertAlmostEqual(s.avg_duration_ms, 200.0, places=6)
        self.assertEqual(s.sessions_affected, 2)

    def test_failure_rate_zero_when_no_failures(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        acc = tools["Read"]
        acc.total_calls = 10
        acc.failures = 0
        result = _build_tool_summaries(tools)
        self.assertAlmostEqual(result[0].failure_rate, 0.0, places=6)

    def test_failure_rate_zero_when_no_total_calls(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        acc = tools["Edit"]
        acc.total_calls = 0
        acc.failures = 0
        result = _build_tool_summaries(tools)
        self.assertAlmostEqual(result[0].failure_rate, 0.0, places=6)

    def test_avg_duration_zero_when_no_durations(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        acc = tools["Bash"]
        acc.total_calls = 3
        acc.durations = []
        result = _build_tool_summaries(tools)
        self.assertAlmostEqual(result[0].avg_duration_ms, 0.0, places=6)

    def test_sorted_by_tool_name(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        tools["Zebra"].total_calls = 1
        tools["Apple"].total_calls = 1
        tools["Mango"].total_calls = 1
        result = _build_tool_summaries(tools)
        names = [r.tool_name for r in result]
        self.assertEqual(names, sorted(names))

    def test_result_is_tool_error_summary_instances(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        tools["Bash"].total_calls = 1
        result = _build_tool_summaries(tools)
        for r in result:
            self.assertIsInstance(r, ToolErrorSummary)

    def test_multiple_tools_returned(self):
        from collections import defaultdict
        tools = defaultdict(_ToolAccumulator)
        for name in ["Bash", "Read", "Write", "Edit"]:
            tools[name].total_calls = 1
        result = _build_tool_summaries(tools)
        self.assertEqual(len(result), 4)


# ---------------------------------------------------------------------------
# get_tool_summaries — integration via mock
# ---------------------------------------------------------------------------

class TestGetToolSummaries(unittest.TestCase):

    @mock.patch("telemetry.otel.analytics.tools.OTLPReader")
    @mock.patch("telemetry.otel.analytics.tools.OTLPDataDir")
    def test_no_data_dir_uses_from_env(self, mock_data_dir_cls, mock_reader_cls):
        from telemetry.otel.analytics.tools import get_tool_summaries
        mock_data_dir_cls.from_env.return_value = mock.MagicMock()
        mock_reader_cls.return_value.read_events.return_value = []
        get_tool_summaries()
        mock_data_dir_cls.from_env.assert_called_once()

    @mock.patch("telemetry.otel.analytics.tools.OTLPReader")
    def test_explicit_data_dir_passed_to_reader(self, mock_reader_cls):
        from telemetry.otel.analytics.tools import get_tool_summaries
        from telemetry.otel.reader import OTLPDataDir
        mock_reader_cls.return_value.read_events.return_value = []
        data_dir = OTLPDataDir.default()
        get_tool_summaries(data_dir=data_dir)
        mock_reader_cls.assert_called_once_with(data_dir)

    @mock.patch("telemetry.otel.analytics.tools.OTLPReader")
    def test_empty_events_returns_empty_list(self, mock_reader_cls):
        from telemetry.otel.analytics.tools import get_tool_summaries
        from telemetry.otel.reader import OTLPDataDir
        mock_reader_cls.return_value.read_events.return_value = []
        result = get_tool_summaries(data_dir=OTLPDataDir.default())
        self.assertEqual(result, [])

    @mock.patch("telemetry.otel.analytics.tools.OTLPReader")
    def test_returns_tool_error_summary_for_tool_events(self, mock_reader_cls):
        from telemetry.otel.analytics.tools import get_tool_summaries
        from telemetry.otel.reader import OTLPDataDir
        event = _make_tool_event("Bash", success="true", duration_ms=100.0)
        record = _make_record([event])
        mock_reader_cls.return_value.read_events.return_value = [record]
        result = get_tool_summaries(data_dir=OTLPDataDir.default())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].tool_name, "Bash")
        self.assertEqual(result[0].total_calls, 1)
        self.assertEqual(result[0].failures, 0)
        self.assertAlmostEqual(result[0].avg_duration_ms, 100.0, places=1)

    @mock.patch("telemetry.otel.analytics.tools.OTLPReader")
    def test_since_filter_applied(self, mock_reader_cls):
        from telemetry.otel.analytics.tools import get_tool_summaries
        from telemetry.otel.reader import OTLPDataDir
        old_event = _make_tool_event("Bash", time_nano=_nano(_utc(2026, 1, 1)))
        new_event = _make_tool_event("Read", time_nano=_nano(_utc(2026, 7, 15)))
        record = _make_record([old_event, new_event])
        mock_reader_cls.return_value.read_events.return_value = [record]
        since = _utc(2026, 7, 1)
        result = get_tool_summaries(data_dir=OTLPDataDir.default(), since=since)
        tool_names = [r.tool_name for r in result]
        self.assertNotIn("Bash", tool_names)
        self.assertIn("Read", tool_names)


if __name__ == "__main__":
    unittest.main()
