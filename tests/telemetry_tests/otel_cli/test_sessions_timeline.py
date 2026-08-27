"""Tests for telemetry/otel/cli/sessions_timeline.py.

Covers the lines not reached by test_sessions.py:
- _sum_token_attrs: inner loop body with valid attrs (lines 17-21), ValueError/TypeError swallow,
  non-matching keys skipped, empty attributes list
- _event_to_timeline_entry: conversion to dict (lines 85-86)
- _output_timeline: no-events case, events-found case, since filter, session_id filter,
  OTLPReader delegation (lines 117-143)

All OTLPReader interactions are mocked. No network or real file I/O.
"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from telemetry.otel.cli.sessions_timeline import (
    _event_to_timeline_entry,
    _format_timeline_entry,
    _output_timeline,
    _sum_token_attrs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_attr(key: str, value: str) -> NS:
    """Build a minimal OTLP attribute-like object."""
    v = NS(as_str=lambda: value)
    return NS(key=key, value=v)


def _make_event(
    *,
    body: str = "claude_code.api_request",
    session_id: str = "sess-abc",
    timestamp: datetime | None = None,
    attrs: list | None = None,
    get_attr_side_effect=None,
    get_attr_as_float_side_effect=None,
) -> MagicMock:
    """Build a mock OTLP event object."""
    event = MagicMock()
    event.body = body
    event.timestamp = timestamp or datetime.now(timezone.utc)
    event.attributes = attrs if attrs is not None else []

    if get_attr_side_effect is not None:
        event.get_attr.side_effect = get_attr_side_effect
    else:
        # Default: return session_id for session.id / session_id keys, None for others
        def _default_get_attr(key):
            if key in ("session.id", "session_id"):
                return session_id
            return None
        event.get_attr.side_effect = _default_get_attr

    if get_attr_as_float_side_effect is not None:
        event.get_attr_as_float.side_effect = get_attr_as_float_side_effect
    else:
        event.get_attr_as_float.return_value = None

    return event


def _make_record(events: list) -> NS:
    """Build a mock OTLP record with log_records."""
    return NS(log_records=events)


# ---------------------------------------------------------------------------
# _sum_token_attrs
# ---------------------------------------------------------------------------

class TestSumTokenAttrs(unittest.TestCase):
    """Tests for _sum_token_attrs — covers the inner loop and exception swallows."""

    def test_empty_attributes_returns_zero(self) -> None:
        """Happy path: no attributes → zero tokens."""
        event = MagicMock()
        event.attributes = []
        result = _sum_token_attrs(event)
        self.assertEqual(result, 0)

    def test_input_and_output_tokens_summed(self) -> None:
        """Happy path: input_tokens and output_tokens are both summed."""
        event = MagicMock()
        event.attributes = [
            _make_attr("input_tokens", "100"),
            _make_attr("output_tokens", "50"),
        ]
        result = _sum_token_attrs(event)
        self.assertEqual(result, 150)

    def test_non_token_keys_ignored(self) -> None:
        """Attributes with unrelated keys do not contribute to the total."""
        event = MagicMock()
        event.attributes = [
            _make_attr("model", "claude-sonnet-4-6"),
            _make_attr("input_tokens", "200"),
        ]
        result = _sum_token_attrs(event)
        self.assertEqual(result, 200)

    def test_float_string_value_is_parsed(self) -> None:
        """Values like '1234.0' are parsed via int(float(...))."""
        event = MagicMock()
        event.attributes = [_make_attr("input_tokens", "1234.0")]
        result = _sum_token_attrs(event)
        self.assertEqual(result, 1234)

    def test_non_numeric_value_is_skipped(self) -> None:
        """ValueError from a non-numeric value is swallowed; rest of attrs still counted."""
        event = MagicMock()
        event.attributes = [
            _make_attr("input_tokens", "not_a_number"),
            _make_attr("output_tokens", "80"),
        ]
        result = _sum_token_attrs(event)
        # "not_a_number" is skipped; "80" is still counted
        self.assertEqual(result, 80)

    def test_type_error_value_is_skipped(self) -> None:
        """TypeError from as_str() raising is swallowed; rest of attrs still counted."""
        event = MagicMock()
        bad_attr = NS(key="input_tokens", value=NS(as_str=lambda: (_ for _ in ()).throw(TypeError("oops"))))
        good_attr = _make_attr("output_tokens", "30")
        event.attributes = [bad_attr, good_attr]
        result = _sum_token_attrs(event)
        self.assertEqual(result, 30)


# ---------------------------------------------------------------------------
# _event_to_timeline_entry
# ---------------------------------------------------------------------------

class TestEventToTimelineEntry(unittest.TestCase):
    """Tests for _event_to_timeline_entry — covers lines 85-86."""

    def test_returns_dict_with_timestamp_eventtype_detail(self) -> None:
        """Happy path: output dict contains expected keys."""
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        event = _make_event(body="claude_code.api_request", timestamp=ts)
        event.get_attr.return_value = "claude-sonnet-4-6"

        result = _event_to_timeline_entry(event)

        self.assertEqual(result["timestamp"], ts)
        self.assertEqual(result["event_type"], "claude_code.api_request")
        self.assertIn("detail", result)

    def test_unknown_event_body_produces_empty_detail(self) -> None:
        """For unknown event types, detail is empty string."""
        event = _make_event(body="some.unknown_event")
        result = _event_to_timeline_entry(event)
        self.assertEqual(result["detail"], "")

    def test_api_error_body_produces_status_detail(self) -> None:
        """api_error event includes status code in detail."""
        event = _make_event(
            body="claude_code.api_error",
            get_attr_side_effect=lambda k: "429" if k == "status_code" else None,
        )
        result = _event_to_timeline_entry(event)
        self.assertIn("429", result["detail"])


# ---------------------------------------------------------------------------
# _output_timeline
# ---------------------------------------------------------------------------

class TestOutputTimeline(unittest.TestCase):
    """Tests for _output_timeline — covers lines 117-143."""

    def _make_data_dir(self) -> MagicMock:
        return MagicMock()

    def _run(self, *, records: list, session_id: str = "sess-abc", since=None) -> str:
        """Run _output_timeline with mocked OTLPReader and capture stdout."""
        data_dir = self._make_data_dir()

        with patch("telemetry.otel.cli.sessions_timeline.OTLPReader") as mock_reader_cls:
            mock_reader = MagicMock()
            mock_reader.read_events.return_value = records
            mock_reader_cls.return_value = mock_reader

            buf = io.StringIO()
            with redirect_stdout(buf):
                _output_timeline(data_dir, session_id, since)

        return buf.getvalue()

    def test_no_events_prints_no_events_message(self) -> None:
        """When no events match the session_id, prints 'No events found'."""
        output = self._run(records=[], session_id="sess-xyz")
        self.assertIn("No events found", output)
        self.assertIn("sess-xyz", output)

    def test_events_for_different_session_are_filtered(self) -> None:
        """Events belonging to a different session_id are excluded."""
        ts = datetime.now(timezone.utc)
        event = _make_event(session_id="other-session", timestamp=ts)
        record = _make_record([event])
        output = self._run(records=[record], session_id="target-session")
        self.assertIn("No events found", output)

    def test_matching_events_are_displayed(self) -> None:
        """Events with matching session_id are displayed."""
        ts = datetime.now(timezone.utc)
        event = _make_event(body="claude_code.api_request", session_id="sess-abc", timestamp=ts)
        event.get_attr.return_value = "claude-sonnet-4-6"
        event.get_attr_as_float.return_value = None
        record = _make_record([event])
        output = self._run(records=[record], session_id="sess-abc")
        self.assertIn("Timeline for sess-abc", output)
        self.assertIn("api_request", output)

    def test_since_filter_excludes_old_events(self) -> None:
        """Events before the 'since' cutoff are excluded."""
        now = datetime.now(timezone.utc)
        old_ts = now - timedelta(hours=2)
        new_ts = now
        since = now - timedelta(hours=1)

        old_event = _make_event(session_id="sess-abc", timestamp=old_ts)
        new_event = _make_event(body="claude_code.user_prompt", session_id="sess-abc", timestamp=new_ts)
        new_event.get_attr.side_effect = lambda k: "sess-abc" if k in ("session.id", "session_id") else "500"

        record = _make_record([old_event, new_event])
        output = self._run(records=[record], session_id="sess-abc", since=since)

        # Old event excluded, new event included
        self.assertIn("Timeline for sess-abc", output)
        self.assertIn("(1 events)", output)

    def test_since_none_includes_all_events(self) -> None:
        """When since is None, all events for the session are shown."""
        ts = datetime.now(timezone.utc) - timedelta(days=10)
        event = _make_event(body="claude_code.api_request", session_id="sess-abc", timestamp=ts)
        event.get_attr.return_value = "claude-sonnet-4-6"
        record = _make_record([event])
        output = self._run(records=[record], session_id="sess-abc", since=None)
        self.assertIn("Timeline for sess-abc", output)
        self.assertIn("(1 events)", output)

    def test_events_sorted_by_timestamp(self) -> None:
        """Multiple events are output in ascending timestamp order."""
        now = datetime.now(timezone.utc)
        ts1 = now - timedelta(minutes=5)
        ts2 = now

        event1 = _make_event(body="claude_code.api_request", session_id="sess-abc", timestamp=ts1)
        event1.get_attr.return_value = "claude-sonnet-4-6"
        event1.get_attr_as_float.return_value = None

        event2 = _make_event(body="claude_code.user_prompt", session_id="sess-abc", timestamp=ts2)
        event2.get_attr.side_effect = lambda k: "sess-abc" if k in ("session.id", "session_id") else "100"

        # Supply events in reverse order to confirm sorting
        record = _make_record([event2, event1])
        output = self._run(records=[record, ], session_id="sess-abc")

        lines = [ln for ln in output.splitlines() if "[" in ln]
        self.assertEqual(len(lines), 2)
        # First line should have the earlier timestamp
        self.assertIn(ts1.strftime("%H:%M:%S"), lines[0])

    def test_multiple_records_are_all_read(self) -> None:
        """Events across multiple records are all collected."""
        ts = datetime.now(timezone.utc)
        event1 = _make_event(body="claude_code.api_request", session_id="sess-abc", timestamp=ts)
        event1.get_attr.return_value = "claude-sonnet-4-6"
        event1.get_attr_as_float.return_value = None

        event2 = _make_event(body="claude_code.user_prompt", session_id="sess-abc",
                             timestamp=ts + timedelta(seconds=1))
        event2.get_attr.side_effect = lambda k: "sess-abc" if k in ("session.id", "session_id") else "200"

        record1 = _make_record([event1])
        record2 = _make_record([event2])
        output = self._run(records=[record1, record2], session_id="sess-abc")
        self.assertIn("(2 events)", output)

    def test_session_id_resolved_via_session_id_key(self) -> None:
        """session_id attribute key is used as fallback when session.id is missing."""
        ts = datetime.now(timezone.utc)
        event = MagicMock()
        event.body = "claude_code.api_request"
        event.timestamp = ts
        event.attributes = []
        event.get_attr_as_float.return_value = None
        # session.id returns None, session_id returns "target"
        def _sid(k):
            if k == "session.id":
                return None
            if k == "session_id":
                return "target"
            return "claude-sonnet-4-6"
        event.get_attr.side_effect = _sid

        record = _make_record([event])
        output = self._run(records=[record], session_id="target")
        self.assertIn("Timeline for target", output)

    def test_unknown_session_id_falls_back_to_unknown(self) -> None:
        """When neither session.id nor session_id is present, sid becomes 'unknown'."""
        ts = datetime.now(timezone.utc)
        event = MagicMock()
        event.body = "some_event"
        event.timestamp = ts
        event.attributes = []
        event.get_attr.return_value = None  # both session attrs return None
        event.get_attr_as_float.return_value = None

        record = _make_record([event])
        # session_id="unknown" should match the fallback
        output = self._run(records=[record], session_id="unknown")
        self.assertIn("Timeline for unknown", output)

    def test_empty_records_prints_no_events(self) -> None:
        """Empty record list with no log_records results in 'No events found'."""
        output = self._run(records=[], session_id="sess-abc")
        self.assertIn("No events found", output)


# ---------------------------------------------------------------------------
# _format_timeline_entry — edge cases not covered in test_sessions.py
# ---------------------------------------------------------------------------

class TestFormatTimelineEntry(unittest.TestCase):
    """Edge cases for _format_timeline_entry."""

    def test_none_timestamp_shows_unknown_time(self) -> None:
        """Entry with no timestamp shows ??:??:??."""
        entry = {"timestamp": None, "event_type": "some.event", "detail": ""}
        result = _format_timeline_entry(entry)
        self.assertIn("??:??:??", result)

    def test_event_type_with_dot_shows_last_segment(self) -> None:
        """Event type 'foo.bar.baz' is shortened to 'baz'."""
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entry = {"timestamp": ts, "event_type": "foo.bar.baz", "detail": ""}
        result = _format_timeline_entry(entry)
        self.assertIn("baz", result)
        self.assertNotIn("foo", result)

    def test_event_type_without_dot_shown_as_is(self) -> None:
        """Event type without dots is emitted as-is."""
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entry = {"timestamp": ts, "event_type": "plain_event", "detail": ""}
        result = _format_timeline_entry(entry)
        self.assertIn("plain_event", result)

    def test_detail_present_included_in_output(self) -> None:
        """When detail is non-empty, it is wrapped in parentheses."""
        ts = datetime(2026, 1, 1, 9, 30, 0, tzinfo=timezone.utc)
        entry = {"timestamp": ts, "event_type": "some.event", "detail": "info here"}
        result = _format_timeline_entry(entry)
        self.assertIn("(info here)", result)

    def test_no_detail_omits_parentheses(self) -> None:
        """When detail is empty, no parentheses appear."""
        ts = datetime(2026, 1, 1, 9, 30, 0, tzinfo=timezone.utc)
        entry = {"timestamp": ts, "event_type": "some.event", "detail": ""}
        result = _format_timeline_entry(entry)
        self.assertNotIn("(", result)


if __name__ == "__main__":
    unittest.main()
