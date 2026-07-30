"""Tests for telemetry/otel/menubar_parsers.py — parsing and accumulation helpers."""
from __future__ import annotations

import collections
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from telemetry.otel.menubar_parsers import (
    _accumulate_compaction_events,
    _accumulate_cost_metric,
    _accumulate_datapoint,
    _accumulate_loc_metrics,
    _accumulate_token_metric,
    _is_event_success,
    _iter_log_records,
    _iter_metric_datapoints,
    _parse_attrs,
    _parse_nano_ts,
    _process_tool_result_event,
    _read_rotated_jsonl,
    _safe_float,
    _safe_int,
    _top_n,
    _trunc,
    _MAX_ATTR_LEN,
)


class TestSafeFloat(unittest.TestCase):
    def test_float_passthrough(self) -> None:
        self.assertEqual(_safe_float(3.14), 3.14)

    def test_int_converted(self) -> None:
        self.assertEqual(_safe_float(5), 5.0)

    def test_string_converted(self) -> None:
        self.assertEqual(_safe_float("2.5"), 2.5)

    def test_bool_returns_zero(self) -> None:
        self.assertEqual(_safe_float(True), 0.0)
        self.assertEqual(_safe_float(False), 0.0)

    def test_none_returns_zero(self) -> None:
        self.assertEqual(_safe_float(None), 0.0)

    def test_invalid_string_returns_zero(self) -> None:
        self.assertEqual(_safe_float("abc"), 0.0)


class TestSafeInt(unittest.TestCase):
    def test_int_passthrough(self) -> None:
        self.assertEqual(_safe_int(42), 42)

    def test_float_truncated(self) -> None:
        self.assertEqual(_safe_int(3.9), 3)

    def test_string_converted(self) -> None:
        self.assertEqual(_safe_int("7"), 7)

    def test_bool_returns_zero(self) -> None:
        self.assertEqual(_safe_int(True), 0)
        self.assertEqual(_safe_int(False), 0)

    def test_none_returns_zero(self) -> None:
        self.assertEqual(_safe_int(None), 0)

    def test_invalid_string_returns_zero(self) -> None:
        self.assertEqual(_safe_int("xyz"), 0)


class TestParseNanoTs(unittest.TestCase):
    def test_valid_int_string(self) -> None:
        self.assertEqual(_parse_nano_ts("1700000000000000000"), 1700000000000000000)

    def test_int_value(self) -> None:
        self.assertEqual(_parse_nano_ts(12345), 12345)

    def test_none_returns_zero(self) -> None:
        self.assertEqual(_parse_nano_ts(None), 0)

    def test_empty_string_returns_zero(self) -> None:
        self.assertEqual(_parse_nano_ts(""), 0)

    def test_non_numeric_string_returns_zero(self) -> None:
        self.assertEqual(_parse_nano_ts("abc"), 0)

    def test_zero_returns_zero(self) -> None:
        self.assertEqual(_parse_nano_ts(0), 0)


class TestTrunc(unittest.TestCase):
    def test_short_string_unchanged(self) -> None:
        self.assertEqual(_trunc("hello"), "hello")

    def test_long_string_truncated(self) -> None:
        long = "a" * 100
        result = _trunc(long)
        self.assertEqual(len(result), _MAX_ATTR_LEN)

    def test_none_returns_empty_string(self) -> None:
        self.assertEqual(_trunc(None), "")

    def test_custom_length(self) -> None:
        self.assertEqual(_trunc("abcdef", 3), "abc")

    def test_int_converted_to_str(self) -> None:
        self.assertEqual(_trunc(42), "42")


class TestTopN(unittest.TestCase):
    def test_top_3_from_dict(self) -> None:
        counts = {"a": 10, "b": 30, "c": 20, "d": 5}
        result = _top_n(counts, 3)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], ("b", 30))
        self.assertEqual(result[1], ("c", 20))
        self.assertEqual(result[2], ("a", 10))

    def test_fewer_items_than_n(self) -> None:
        counts = {"x": 5}
        result = _top_n(counts, 3)
        self.assertEqual(len(result), 1)

    def test_empty_dict(self) -> None:
        result = _top_n({}, 5)
        self.assertEqual(result, [])

    def test_n_zero_returns_empty(self) -> None:
        result = _top_n({"a": 1}, 0)
        self.assertEqual(result, [])


class TestIsEventSuccess(unittest.TestCase):
    def test_missing_success_key_returns_true(self) -> None:
        self.assertTrue(_is_event_success({}))

    def test_success_true_string(self) -> None:
        self.assertTrue(_is_event_success({"success": "true"}))

    def test_success_false_string_returns_false(self) -> None:
        self.assertFalse(_is_event_success({"success": "false"}))

    def test_success_zero_string_returns_false(self) -> None:
        self.assertFalse(_is_event_success({"success": "0"}))

    def test_success_no_string_returns_false(self) -> None:
        self.assertFalse(_is_event_success({"success": "no"}))

    def test_success_true_bool_returns_true(self) -> None:
        # bool True -> str "True" -> not in falsy set
        self.assertTrue(_is_event_success({"success": True}))


class TestParseAttrs(unittest.TestCase):
    def test_string_value(self) -> None:
        attrs = [{"key": "model", "value": {"stringValue": "claude-sonnet"}}]
        result = _parse_attrs(attrs)
        self.assertEqual(result["model"], "claude-sonnet")

    def test_int_value(self) -> None:
        attrs = [{"key": "count", "value": {"intValue": 42}}]
        result = _parse_attrs(attrs)
        self.assertEqual(result["count"], 42)

    def test_double_value(self) -> None:
        attrs = [{"key": "cost", "value": {"doubleValue": 1.23}}]
        result = _parse_attrs(attrs)
        self.assertAlmostEqual(result["cost"], 1.23)

    def test_bool_value(self) -> None:
        attrs = [{"key": "success", "value": {"boolValue": True}}]
        result = _parse_attrs(attrs)
        self.assertTrue(result["success"])

    def test_empty_value_dict_gives_none(self) -> None:
        attrs = [{"key": "unknown", "value": {}}]
        result = _parse_attrs(attrs)
        self.assertIsNone(result["unknown"])

    def test_non_dict_value_gives_none(self) -> None:
        attrs = [{"key": "bad", "value": "not-a-dict"}]
        result = _parse_attrs(attrs)
        self.assertIsNone(result["bad"])

    def test_empty_list(self) -> None:
        self.assertEqual(_parse_attrs([]), {})

    def test_multiple_attrs(self) -> None:
        attrs = [
            {"key": "model", "value": {"stringValue": "sonnet"}},
            {"key": "cost", "value": {"doubleValue": 0.5}},
        ]
        result = _parse_attrs(attrs)
        self.assertEqual(result["model"], "sonnet")
        self.assertAlmostEqual(result["cost"], 0.5)


class TestIterLogRecords(unittest.TestCase):
    def test_empty_list_yields_nothing(self) -> None:
        self.assertEqual(list(_iter_log_records([])), [])

    def test_yields_log_records(self) -> None:
        raw = [{
            "resourceLogs": [{
                "scopeLogs": [{
                    "logRecords": [{"body": "event1"}, {"body": "event2"}]
                }]
            }]
        }]
        records = list(_iter_log_records(raw))
        self.assertEqual(len(records), 2)

    def test_multiple_resource_logs(self) -> None:
        raw = [
            {"resourceLogs": [{"scopeLogs": [{"logRecords": [{"body": "a"}]}]}]},
            {"resourceLogs": [{"scopeLogs": [{"logRecords": [{"body": "b"}]}]}]},
        ]
        records = list(_iter_log_records(raw))
        self.assertEqual(len(records), 2)

    def test_missing_keys_yield_nothing(self) -> None:
        raw = [{"resourceLogs": [{"scopeLogs": [{}]}]}]
        records = list(_iter_log_records(raw))
        self.assertEqual(records, [])


class TestIterMetricDatapoints(unittest.TestCase):
    def test_yields_name_and_dp(self) -> None:
        raw = {
            "resourceMetrics": [{
                "scopeMetrics": [{
                    "metrics": [{
                        "name": "claude_code.cost.usage",
                        "gauge": {"dataPoints": [{"asDouble": 1.5}]},
                    }]
                }]
            }]
        }
        results = list(_iter_metric_datapoints(raw))
        self.assertEqual(len(results), 1)
        name, dp = results[0]
        self.assertEqual(name, "claude_code.cost.usage")
        self.assertEqual(dp["asDouble"], 1.5)

    def test_sum_data_points_used(self) -> None:
        raw = {
            "resourceMetrics": [{
                "scopeMetrics": [{
                    "metrics": [{
                        "name": "claude_code.token.usage",
                        "sum": {"dataPoints": [{"asInt": 100}]},
                    }]
                }]
            }]
        }
        results = list(_iter_metric_datapoints(raw))
        self.assertEqual(len(results), 1)

    def test_empty_raw_yields_nothing(self) -> None:
        results = list(_iter_metric_datapoints({}))
        self.assertEqual(results, [])


class TestAccumulateDatapoint(unittest.TestCase):
    def _future_ts_nano(self, secs_ahead: int = 10) -> int:
        """Return a nanosecond timestamp comfortably in the future."""
        return int((time.time() + secs_ahead) * 1e9)

    def test_recent_datapoint_appended(self) -> None:
        cutoff = time.time() - 3600  # 1 hour ago
        dp = {"timeUnixNano": self._future_ts_nano(), "asDouble": 2.5}
        out: list = []
        _accumulate_datapoint(dp, "my.metric", cutoff, out)
        self.assertEqual(len(out), 1)
        name, value, attrs = out[0]
        self.assertEqual(name, "my.metric")
        self.assertAlmostEqual(value, 2.5)

    def test_old_datapoint_skipped(self) -> None:
        cutoff = time.time() + 3600  # 1 hour in the future
        dp = {"timeUnixNano": int(time.time() * 1e9), "asDouble": 2.5}
        out: list = []
        _accumulate_datapoint(dp, "my.metric", cutoff, out)
        self.assertEqual(len(out), 0)

    def test_asint_used_when_asdouble_missing(self) -> None:
        cutoff = time.time() - 3600
        dp = {"timeUnixNano": self._future_ts_nano(), "asInt": 10}
        out: list = []
        _accumulate_datapoint(dp, "my.metric", cutoff, out)
        self.assertEqual(len(out), 1)
        _, value, _ = out[0]
        self.assertEqual(value, 10.0)

    def test_attrs_parsed(self) -> None:
        cutoff = time.time() - 3600
        dp = {
            "timeUnixNano": self._future_ts_nano(),
            "asDouble": 1.0,
            "attributes": [{"key": "model", "value": {"stringValue": "sonnet"}}],
        }
        out: list = []
        _accumulate_datapoint(dp, "my.metric", cutoff, out)
        _, _, attrs = out[0]
        self.assertEqual(attrs["model"], "sonnet")


class TestAccumulateTokenMetric(unittest.TestCase):
    def _counters(self) -> dict[str, int]:
        return {"input": 0, "output": 0, "cacheRead": 0, "cacheCreation": 0}

    def test_input_accumulated(self) -> None:
        c = self._counters()
        _accumulate_token_metric("input", 100, c)
        self.assertEqual(c["input"], 100)

    def test_output_accumulated(self) -> None:
        c = self._counters()
        _accumulate_token_metric("output", 50, c)
        self.assertEqual(c["output"], 50)

    def test_cache_read_accumulated(self) -> None:
        c = self._counters()
        _accumulate_token_metric("cacheRead", 200, c)
        self.assertEqual(c["cacheRead"], 200)

    def test_cache_creation_accumulated(self) -> None:
        c = self._counters()
        _accumulate_token_metric("cacheCreation", 75, c)
        self.assertEqual(c["cacheCreation"], 75)

    def test_unknown_type_ignored(self) -> None:
        c = self._counters()
        _accumulate_token_metric("unknown", 999, c)
        self.assertEqual(sum(c.values()), 0)

    def test_additive(self) -> None:
        c = self._counters()
        _accumulate_token_metric("input", 100, c)
        _accumulate_token_metric("input", 50, c)
        self.assertEqual(c["input"], 150)


class TestAccumulateCostMetric(unittest.TestCase):
    def test_cost_accumulated(self) -> None:
        cost_holder = [0.0]
        model_cost: dict[str, float] = collections.defaultdict(float)
        attrs = {"model": "sonnet"}
        _accumulate_cost_metric(2.5, attrs, cost_holder, model_cost)
        self.assertAlmostEqual(cost_holder[0], 2.5)

    def test_model_cost_accumulated(self) -> None:
        cost_holder = [0.0]
        model_cost: dict[str, float] = collections.defaultdict(float)
        attrs = {"model": "sonnet"}
        _accumulate_cost_metric(2.5, attrs, cost_holder, model_cost)
        self.assertAlmostEqual(model_cost["sonnet"], 2.5)

    def test_additive_across_calls(self) -> None:
        cost_holder = [0.0]
        model_cost: dict[str, float] = collections.defaultdict(float)
        attrs = {"model": "sonnet"}
        _accumulate_cost_metric(1.0, attrs, cost_holder, model_cost)
        _accumulate_cost_metric(1.5, attrs, cost_holder, model_cost)
        self.assertAlmostEqual(cost_holder[0], 2.5)

    def test_missing_model_uses_unknown(self) -> None:
        cost_holder = [0.0]
        model_cost: dict[str, float] = collections.defaultdict(float)
        _accumulate_cost_metric(1.0, {}, cost_holder, model_cost)
        self.assertIn("unknown", model_cost)


class TestAccumulateLocMetrics(unittest.TestCase):
    def _make_counters(self) -> dict:
        return {
            "lines_added": 0,
            "lines_removed": 0,
            "commits_today": 0,
            "compaction_count": 0,
            "tokens_saved": 0,
            "lang_counts": collections.defaultdict(int),
        }

    def test_lines_added(self) -> None:
        counters = self._make_counters()
        metrics = [("claude_code.lines_of_code.count", 10.0, {"type": "added"})]
        _accumulate_loc_metrics(metrics, counters)
        self.assertEqual(counters["lines_added"], 10)

    def test_lines_removed(self) -> None:
        counters = self._make_counters()
        metrics = [("claude_code.lines_of_code.count", 5.0, {"type": "removed"})]
        _accumulate_loc_metrics(metrics, counters)
        self.assertEqual(counters["lines_removed"], 5)

    def test_commit_count(self) -> None:
        counters = self._make_counters()
        metrics = [("claude_code.commit.count", 3.0, {})]
        _accumulate_loc_metrics(metrics, counters)
        self.assertEqual(counters["commits_today"], 3)

    def test_language_counts(self) -> None:
        counters = self._make_counters()
        metrics = [
            ("claude_code.code_edit_tool.decision", 5.0, {"language": "python"}),
            ("claude_code.code_edit_tool.decision", 3.0, {"language": "python"}),
        ]
        _accumulate_loc_metrics(metrics, counters)
        self.assertEqual(counters["lang_counts"]["python"], 8)

    def test_unrelated_metric_ignored(self) -> None:
        counters = self._make_counters()
        metrics = [("unrelated.metric", 99.0, {})]
        _accumulate_loc_metrics(metrics, counters)
        self.assertEqual(counters["lines_added"], 0)


class TestAccumulateCompactionEvents(unittest.TestCase):
    def _make_counters(self) -> dict:
        return {"compaction_count": 0, "tokens_saved": 0}

    def test_compaction_event_counted(self) -> None:
        counters = self._make_counters()
        events = [("claude_code.compaction", 0.0, {"pre_tokens": 1000, "post_tokens": 200})]
        _accumulate_compaction_events(events, counters)
        self.assertEqual(counters["compaction_count"], 1)

    def test_tokens_saved_computed(self) -> None:
        counters = self._make_counters()
        events = [("claude_code.compaction", 0.0, {"pre_tokens": 1000, "post_tokens": 200})]
        _accumulate_compaction_events(events, counters)
        self.assertEqual(counters["tokens_saved"], 800)

    def test_negative_savings_clamped_to_zero(self) -> None:
        counters = self._make_counters()
        events = [("claude_code.compaction", 0.0, {"pre_tokens": 100, "post_tokens": 500})]
        _accumulate_compaction_events(events, counters)
        self.assertEqual(counters["tokens_saved"], 0)

    def test_other_event_types_ignored(self) -> None:
        counters = self._make_counters()
        events = [("other_event", 0.0, {})]
        _accumulate_compaction_events(events, counters)
        self.assertEqual(counters["compaction_count"], 0)

    def test_additive_across_events(self) -> None:
        counters = self._make_counters()
        events = [
            ("claude_code.compaction", 0.0, {"pre_tokens": 500, "post_tokens": 100}),
            ("claude_code.compaction", 0.0, {"pre_tokens": 300, "post_tokens": 50}),
        ]
        _accumulate_compaction_events(events, counters)
        self.assertEqual(counters["compaction_count"], 2)
        self.assertEqual(counters["tokens_saved"], 650)


class TestProcessToolResultEvent(unittest.TestCase):
    def _make_state(self) -> dict:
        return {
            "tool_errors": 0,
            "bash_calls": 0,
            "bash_errors": 0,
            "total_input_bytes": 0.0,
            "total_output_bytes": 0.0,
        }

    def test_success_event_no_error_count(self) -> None:
        state = self._make_state()
        _process_tool_result_event({"tool_name": "Read", "success": "true"}, state)
        self.assertEqual(state["tool_errors"], 0)

    def test_failure_event_increments_errors(self) -> None:
        state = self._make_state()
        _process_tool_result_event({"tool_name": "Bash", "success": "false"}, state)
        self.assertEqual(state["tool_errors"], 1)

    def test_bash_tool_tracked(self) -> None:
        state = self._make_state()
        _process_tool_result_event({"tool_name": "bash", "success": "true"}, state)
        self.assertEqual(state["bash_calls"], 1)

    def test_bash_error_tracked(self) -> None:
        state = self._make_state()
        _process_tool_result_event({"tool_name": "bash", "success": "false"}, state)
        self.assertEqual(state["bash_calls"], 1)
        self.assertEqual(state["bash_errors"], 1)

    def test_byte_sizes_accumulated(self) -> None:
        state = self._make_state()
        _process_tool_result_event({
            "tool_name": "Read",
            "tool_input_size_bytes": 500,
            "tool_result_size_bytes": 1500,
        }, state)
        self.assertEqual(state["total_input_bytes"], 500.0)
        self.assertEqual(state["total_output_bytes"], 1500.0)


class TestReadRotatedJsonl(unittest.TestCase):
    def test_missing_base_path_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "nonexistent.jsonl"
            cutoff = time.time() - 3600
            # find_rotated_files on a missing file should yield nothing gracefully
            result = _read_rotated_jsonl(base, cutoff)
            self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
