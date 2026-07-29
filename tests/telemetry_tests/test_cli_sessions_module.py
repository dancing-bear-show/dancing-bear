"""Tests for telemetry/_cli_sessions.py — session rendering helpers."""
from __future__ import annotations

import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from rich.table import Table

from tests.telemetry_tests.shared_fixtures import (
    _make_agent_summary_cli,
    _make_session_summary,
)
from telemetry._cli_sessions import (
    _LABEL_SESSION_ID,
    _build_sessions_table,
    _fmt_duration,
    _fmt_tokens,
    _session_to_dict,
    _sessions_json_payload,
    _truncate_id,
)
from telemetry.models import SessionSummary


# ---------------------------------------------------------------------------
# _truncate_id
# ---------------------------------------------------------------------------

class TestTruncateId(unittest.TestCase):
    def test_short_id_not_truncated(self):
        result = _truncate_id("abc")
        self.assertEqual(result, "abc")

    def test_long_id_truncated(self):
        long_id = "a" * 30
        result = _truncate_id(long_id)
        self.assertLessEqual(len(result), 17)  # 16 + ellipsis char
        self.assertIn("…", result)

    def test_exactly_16_chars_not_truncated(self):
        result = _truncate_id("a" * 16)
        self.assertEqual(result, "a" * 16)


# ---------------------------------------------------------------------------
# _fmt_duration
# ---------------------------------------------------------------------------

class TestFmtDuration(unittest.TestCase):
    def test_returns_dash_for_non_session(self):
        result = _fmt_duration("not a session")
        self.assertEqual(result, "—")

    def test_returns_dash_when_no_start_time(self):
        s = _make_session_summary()
        s.start_time = None
        result = _fmt_duration(s)
        self.assertEqual(result, "—")

    def test_returns_dash_when_no_end_time(self):
        s = _make_session_summary()
        s.end_time = None
        result = _fmt_duration(s)
        self.assertEqual(result, "—")

    def test_formats_minutes_under_one_hour(self):
        s = _make_session_summary(start="2026-04-16T10:00:00Z", end="2026-04-16T10:30:00Z")
        result = _fmt_duration(s)
        self.assertEqual(result, "30m")

    def test_formats_hours_and_minutes(self):
        start = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 16, 12, 34, 0, tzinfo=timezone.utc)
        s = _make_session_summary()
        s.start_time = start
        s.end_time = end
        result = _fmt_duration(s)
        self.assertEqual(result, "2h34m")

    def test_zero_minutes_shown_as_0m(self):
        start = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
        s = _make_session_summary()
        s.start_time = start
        s.end_time = end
        result = _fmt_duration(s)
        self.assertEqual(result, "0m")


# ---------------------------------------------------------------------------
# _fmt_tokens
# ---------------------------------------------------------------------------

class TestFmtTokens(unittest.TestCase):
    def test_small_number_no_suffix(self):
        self.assertEqual(_fmt_tokens(999), "999")

    def test_thousands_formatted_with_k(self):
        self.assertEqual(_fmt_tokens(1000), "1K")
        self.assertEqual(_fmt_tokens(5500), "6K")

    def test_millions_formatted_with_m(self):
        self.assertEqual(_fmt_tokens(1_000_000), "1.0M")
        self.assertEqual(_fmt_tokens(2_500_000), "2.5M")

    def test_zero_is_zero(self):
        self.assertEqual(_fmt_tokens(0), "0")


# ---------------------------------------------------------------------------
# _session_to_dict
# ---------------------------------------------------------------------------

class TestSessionToDict(unittest.TestCase):
    def test_returns_empty_for_non_session(self):
        result = _session_to_dict("not a session")
        self.assertEqual(result, {})

    def test_returns_empty_for_none(self):
        result = _session_to_dict(None)
        self.assertEqual(result, {})

    def test_serializes_session_summary(self):
        s = _make_session_summary()
        result = _session_to_dict(s)
        self.assertEqual(result["session_id"], s.session_id)
        self.assertAlmostEqual(result["total_cost"], s.total_cost, places=6)
        self.assertEqual(result["total_events"], s.total_events)

    def test_duration_minutes_computed(self):
        s = _make_session_summary(start="2026-04-16T10:00:00Z", end="2026-04-16T10:30:00Z")
        result = _session_to_dict(s)
        self.assertAlmostEqual(result["duration_minutes"], 30.0, places=1)

    def test_no_end_time_duration_none(self):
        s = _make_session_summary()
        s.end_time = None
        result = _session_to_dict(s)
        self.assertIsNone(result["duration_minutes"])

    def test_no_start_time_start_none(self):
        s = _make_session_summary()
        s.start_time = None
        result = _session_to_dict(s)
        self.assertIsNone(result["start_time"])

    def test_agents_list_serialized(self):
        agent = _make_agent_summary_cli()
        s = _make_session_summary(agents=[agent])
        result = _session_to_dict(s)
        self.assertEqual(result["num_agents"], 1)
        self.assertEqual(len(result["agents"]), 1)
        agent_dict = result["agents"][0]
        for key in ("agent_id", "agent_type", "description", "model",
                    "duration_ms", "total_tokens", "total_tool_uses", "cost_usd"):
            self.assertIn(key, agent_dict)

    def test_empty_agents_list(self):
        s = _make_session_summary(agents=[])
        result = _session_to_dict(s)
        self.assertEqual(result["num_agents"], 0)
        self.assertEqual(result["agents"], [])

    def test_all_fields_present(self):
        s = _make_session_summary()
        result = _session_to_dict(s)
        expected_keys = [
            "session_id", "project_path", "start_time", "end_time",
            "duration_minutes", "model", "total_cost", "total_events",
            "input_tokens", "output_tokens", "cache_read_tokens",
            "cache_creation_tokens", "efficiency_score", "num_agents", "agents",
        ]
        for key in expected_keys:
            self.assertIn(key, result)


# ---------------------------------------------------------------------------
# _sessions_json_payload
# ---------------------------------------------------------------------------

class TestSessionsJsonPayload(unittest.TestCase):
    def test_empty_sessions_returns_zeros(self):
        payload = _sessions_json_payload([])
        self.assertEqual(payload["session_count"], 0)
        self.assertAlmostEqual(payload["total_cost"], 0.0, places=6)
        self.assertEqual(payload["sessions"], [])
        self.assertEqual(payload["source"], "transcript")

    def test_sums_total_cost(self):
        s1 = _make_session_summary(total_cost=0.10)
        s2 = _make_session_summary(session_id="s2", total_cost=0.05)
        payload = _sessions_json_payload([s1, s2])
        self.assertAlmostEqual(payload["total_cost"], 0.15, places=5)

    def test_session_count_matches(self):
        sessions = [
            _make_session_summary(session_id=f"s{i}") for i in range(5)
        ]
        payload = _sessions_json_payload(sessions)
        self.assertEqual(payload["session_count"], 5)
        self.assertEqual(len(payload["sessions"]), 5)

    def test_source_is_transcript(self):
        payload = _sessions_json_payload([])
        self.assertEqual(payload["source"], "transcript")


# ---------------------------------------------------------------------------
# _build_sessions_table
# ---------------------------------------------------------------------------

class TestBuildSessionsTable(unittest.TestCase):
    def test_returns_rich_table(self):
        s = _make_session_summary()
        table = _build_sessions_table([s], "7d")
        self.assertIsInstance(table, Table)

    def test_title_includes_since_label(self):
        s = _make_session_summary()
        table = _build_sessions_table([s], "30d")
        self.assertIn("30d", str(table.title))

    def test_session_id_column_header(self):
        table = _build_sessions_table([], "7d")
        col_headers = [c.header for c in table.columns]
        self.assertIn(_LABEL_SESSION_ID, col_headers)

    def test_project_path_two_parts(self):
        s = _make_session_summary(project_path="/home/user/myproject")
        table = _build_sessions_table([s], "7d")
        self.assertIsInstance(table, Table)

    def test_project_path_single_part(self):
        s = _make_session_summary(project_path="/single")
        table = _build_sessions_table([s], "7d")
        self.assertIsInstance(table, Table)

    def test_project_path_none(self):
        s = _make_session_summary(project_path=None)
        table = _build_sessions_table([s], "7d")
        self.assertIsInstance(table, Table)

    def test_no_start_time_shows_dash(self):
        s = _make_session_summary()
        s.start_time = None
        table = _build_sessions_table([s], "7d")
        self.assertIsInstance(table, Table)

    def test_multiple_sessions_added(self):
        sessions = [_make_session_summary(session_id=f"s{i}") for i in range(3)]
        table = _build_sessions_table(sessions, "7d")
        self.assertEqual(table.row_count, 3)

    def test_empty_sessions_table(self):
        table = _build_sessions_table([], "7d")
        self.assertEqual(table.row_count, 0)


if __name__ == "__main__":
    unittest.main()
