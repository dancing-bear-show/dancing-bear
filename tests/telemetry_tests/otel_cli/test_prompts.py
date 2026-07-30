"""Tests for telemetry/otel/cli/prompts.py."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from telemetry.otel.cli.prompts import _format_duration_ms, _truncate, main
from telemetry.otel.cost_models import PromptMetrics


def _make_prompt_metrics(
    *,
    prompt_id: str = "prompt-001",
    session_id: str = "session-abc",
    timestamp: str | None = "2026-04-16T10:00:00Z",
    prompt_length: int = 500,
    api_calls: int = 3,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cost: float = 0.02,
    tool_calls: int = 5,
    tool_failures: int = 1,
    duration_ms: float = 5000.0,
) -> PromptMetrics:
    return PromptMetrics(
        prompt_id=prompt_id,
        session_id=session_id,
        timestamp=timestamp,
        prompt_length=prompt_length,
        api_calls=api_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
        tool_calls=tool_calls,
        tool_failures=tool_failures,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------


class TestTruncate(unittest.TestCase):
    def test_short_string_unchanged(self):
        self.assertEqual(_truncate("abc", 10), "abc")

    def test_long_string_truncated(self):
        result = _truncate("a" * 20, 10)
        self.assertTrue(result.endswith("..."))
        self.assertEqual(len(result), 10)


# ---------------------------------------------------------------------------
# _format_duration_ms
# ---------------------------------------------------------------------------


class TestFormatDurationMs(unittest.TestCase):
    def test_zero_returns_dash(self):
        self.assertEqual(_format_duration_ms(0), "-")

    def test_negative_returns_dash(self):
        self.assertEqual(_format_duration_ms(-1), "-")

    def test_milliseconds(self):
        result = _format_duration_ms(500)
        self.assertIn("ms", result)

    def test_seconds(self):
        result = _format_duration_ms(5000)
        self.assertIn("s", result)

    def test_minutes(self):
        result = _format_duration_ms(120000)
        self.assertIn("m", result)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestPromptsMain(unittest.TestCase):
    def test_no_data_returns_0(self):
        with patch("telemetry.otel.cli.prompts.get_prompt_metrics", return_value=[]):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                result = main([])
        self.assertEqual(result, 0)
        self.assertIn("No prompt metrics", buf.getvalue())

    def test_table_format_returns_0(self):
        metrics = [_make_prompt_metrics()]
        with patch("telemetry.otel.cli.prompts.get_prompt_metrics", return_value=metrics):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                result = main([])
        self.assertEqual(result, 0)

    def test_json_format_returns_0_and_valid_json(self):
        metrics = [_make_prompt_metrics()]
        with patch("telemetry.otel.cli.prompts.get_prompt_metrics", return_value=metrics):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                result = main(["--format", "json"])
        self.assertEqual(result, 0)
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["prompt_id"], "prompt-001")

    def test_limit_flag(self):
        metrics = [_make_prompt_metrics(prompt_id=f"p{i}") for i in range(10)]
        with patch("telemetry.otel.cli.prompts.get_prompt_metrics", return_value=metrics):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                result = main(["--limit", "3"])
        self.assertEqual(result, 0)

    def test_value_error_returns_1(self):
        with patch("telemetry.otel.cli.prompts.get_prompt_metrics", side_effect=ValueError("bad since")):
            buf = io.StringIO()
            with patch("sys.stderr", buf):
                result = main(["--since", "bad"])
        self.assertEqual(result, 1)
        self.assertIn("bad since", buf.getvalue())

    def test_session_id_flag_passed(self):
        with patch("telemetry.otel.cli.prompts.get_prompt_metrics", return_value=[]) as mock_get:
            main(["--session-id", "my-session"])
        call_kwargs = mock_get.call_args[1]
        self.assertEqual(call_kwargs["session_id"], "my-session")

    def test_data_dir_flag(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with patch("telemetry.otel.cli.prompts.get_prompt_metrics", return_value=[]):
                result = main(["--data-dir", td])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
