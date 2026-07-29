"""Tests for telemetry/otel/menubar_provider.py — OtelMenubarProvider."""
from __future__ import annotations

import collections
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from telemetry.otel.menubar_dataclasses import (
    OtelDisplayData,
    OtelModels,
    OtelUsage,
    MetaStats,
    HookHealth,
    ToolActivity,
    CodeImpact,
    Skills,
    SessionPatterns,
    _unavailable,
)
from telemetry.otel.menubar_provider import OtelMenubarProvider
from telemetry.otel.reader import OTLPDataDir, EVENTS_FILE, METRICS_FILE


def _make_data_dir(tmpdir: str) -> OTLPDataDir:
    """Return an OTLPDataDir pointing at tmpdir."""
    return OTLPDataDir(path=Path(tmpdir))


def _write_events(path: Path, records: list[dict]) -> None:
    """Write records as JSONL to events file."""
    import json
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _write_metrics(path: Path, records: list[dict]) -> None:
    """Write records as JSONL to metrics file."""
    import json
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _ts_nano(secs_ago: float = 0.0) -> int:
    """Return nanosecond UTC timestamp for time.time() - secs_ago."""
    return int((time.time() - secs_ago) * 1e9)


def _make_event_record(event_type: str, attrs: dict | None = None, secs_ago: float = 60.0) -> dict:
    """Build a minimal OTLP resourceLogs record containing one log record."""
    attr_list = []
    for k, v in (attrs or {}).items():
        if isinstance(v, str):
            attr_list.append({"key": k, "value": {"stringValue": v}})
        elif isinstance(v, int):
            attr_list.append({"key": k, "value": {"intValue": v}})
        elif isinstance(v, float):
            attr_list.append({"key": k, "value": {"doubleValue": v}})
        elif isinstance(v, bool):
            attr_list.append({"key": k, "value": {"boolValue": v}})
    return {
        "resourceLogs": [{
            "scopeLogs": [{
                "logRecords": [{
                    "timeUnixNano": str(_ts_nano(secs_ago)),
                    "body": {"stringValue": event_type},
                    "attributes": attr_list,
                }]
            }]
        }]
    }


class TestGetDisplayDataMissingDir(unittest.TestCase):
    def test_missing_dir_returns_unavailable(self) -> None:
        data_dir = OTLPDataDir(path=Path("/tmp/nonexistent_otel_test_dir_12345"))
        provider = OtelMenubarProvider(data_dir=data_dir)
        result = provider.get_display_data()
        self.assertIsInstance(result, OtelDisplayData)
        self.assertFalse(result.available)


class TestGetDisplayDataMissingEventsFile(unittest.TestCase):
    def test_missing_events_file_returns_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = OtelMenubarProvider(data_dir=_make_data_dir(tmpdir))
            result = provider.get_display_data()
            self.assertFalse(result.available)


class TestGetDisplayDataEmptyEventsFile(unittest.TestCase):
    def test_empty_events_file_returns_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            (data_dir.path / EVENTS_FILE).write_text("")
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            self.assertFalse(result.available)


class TestGetDisplayDataStaleFile(unittest.TestCase):
    def test_stale_events_file_returns_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [_make_event_record("test.event")])
            # Patch time so the file appears stale
            with patch("telemetry.otel.menubar_provider.time.time", return_value=time.time() + 700):
                provider = OtelMenubarProvider(data_dir=data_dir)
                result = provider.get_display_data()
            self.assertFalse(result.available)

    def test_explicit_cutoff_bypasses_stale_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [_make_event_record("test.event")])
            provider = OtelMenubarProvider(data_dir=data_dir)
            # Pass explicit cutoff — stale check is bypassed
            result = provider.get_display_data(cutoff=time.time() - 3600)
            self.assertTrue(result.available)


class TestGetDisplayDataAvailable(unittest.TestCase):
    def test_fresh_events_file_returns_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [_make_event_record("test.event")])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            self.assertTrue(result.available)

    def test_returns_otel_display_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [_make_event_record("test.event")])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            self.assertIsInstance(result, OtelDisplayData)
            self.assertIsInstance(result.otel_usage, OtelUsage)
            self.assertIsInstance(result.meta_stats, MetaStats)
            self.assertIsInstance(result.hook_health, HookHealth)
            self.assertIsInstance(result.tool_activity, ToolActivity)
            self.assertIsInstance(result.code_impact, CodeImpact)
            self.assertIsInstance(result.skills, Skills)
            self.assertIsInstance(result.session_patterns, SessionPatterns)


class TestParseEvents(unittest.TestCase):
    def test_parses_hook_execution_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [
                _make_event_record(
                    "claude_code.hook_execution_complete",
                    {"total_duration_ms": 150.0, "num_blocking": 1, "num_non_blocking_error": 0, "hook_name": "my-hook"},
                )
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            self.assertTrue(result.available)
            hk = result.hook_health
            self.assertEqual(hk.hooks_fired_today, 1)
            self.assertEqual(hk.blocking_count, 1)

    def test_parses_skill_activated_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [
                _make_event_record("claude_code.skill_activated", {"skill.name": "pr-assistant"}),
                _make_event_record("claude_code.skill_activated", {"skill.name": "pr-assistant"}),
                _make_event_record("claude_code.skill_activated", {"skill.name": "code-review"}),
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            self.assertEqual(result.skills.skills_invoked_today, 3)
            top_skill_names = [name for name, _ in result.skills.top_skills]
            self.assertIn("pr-assistant", top_skill_names)

    def test_parses_user_prompt_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [
                _make_event_record("claude_code.user_prompt"),
                _make_event_record("claude_code.user_prompt"),
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            self.assertEqual(result.session_patterns.prompts_today, 2)

    def test_parses_tool_decision_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [
                _make_event_record("claude_code.tool_decision", {"tool_name": "Bash", "decision": "accept"}),
                _make_event_record("claude_code.tool_decision", {"tool_name": "Read", "decision": "accept"}),
                _make_event_record("claude_code.tool_decision", {"tool_name": "Edit", "decision": "reject"}),
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            ta = result.tool_activity
            # 2 of 3 accepted = ~66.7%
            self.assertAlmostEqual(ta.accept_rate_pct, 200.0 / 3, places=0)

    def test_parses_compaction_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [
                _make_event_record("claude_code.compaction", {"pre_tokens": 1000, "post_tokens": 200}),
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            ci = result.code_impact
            self.assertEqual(ci.compaction_count, 1)
            self.assertEqual(ci.tokens_saved_by_compaction, 800)

    def test_api_request_agent_call_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [
                _make_event_record("claude_code.api_request", {"query_source": "agent:code-writer", "model": "sonnet"}),
                _make_event_record("claude_code.api_request", {"query_source": "user", "model": "sonnet"}),
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            sp = result.session_patterns
            self.assertAlmostEqual(sp.agent_call_pct, 50.0)


class TestComputeMetaStats(unittest.TestCase):
    def _provider(self) -> OtelMenubarProvider:
        return OtelMenubarProvider(data_dir=OTLPDataDir(path=Path("/tmp")))

    def test_zero_active_hours_gives_zero_cost_per_hour(self) -> None:
        usage = OtelUsage(
            cost_24h=5.0, cost_7d=0.0, input_tokens_24h=0, output_tokens_24h=0,
            cache_read_tokens_24h=0, cache_creation_tokens_24h=0, total_tokens_24h=0,
            active_hours_24h=0.0, model_cost_breakdown=[],
        )
        code_impact = CodeImpact(
            lines_added_today=0, lines_removed_today=0, top_languages=[],
            commits_today=0, compaction_count=0, tokens_saved_by_compaction=0,
        )
        provider = self._provider()
        stats = provider._compute_meta_stats(usage, code_impact)
        self.assertEqual(stats.cost_per_active_hour, 0.0)

    def test_active_hours_gives_cost_per_hour(self) -> None:
        usage = OtelUsage(
            cost_24h=4.0, cost_7d=0.0, input_tokens_24h=0, output_tokens_24h=0,
            cache_read_tokens_24h=0, cache_creation_tokens_24h=0, total_tokens_24h=0,
            active_hours_24h=2.0, model_cost_breakdown=[],
        )
        code_impact = CodeImpact(
            lines_added_today=0, lines_removed_today=0, top_languages=[],
            commits_today=0, compaction_count=0, tokens_saved_by_compaction=0,
        )
        provider = self._provider()
        stats = provider._compute_meta_stats(usage, code_impact)
        self.assertAlmostEqual(stats.cost_per_active_hour, 2.0)

    def test_cache_hit_rate_computed(self) -> None:
        usage = OtelUsage(
            cost_24h=0.0, cost_7d=0.0, input_tokens_24h=0, output_tokens_24h=0,
            cache_read_tokens_24h=800, cache_creation_tokens_24h=200, total_tokens_24h=0,
            active_hours_24h=0.0, model_cost_breakdown=[],
        )
        code_impact = CodeImpact(
            lines_added_today=0, lines_removed_today=0, top_languages=[],
            commits_today=0, compaction_count=0, tokens_saved_by_compaction=0,
        )
        provider = self._provider()
        stats = provider._compute_meta_stats(usage, code_impact)
        self.assertAlmostEqual(stats.cache_hit_rate_pct, 80.0)

    def test_zero_cache_tokens_gives_zero_hit_rate(self) -> None:
        usage = OtelUsage(
            cost_24h=0.0, cost_7d=0.0, input_tokens_24h=0, output_tokens_24h=0,
            cache_read_tokens_24h=0, cache_creation_tokens_24h=0, total_tokens_24h=0,
            active_hours_24h=0.0, model_cost_breakdown=[],
        )
        code_impact = CodeImpact(
            lines_added_today=0, lines_removed_today=0, top_languages=[],
            commits_today=0, compaction_count=0, tokens_saved_by_compaction=0,
        )
        provider = self._provider()
        stats = provider._compute_meta_stats(usage, code_impact)
        self.assertEqual(stats.cache_hit_rate_pct, 0.0)


class TestComputeOtelUsageWithMetrics(unittest.TestCase):
    """Test _compute_otel_usage via get_display_data with real metric records."""

    def _make_metrics_record(
        self, metric_name: str, value: float, attrs: dict | None = None, secs_ago: float = 60.0
    ) -> dict:
        ts_nano = int((time.time() - secs_ago) * 1e9)
        attr_list = []
        for k, v in (attrs or {}).items():
            if isinstance(v, str):
                attr_list.append({"key": k, "value": {"stringValue": v}})
            elif isinstance(v, float):
                attr_list.append({"key": k, "value": {"doubleValue": v}})
            elif isinstance(v, int):
                attr_list.append({"key": k, "value": {"intValue": v}})
        return {
            "resourceMetrics": [{
                "scopeMetrics": [{
                    "metrics": [{
                        "name": metric_name,
                        "gauge": {"dataPoints": [{"timeUnixNano": str(ts_nano), "asDouble": value, "attributes": attr_list}]},
                    }]
                }]
            }]
        }

    def test_cost_metric_accumulated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            metrics_path = data_dir.path / METRICS_FILE
            _write_events(events_path, [_make_event_record("test.event")])
            _write_metrics(metrics_path, [
                self._make_metrics_record("claude_code.cost.usage", 2.5, {"model": "sonnet"}),
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            self.assertAlmostEqual(result.otel_usage.cost_24h, 2.5)

    def test_token_metric_accumulated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            metrics_path = data_dir.path / METRICS_FILE
            _write_events(events_path, [_make_event_record("test.event")])
            _write_metrics(metrics_path, [
                self._make_metrics_record("claude_code.token.usage", 1000.0, {"type": "input"}),
                self._make_metrics_record("claude_code.token.usage", 500.0, {"type": "output"}),
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            self.assertEqual(result.otel_usage.input_tokens_24h, 1000)
            self.assertEqual(result.otel_usage.output_tokens_24h, 500)

    def test_active_time_metric_accumulated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            metrics_path = data_dir.path / METRICS_FILE
            _write_events(events_path, [_make_event_record("test.event")])
            _write_metrics(metrics_path, [
                self._make_metrics_record("claude_code.active_time.total", 7200.0),  # 2 hours
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            self.assertAlmostEqual(result.otel_usage.active_hours_24h, 2.0)

    def test_models_computed_from_cost_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            metrics_path = data_dir.path / METRICS_FILE
            _write_events(events_path, [_make_event_record("test.event")])
            _write_metrics(metrics_path, [
                self._make_metrics_record("claude_code.cost.usage", 1.0, {"model": "sonnet"}),
                self._make_metrics_record("claude_code.token.usage", 500.0, {"model": "sonnet", "type": "input"}),
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            model_names = [m for m, _, _ in result.otel_models.model_rows]
            self.assertIn("sonnet", model_names)


class TestParseEventsBodyFormats(unittest.TestCase):
    """Test that _parse_events handles both dict body and string body."""

    def test_string_body_event_type(self) -> None:
        """Events with a plain string body should still parse correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import json as _json
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            ts_nano = int(time.time() * 1e9)
            # Write a record with string body instead of dict body
            record = {
                "resourceLogs": [{
                    "scopeLogs": [{
                        "logRecords": [{
                            "timeUnixNano": str(ts_nano),
                            "body": "claude_code.user_prompt",  # string, not dict
                            "attributes": [],
                        }]
                    }]
                }]
            }
            with events_path.open("w") as fh:
                fh.write(_json.dumps(record) + "\n")
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            self.assertTrue(result.available)
            self.assertEqual(result.session_patterns.prompts_today, 1)

    def test_event_before_cutoff_excluded(self) -> None:
        """Events older than the cutoff should not be counted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            # Write a recent event (for freshness check) and an old event
            _write_events(events_path, [
                _make_event_record("claude_code.user_prompt", secs_ago=60.0),   # recent
                _make_event_record("claude_code.user_prompt", secs_ago=90000.0),  # > 24h, excluded
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data(window="24h")
            # Only the recent event should be counted
            self.assertEqual(result.session_patterns.prompts_today, 1)


class TestToolResultEvents(unittest.TestCase):
    """Test that tool_result events populate tool_activity correctly."""

    def test_tool_result_event_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [
                _make_event_record("claude_code.tool_result", {
                    "tool_name": "Read",
                    "tool_input_size_bytes": 100,
                    "tool_result_size_bytes": 2000,
                }),
                _make_event_record("claude_code.tool_result", {
                    "tool_name": "bash",
                    "success": "false",
                }),
            ])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data()
            ta = result.tool_activity
            self.assertEqual(ta.tool_calls_today, 2)
            self.assertEqual(ta.tool_error_count, 1)
            self.assertAlmostEqual(ta.bash_error_rate_pct, 100.0)


class TestWindowParameter(unittest.TestCase):
    def test_window_1h_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [_make_event_record("test.event")])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data(window="1h")
            self.assertIsInstance(result, OtelDisplayData)

    def test_unknown_window_falls_back_to_24h(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(tmpdir)
            events_path = data_dir.path / EVENTS_FILE
            _write_events(events_path, [_make_event_record("test.event")])
            provider = OtelMenubarProvider(data_dir=data_dir)
            result = provider.get_display_data(window="invalid")
            self.assertIsInstance(result, OtelDisplayData)


if __name__ == "__main__":
    unittest.main()
