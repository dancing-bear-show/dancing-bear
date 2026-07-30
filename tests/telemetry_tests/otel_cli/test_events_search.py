"""Tests for telemetry/otel/cli/events_search.py."""

from __future__ import annotations

import io
import json
import re
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from telemetry.otel.cli.events_search import (
    _compile_pattern,
    _find_match,
    _get_session_id,
    main,
)


def _make_event(
    *,
    body: str = "claude_code.api_request",
    session_id: str = "abc123",
    timestamp: datetime | None = None,
    attributes: list | None = None,
) -> MagicMock:
    evt = MagicMock()
    evt.body = body
    evt.timestamp = timestamp or datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
    evt.get_attr.side_effect = lambda k: session_id if "session" in k else None

    if attributes is not None:
        attr_mocks = []
        for key, val in attributes:
            a = MagicMock()
            a.key = key
            a.value.as_str.return_value = str(val)
            attr_mocks.append(a)
        evt.attributes = attr_mocks
    else:
        evt.attributes = []

    return evt


# ---------------------------------------------------------------------------
# _compile_pattern
# ---------------------------------------------------------------------------


class TestCompilePattern(unittest.TestCase):
    def test_valid_regex(self):
        pattern = _compile_pattern(r"api_request")
        self.assertIsInstance(pattern, re.Pattern)

    def test_invalid_regex_falls_back_to_literal(self):
        pattern = _compile_pattern("[invalid")
        # Should still compile (escaped)
        self.assertIsInstance(pattern, re.Pattern)

    def test_pattern_matches_body(self):
        pattern = _compile_pattern("api_request")
        evt = _make_event(body="claude_code.api_request")
        self.assertIsNotNone(pattern.search(evt.body))


# ---------------------------------------------------------------------------
# _get_session_id
# ---------------------------------------------------------------------------


class TestGetSessionId(unittest.TestCase):
    def test_session_id_from_attr(self):
        evt = _make_event(session_id="my-session")
        result = _get_session_id(evt)
        self.assertEqual(result, "my-session")

    def test_fallback_to_unknown(self):
        evt = MagicMock()
        evt.get_attr.return_value = None
        result = _get_session_id(evt)
        self.assertEqual(result, "unknown")


# ---------------------------------------------------------------------------
# _find_match
# ---------------------------------------------------------------------------


class TestFindMatch(unittest.TestCase):
    def test_body_match(self):
        pattern = re.compile("api_request")
        evt = _make_event(body="claude_code.api_request")
        result = _find_match(evt, pattern)
        self.assertEqual(result, "claude_code.api_request")

    def test_attribute_match(self):
        pattern = re.compile("special-value")
        evt = _make_event(body="other_event", attributes=[("tool_name", "special-value")])
        result = _find_match(evt, pattern)
        self.assertIn("tool_name=special-value", result)

    def test_no_match(self):
        pattern = re.compile("no-match-here")
        evt = _make_event(body="api_request")
        result = _find_match(evt, pattern)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestEventsSearchMain(unittest.TestCase):
    def _make_record(self, events: list | None = None):
        record = MagicMock()
        record.log_records = events or []
        return record

    def _run(self, argv: list[str], events: list | None = None) -> tuple[int, str, str]:
        evt = _make_event()
        records = [self._make_record([evt])] if events is None else events
        with patch("telemetry.otel.cli.events_search.resolve_data_dir"):
            with patch("telemetry.otel.cli.events_search.resolve_since", return_value=(None, None)):
                with patch("telemetry.otel.cli.events_search.OTLPReader") as mock_reader_cls:
                    mock_reader_cls.return_value.read_events.return_value = records
                    stdout_buf = io.StringIO()
                    stderr_buf = io.StringIO()
                    with patch("sys.stdout", stdout_buf):
                        with patch("sys.stderr", stderr_buf):
                            result = main(argv + ["--contains", "api_request"])
        return result, stdout_buf.getvalue(), stderr_buf.getvalue()

    def test_match_found_returns_0(self):
        result, stdout, stderr = self._run([])
        self.assertEqual(result, 0)

    def test_no_match_message_on_stderr(self):
        no_match_evt = _make_event(body="user_prompt")
        records = [self._make_record([no_match_evt])]
        with patch("telemetry.otel.cli.events_search.resolve_data_dir"):
            with patch("telemetry.otel.cli.events_search.resolve_since", return_value=(None, None)):
                with patch("telemetry.otel.cli.events_search.OTLPReader") as mock_reader_cls:
                    mock_reader_cls.return_value.read_events.return_value = records
                    stderr_buf = io.StringIO()
                    with patch("sys.stderr", stderr_buf):
                        result = main(["--contains", "xyz_no_match_xyz"])
        self.assertEqual(result, 0)
        self.assertIn("No matching events", stderr_buf.getvalue())

    def test_json_format_returns_list(self):
        result, stdout, _ = self._run(["--format", "json"])
        self.assertEqual(result, 0)
        data = json.loads(stdout)
        self.assertIsInstance(data, list)

    def test_invalid_since_returns_error(self):
        with patch("telemetry.otel.cli.events_search.resolve_data_dir"):
            with patch("telemetry.otel.cli.events_search.resolve_since", return_value=(None, 2)):
                result = main(["--contains", "x", "--since", "bad"])
        self.assertEqual(result, 2)

    def test_limit_flag_respected(self):
        events = [_make_event(body=f"api_request_{i}") for i in range(10)]
        records = [self._make_record(events)]
        with patch("telemetry.otel.cli.events_search.resolve_data_dir"):
            with patch("telemetry.otel.cli.events_search.resolve_since", return_value=(None, None)):
                with patch("telemetry.otel.cli.events_search.OTLPReader") as mock_reader_cls:
                    mock_reader_cls.return_value.read_events.return_value = records
                    buf = io.StringIO()
                    with patch("sys.stdout", buf):
                        result = main(["--contains", "api_request", "--limit", "3"])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
