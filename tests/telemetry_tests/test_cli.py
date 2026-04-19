"""Tests for telemetry CLI commands."""

import tempfile
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from telemetry.cli import (
    _format_duration,
    _format_tokens,
    _print_session_detail,
    _session_cost,
    cmd_cost,
    cmd_history,
    cmd_summary,
    main,
)
from telemetry.parser import SessionStats


def _make_session(
    session_id="abc123def456",
    model="claude-sonnet-4-6",
    input_tok=1000,
    output_tok=500,
    cache_read=200,
    cache_create=50,
    events=5,
    start="2026-04-16T10:00:00Z",
    end="2026-04-16T10:30:00Z",
    tool_counts=None,
):
    s = SessionStats(session_id=session_id, path=Path(f"/fake/{session_id}.jsonl"))
    s.model = model
    s.input_tokens = input_tok
    s.output_tokens = output_tok
    s.cache_read_tokens = cache_read
    s.cache_create_tokens = cache_create
    s.events = events
    s.start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
    s.end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
    s.tool_counts = tool_counts or {}
    return s


class TestFormatDuration(unittest.TestCase):
    def test_seconds_only(self):
        self.assertEqual(_format_duration(45.0), "45s")

    def test_minutes_and_seconds(self):
        result = _format_duration(125.0)
        self.assertEqual(result, "2m05s")

    def test_hours_and_minutes(self):
        result = _format_duration(3661.0)
        self.assertIn("h", result)
        self.assertEqual(result, "1h01m")

    def test_zero_seconds(self):
        self.assertEqual(_format_duration(0.0), "0s")

    def test_exactly_one_minute(self):
        self.assertEqual(_format_duration(60.0), "1m00s")


class TestFormatTokens(unittest.TestCase):
    def test_small_number(self):
        self.assertEqual(_format_tokens(500), "500")

    def test_thousands(self):
        self.assertEqual(_format_tokens(1500), "1.5K")

    def test_millions(self):
        self.assertEqual(_format_tokens(2_500_000), "2.5M")

    def test_exactly_one_thousand(self):
        self.assertEqual(_format_tokens(1000), "1.0K")

    def test_exactly_one_million(self):
        self.assertEqual(_format_tokens(1_000_000), "1.0M")


class TestSessionCost(unittest.TestCase):
    def test_no_model_returns_zero(self):
        s = _make_session(model="")
        self.assertEqual(_session_cost(s), 0.0)

    def test_known_model_returns_nonzero(self):
        s = _make_session(model="claude-opus-4-6", input_tok=1_000_000)
        cost = _session_cost(s)
        self.assertGreater(cost, 0.0)

    def test_unknown_model_returns_zero(self):
        s = _make_session(model="future-model-xyz", input_tok=1_000_000)
        cost = _session_cost(s)
        self.assertEqual(cost, 0.0)


class TestPrintSessionDetail(unittest.TestCase):
    def test_prints_session_info(self):
        s = _make_session(
            session_id="test-session-id",
            model="claude-sonnet-4-6",
            tool_counts={"Read": 10, "Bash": 5, "Edit": 2},
        )
        buf = StringIO()
        with patch("sys.stdout", buf):
            _print_session_detail(s)
        output = buf.getvalue()
        self.assertIn("test-session-id", output)
        self.assertIn("claude-sonnet-4-6", output)
        self.assertIn("Read", output)
        self.assertIn("Bash", output)

    def test_prints_no_tools_section_when_empty(self):
        s = _make_session(tool_counts={})
        buf = StringIO()
        with patch("sys.stdout", buf):
            _print_session_detail(s)
        output = buf.getvalue()
        self.assertNotIn("Top Tools", output)

    def test_opus_model_shows_cost_breakdown(self):
        s = _make_session(model="claude-opus-4-6", input_tok=1_000_000)
        buf = StringIO()
        with patch("sys.stdout", buf):
            _print_session_detail(s)
        output = buf.getvalue()
        self.assertIn("Cost", output)
        self.assertIn("Input", output)
        self.assertIn("Output", output)

    def test_no_model_shows_question_mark_tier(self):
        s = _make_session(model="")
        s.start_time = None
        buf = StringIO()
        with patch("sys.stdout", buf):
            _print_session_detail(s)
        output = buf.getvalue()
        self.assertIn("?", output)


class TestCmdHistory(unittest.TestCase):
    def _make_args(self, days=7):
        args = MagicMock()
        args.days = days
        return args

    def test_no_sessions_prints_message_and_returns_1(self):
        with patch("telemetry.cli._load_sessions", return_value=[]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_history(self._make_args())
        self.assertEqual(rc, 1)
        self.assertIn("No sessions found", buf.getvalue())

    def test_with_sessions_returns_0(self):
        sessions = [
            _make_session(session_id="aaa111", model="claude-opus-4-6"),
            _make_session(session_id="bbb222", model="claude-sonnet-4-6"),
        ]
        with patch("telemetry.cli._load_sessions", return_value=sessions):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_history(self._make_args())
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("SESSION", output)
        self.assertIn("TOTAL", output)

    def test_long_session_id_truncated(self):
        long_id = "a" * 50
        s = _make_session(session_id=long_id)
        with patch("telemetry.cli._load_sessions", return_value=[s]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                cmd_history(self._make_args())
        output = buf.getvalue()
        self.assertIn("…", output)

    def test_session_without_start_time(self):
        s = _make_session()
        s.start_time = None
        with patch("telemetry.cli._load_sessions", return_value=[s]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_history(self._make_args())
        self.assertEqual(rc, 0)
        self.assertIn("?", buf.getvalue())

    def test_session_without_model(self):
        s = _make_session(model="")
        with patch("telemetry.cli._load_sessions", return_value=[s]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_history(self._make_args())
        self.assertEqual(rc, 0)


class TestCmdSummary(unittest.TestCase):
    def _make_args(self, session=None):
        args = MagicMock()
        args.session = session
        return args

    def test_no_sessions_no_session_arg_returns_1(self):
        with patch("telemetry.cli._find_current_session", return_value=None):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_summary(self._make_args(session=None))
        self.assertEqual(rc, 1)

    def test_current_session_found_returns_0(self):
        s = _make_session()
        with patch("telemetry.cli._find_current_session", return_value=s):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_summary(self._make_args(session=None))
        self.assertEqual(rc, 0)

    def test_session_prefix_match_returns_0(self):
        s = _make_session(session_id="abc123def456")
        with patch("telemetry.cli._load_sessions", return_value=[s]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_summary(self._make_args(session="abc123"))
        self.assertEqual(rc, 0)

    def test_session_prefix_no_match_returns_1(self):
        s = _make_session(session_id="abc123def456")
        with patch("telemetry.cli._load_sessions", return_value=[s]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_summary(self._make_args(session="zzz999"))
        self.assertEqual(rc, 1)
        self.assertIn("No session matching", buf.getvalue())


class TestCmdCost(unittest.TestCase):
    def _make_args(self, days=7):
        args = MagicMock()
        args.days = days
        return args

    def test_no_sessions_returns_1(self):
        with patch("telemetry.cli._load_sessions", return_value=[]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_cost(self._make_args())
        self.assertEqual(rc, 1)

    def test_sessions_without_model_returns_1(self):
        s = _make_session(model="")
        with patch("telemetry.cli._load_sessions", return_value=[s]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_cost(self._make_args())
        self.assertEqual(rc, 1)
        self.assertIn("No sessions with model data found", buf.getvalue())

    def test_sessions_without_start_time_skipped(self):
        s = _make_session(model="claude-opus-4-6")
        s.start_time = None
        with patch("telemetry.cli._load_sessions", return_value=[s]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_cost(self._make_args())
        self.assertEqual(rc, 1)

    def test_with_valid_sessions_returns_0(self):
        sessions = [
            _make_session(session_id="s1", model="claude-opus-4-6", input_tok=100_000),
            _make_session(session_id="s2", model="claude-sonnet-4-6", input_tok=200_000),
            _make_session(session_id="s3", model="claude-haiku-4-5", input_tok=50_000),
        ]
        with patch("telemetry.cli._load_sessions", return_value=sessions):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_cost(self._make_args())
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("Date", output)
        self.assertIn("Opus", output)
        self.assertIn("TOTAL", output)

    def test_unknown_tier_tokens_not_included(self):
        # Unknown model tier should not break, just not count in known tiers
        s = _make_session(model="future-model-xyz", input_tok=100_000)
        with patch("telemetry.cli._load_sessions", return_value=[s]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cmd_cost(self._make_args())
        self.assertEqual(rc, 0)


class TestMainEntryPoint(unittest.TestCase):
    def test_no_command_prints_help(self):
        buf = StringIO()
        with patch("sys.stdout", buf):
            rc = main([])
        self.assertEqual(rc, 0)

    def test_history_command_dispatched(self):
        with patch("telemetry.cli._load_sessions", return_value=[]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = main(["history", "--days", "3"])
        self.assertEqual(rc, 1)  # no sessions → 1

    def test_summary_command_dispatched(self):
        with patch("telemetry.cli._find_current_session", return_value=None):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = main(["summary"])
        self.assertEqual(rc, 1)

    def test_cost_command_dispatched(self):
        with patch("telemetry.cli._load_sessions", return_value=[]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = main(["cost", "--days", "14"])
        self.assertEqual(rc, 1)


class TestLoadSessions(unittest.TestCase):
    """Test _load_sessions integration with mocked iter_session_files."""

    def test_load_sessions_skips_empty_sessions(self):
        from telemetry.cli import _load_sessions
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            # Write an empty file
            empty = Path(td) / "empty.jsonl"
            empty.write_text("", encoding="utf-8")

            with patch("telemetry.cli.iter_session_files", return_value=[empty]):
                sessions = _load_sessions(days=7)
        # Empty session has 0 events; should be excluded
        self.assertEqual(len(sessions), 0)

    def test_load_sessions_returns_sorted_by_time(self):
        from telemetry.cli import _load_sessions

        s1 = _make_session(session_id="early", start="2026-04-15T10:00:00Z", end="2026-04-15T10:30:00Z")
        s2 = _make_session(session_id="late", start="2026-04-16T10:00:00Z", end="2026-04-16T10:30:00Z")

        # parse_session returns the session for each path
        path1 = Path("/fake/early.jsonl")
        path2 = Path("/fake/late.jsonl")

        with patch("telemetry.cli.iter_session_files", return_value=[path1, path2]):
            with patch("telemetry.cli.parse_session", side_effect=[s1, s2]):
                sessions = _load_sessions(days=7)

        # Sorted most-recent first
        self.assertEqual(sessions[0].session_id, "late")
        self.assertEqual(sessions[1].session_id, "early")


class TestFindCurrentSession(unittest.TestCase):
    def test_returns_none_when_no_files(self):
        from telemetry.cli import _find_current_session
        with patch("telemetry.cli.iter_session_files", return_value=[]):
            result = _find_current_session()
        self.assertIsNone(result)

    def test_returns_most_recently_modified(self):
        from telemetry.cli import _find_current_session

        s = _make_session(events=3)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.jsonl"
            path.write_text("{}", encoding="utf-8")

            with patch("telemetry.cli.iter_session_files", return_value=[path]):
                with patch("telemetry.cli.parse_session", return_value=s):
                    result = _find_current_session()

        self.assertIsNotNone(result)

    def test_returns_none_when_session_has_no_events(self):
        from telemetry.cli import _find_current_session

        empty_session = _make_session(events=0)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.jsonl"
            path.write_text("{}", encoding="utf-8")

            with patch("telemetry.cli.iter_session_files", return_value=[path]):
                with patch("telemetry.cli.parse_session", return_value=empty_session):
                    result = _find_current_session()

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
