"""Tests for telemetry/otel/cli/tools.py."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from telemetry.otel.cli.tools import _sort_summaries, main
from telemetry.otel.cost_models import ToolErrorSummary


def _make_summary(
    *,
    tool_name: str = "Bash",
    total_calls: int = 100,
    failures: int = 10,
    failure_rate: float = 0.1,
    avg_duration_ms: float = 200.0,
    sessions_affected: int = 5,
) -> ToolErrorSummary:
    return ToolErrorSummary(
        tool_name=tool_name,
        total_calls=total_calls,
        failures=failures,
        failure_rate=failure_rate,
        avg_duration_ms=avg_duration_ms,
        sessions_affected=sessions_affected,
    )


# ---------------------------------------------------------------------------
# _sort_summaries
# ---------------------------------------------------------------------------


class TestSortSummaries(unittest.TestCase):
    def test_sort_by_failure_rate(self):
        summaries = [
            _make_summary(tool_name="A", failure_rate=0.1, total_calls=10),
            _make_summary(tool_name="B", failure_rate=0.5, total_calls=20),
        ]
        result = _sort_summaries(summaries, "failure-rate")
        self.assertEqual(result[0].tool_name, "B")

    def test_sort_by_calls(self):
        summaries = [
            _make_summary(tool_name="A", total_calls=10),
            _make_summary(tool_name="B", total_calls=100),
        ]
        result = _sort_summaries(summaries, "calls")
        self.assertEqual(result[0].tool_name, "B")

    def test_sort_by_failures(self):
        summaries = [
            _make_summary(tool_name="A", failures=5),
            _make_summary(tool_name="B", failures=50),
        ]
        result = _sort_summaries(summaries, "failures")
        self.assertEqual(result[0].tool_name, "B")

    def test_sort_by_name(self):
        summaries = [
            _make_summary(tool_name="Zap"),
            _make_summary(tool_name="Alpha"),
        ]
        result = _sort_summaries(summaries, "name")
        self.assertEqual(result[0].tool_name, "Alpha")

    def test_default_sort_by_failure_rate_descending(self):
        summaries = [
            _make_summary(tool_name="Low", failure_rate=0.01, total_calls=5),
            _make_summary(tool_name="High", failure_rate=0.9, total_calls=20),
        ]
        result = _sort_summaries(summaries, "failure-rate")
        self.assertEqual(result[0].tool_name, "High")

    def test_empty_list(self):
        result = _sort_summaries([], "failure-rate")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestToolsMain(unittest.TestCase):
    def test_no_data_returns_0_with_no_data_message_on_stderr(self):
        with patch("telemetry.otel.cli.tools.resolve_data_dir", return_value=None):
            with patch("telemetry.otel.cli.tools.resolve_since", return_value=(None, None)):
                with patch("telemetry.otel.cli.tools.get_tool_summaries", return_value=[]):
                    buf = io.StringIO()
                    with patch("sys.stderr", buf):
                        result = main([])
        self.assertEqual(result, 0)
        self.assertIn("No tool usage data", buf.getvalue())

    def test_data_shown_in_table(self):
        summaries = [_make_summary()]
        with patch("telemetry.otel.cli.tools.resolve_data_dir", return_value=None):
            with patch("telemetry.otel.cli.tools.resolve_since", return_value=(None, None)):
                with patch("telemetry.otel.cli.tools.get_tool_summaries", return_value=summaries):
                    with patch("telemetry.otel.cli.tools.emit_rows", return_value=0) as mock_emit:
                        result = main([])
        self.assertEqual(result, 0)
        mock_emit.assert_called_once()

    def test_json_format(self):
        summaries = [_make_summary()]
        with patch("telemetry.otel.cli.tools.resolve_data_dir", return_value=None):
            with patch("telemetry.otel.cli.tools.resolve_since", return_value=(None, None)):
                with patch("telemetry.otel.cli.tools.get_tool_summaries", return_value=summaries):
                    buf = io.StringIO()
                    with patch("sys.stdout", buf):
                        result = main(["--format", "json"])
        self.assertEqual(result, 0)
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["tool_name"], "Bash")

    def test_sort_flag_name(self):
        summaries = [
            _make_summary(tool_name="Zap", failure_rate=0.2),
            _make_summary(tool_name="Alpha", failure_rate=0.1),
        ]
        with patch("telemetry.otel.cli.tools.resolve_data_dir", return_value=None):
            with patch("telemetry.otel.cli.tools.resolve_since", return_value=(None, None)):
                with patch("telemetry.otel.cli.tools.get_tool_summaries", return_value=summaries):
                    with patch("telemetry.otel.cli.tools.emit_rows", return_value=0):
                        result = main(["--sort", "name"])
        self.assertEqual(result, 0)

    def test_invalid_since_returns_error_code(self):
        with patch("telemetry.otel.cli.tools.resolve_data_dir", return_value=None):
            with patch("telemetry.otel.cli.tools.resolve_since", return_value=(None, 2)):
                result = main(["--since", "bad"])
        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
