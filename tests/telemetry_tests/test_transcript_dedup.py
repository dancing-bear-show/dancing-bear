"""Billing each Claude API call once, and pricing its cache writes by TTL tier.

Claude Code writes one assistant record per content block (thinking, text,
each tool_use), each repeating the call's ``usage``; only ``output_tokens``
climbs to its final value across those copies. A resumed session also copies
earlier records into a new file. Every aggregation must bill such a call once,
from its completed copy.
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from tests.telemetry_tests.shared_fixtures import (
    TempProjectsDirMixin,
    _write_jsonl,
    make_agent_tool_use_result,
    make_assistant_record,
    make_user_record,
)

_SINCE = datetime(2026, 4, 16, 9, 0, tzinfo=timezone.utc)
_SONNET_IN = 3.0  # claude-sonnet-4-6 $/M input
_SONNET_OUT = 15.0  # claude-sonnet-4-6 $/M output


def _snapshot(output_tokens: int, session_id: str = "sess-a", **kwargs: object) -> dict:
    """One per-content-block copy of the same billed call."""
    params: dict = {
        "session_id": session_id,
        "input_tokens": 2,
        "output_tokens": output_tokens,
        "cache_read_tokens": 7058,
        "cache_creation_tokens": 26132,
        "message_id": "msg-1",
        "request_id": "req-1",
    }
    params.update(kwargs)
    return make_assistant_record(**params)


def _expected_cost(output_tokens: int) -> float:
    return (
        2 * _SONNET_IN
        + output_tokens * _SONNET_OUT
        + 7058 * _SONNET_IN * 0.1
        + 26132 * _SONNET_IN * 1.25
    ) / 1_000_000


class _ListPriceMixin(TempProjectsDirMixin):
    """Pins the cost multiplier to 1.0 so costs are list prices."""

    def setUp(self) -> None:  # NOSONAR - required unittest lifecycle method name
        super().setUp()
        patcher = mock.patch("telemetry.pricing._cost_multiplier", return_value=1.0)
        patcher.start()
        self.addCleanup(patcher.stop)  # type: ignore[attr-defined]


class TestAssistantRecordParsing(_ListPriceMixin, unittest.TestCase):
    def _api_events(self, record: dict) -> list:
        events, _ = self.provider._parse_assistant_record(record, {}, 0)
        return [e for e in events if e.event_type == "api_request"]

    def test_event_carries_message_and_request_id(self):
        [event] = self._api_events(_snapshot(5))
        self.assertEqual((event.message_id, event.request_id), ("msg-1", "req-1"))

    def test_null_usage_is_not_billed_and_does_not_raise(self):
        record = make_assistant_record()
        record["message"]["usage"] = None
        self.assertEqual(self._api_events(record), [])

    def test_synthetic_model_is_not_billed(self):
        self.assertEqual(self._api_events(make_assistant_record(model="<synthetic>")), [])

    def test_all_zero_usage_is_not_billed(self):
        record = make_assistant_record(input_tokens=0, output_tokens=0)
        self.assertEqual(self._api_events(record), [])

    def test_dict_shaped_cache_creation_input_tokens(self):
        record = make_assistant_record(input_tokens=0, output_tokens=0)
        record["message"]["usage"]["cache_creation_input_tokens"] = {
            "ephemeral_5m_input_tokens": 300,
            "ephemeral_1h_input_tokens": 700,
        }
        [event] = self._api_events(record)
        self.assertEqual(event.cache_creation_tokens, 1000)
        self.assertEqual(event.cache_creation_1h_tokens, 700)

    def test_flat_dotted_cache_creation_keys(self):
        record = make_assistant_record(input_tokens=0, output_tokens=0)
        usage = record["message"]["usage"]
        del usage["cache_creation_input_tokens"]
        usage["cache_creation.ephemeral_5m_input_tokens"] = 40
        usage["cache_creation.ephemeral_1h_input_tokens"] = 60
        [event] = self._api_events(record)
        self.assertEqual(event.cache_creation_tokens, 100)
        self.assertEqual(event.cache_creation_1h_tokens, 60)

    def test_one_hour_cache_writes_priced_at_2x(self):
        # Scalar total plus the separate tier-split dict (current transcript shape).
        record = make_assistant_record(input_tokens=0, output_tokens=0, cache_creation_tokens=1_000_000)
        record["message"]["usage"]["cache_creation"] = {
            "ephemeral_5m_input_tokens": 0,
            "ephemeral_1h_input_tokens": 1_000_000,
        }
        [event] = self._api_events(record)
        self.assertAlmostEqual(event.cost_usd, _SONNET_IN * 2.0, places=6)

    def test_untiered_cache_writes_priced_at_1_25x(self):
        record = make_assistant_record(input_tokens=0, output_tokens=0, cache_creation_tokens=1_000_000)
        [event] = self._api_events(record)
        self.assertAlmostEqual(event.cost_usd, _SONNET_IN * 1.25, places=6)

    def test_null_subagent_usage_does_not_raise(self):
        result = make_agent_tool_use_result()
        result["usage"] = None
        record = make_user_record(tool_use_result=result)
        summary = self.provider._parse_user_record(record, {})
        self.assertIsNotNone(summary)
        self.assertEqual(summary.cost_usd, 0.0)


class TestStreamedSnapshotsInOneFile(_ListPriceMixin, unittest.TestCase):
    def _write(self, outputs: list[int]) -> None:
        _write_jsonl(self.project_dir(), "sess-a.jsonl", [_snapshot(o) for o in outputs])

    def test_parse_session_keeps_one_event_with_completed_output(self):
        self._write([3, 3, 161])
        events = self.provider.parse_session(self.project_dir() / "sess-a.jsonl")
        api = [e for e in events if e.event_type == "api_request"]
        self.assertEqual([e.output_tokens for e in api], [161])

    def test_get_sessions_bills_the_call_once(self):
        self._write([161, 3, 3])
        [summary] = self.provider.get_sessions()
        self.assertEqual(summary.input_tokens, 2)
        self.assertEqual(summary.output_tokens, 161)
        self.assertEqual(summary.cache_read_tokens, 7058)
        self.assertAlmostEqual(summary.total_cost, _expected_cost(161), places=6)

    def test_windowed_totals_bill_the_call_once(self):
        self._write([3, 3, 161])
        totals = self.provider.get_windowed_totals(_SINCE)
        self.assertEqual(totals["output_tokens"], 161)
        self.assertEqual(totals["input_tokens"], 2)
        self.assertEqual(totals["cache_read_tokens"], 7058)
        self.assertAlmostEqual(totals["cost"], _expected_cost(161), places=6)

    def test_records_without_message_id_are_never_merged(self):
        records = [make_assistant_record(output_tokens=5), make_assistant_record(output_tokens=7)]
        _write_jsonl(self.project_dir(), "sess-a.jsonl", records)
        [summary] = self.provider.get_sessions()
        self.assertEqual(summary.output_tokens, 12)


class TestCallCopiedAcrossSessions(_ListPriceMixin, unittest.TestCase):
    def test_completed_copy_wins_regardless_of_scan_order(self):
        pdir = self.project_dir()
        _write_jsonl(pdir, "sess-a.jsonl", [_snapshot(3, session_id="sess-a")])
        _write_jsonl(pdir, "sess-b.jsonl", [_snapshot(161, session_id="sess-b")])
        summaries = self.provider.get_sessions()
        self.assertEqual(sorted(s.output_tokens for s in summaries), [0, 161])
        self.assertEqual(sum(s.input_tokens for s in summaries), 2)

    def test_identical_copies_billed_once(self):
        pdir = self.project_dir()
        _write_jsonl(pdir, "sess-a.jsonl", [_snapshot(161, session_id="sess-a")])
        _write_jsonl(pdir, "sess-b.jsonl", [_snapshot(161, session_id="sess-b")])
        summaries = self.provider.get_sessions()
        self.assertAlmostEqual(sum(s.total_cost for s in summaries), _expected_cost(161), places=6)

    def test_copy_in_session_outside_window_does_not_suppress_in_window_copy(self):
        # old.jsonl has a recent mtime (passes the cheap file filter) but its
        # session started before the window, so it is not in the result. Its
        # completed copy must not make the in-window partial copy unbillable.
        pdir = self.project_dir()
        _write_jsonl(
            pdir, "old.jsonl", [_snapshot(161, session_id="old", timestamp="2020-01-01T00:00:00Z")]
        )
        _write_jsonl(pdir, "new.jsonl", [_snapshot(3, session_id="new")])
        [summary] = self.provider.get_sessions(since=_SINCE)
        self.assertEqual(summary.session_id, "new")
        self.assertEqual(summary.output_tokens, 3)

    def test_session_file_older_than_window_is_skipped(self):
        pdir = self.project_dir()
        old = _write_jsonl(
            pdir, "old.jsonl", [_snapshot(161, session_id="old", timestamp="2020-01-01T00:00:00Z")]
        )
        old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(old, (old_ts, old_ts))
        _write_jsonl(pdir, "new.jsonl", [_snapshot(3, session_id="new")])
        [summary] = self.provider.get_sessions(since=_SINCE)
        self.assertEqual(summary.output_tokens, 3)

    def test_windowed_totals_count_cross_file_copy_once(self):
        pdir = self.project_dir()
        _write_jsonl(pdir, "sess-a.jsonl", [_snapshot(3, session_id="sess-a")])
        _write_jsonl(pdir, "sess-b.jsonl", [_snapshot(161, session_id="sess-b")])
        totals = self.provider.get_windowed_totals(_SINCE)
        self.assertEqual(totals["output_tokens"], 161)
        self.assertEqual(totals["input_tokens"], 2)
        self.assertAlmostEqual(totals["cost"], _expected_cost(161), places=6)


class TestAggregateAgents(_ListPriceMixin, unittest.TestCase):
    def test_streamed_and_copied_call_counted_once(self):
        pdir = self.project_dir()
        _write_jsonl(pdir, "sess-a.jsonl", [_snapshot(3), _snapshot(161)])
        _write_jsonl(pdir, "sess-b.jsonl", [_snapshot(161, session_id="sess-b")])
        [row] = self.provider.aggregate_agents(_SINCE)
        self.assertEqual(row.calls, 1)
        self.assertEqual(row.input_tokens, 2)
        self.assertEqual(row.output_tokens, 161)
        self.assertEqual(row.cache_write_tokens, 26132)
        self.assertAlmostEqual(row.est_cost, _expected_cost(161), places=6)

    def test_synthetic_and_zero_usage_records_excluded(self):
        records = [
            make_assistant_record(model="<synthetic>", input_tokens=50),
            make_assistant_record(input_tokens=0, output_tokens=0),
        ]
        _write_jsonl(self.project_dir(), "sess-a.jsonl", records)
        self.assertEqual(self.provider.aggregate_agents(_SINCE), [])

    def test_mixed_tiered_and_untiered_writes_both_priced(self):
        tiered = make_assistant_record(
            input_tokens=0, output_tokens=0, cache_creation_tokens=1_000_000, message_id="m1"
        )
        tiered["message"]["usage"]["cache_creation"] = {"ephemeral_1h_input_tokens": 1_000_000}
        untiered = make_assistant_record(
            input_tokens=0, output_tokens=0, cache_creation_tokens=1_000_000, message_id="m2"
        )
        _write_jsonl(self.project_dir(), "sess-a.jsonl", [tiered, untiered])
        [row] = self.provider.aggregate_agents(_SINCE)
        self.assertAlmostEqual(row.est_cost, _SONNET_IN * 2.0 + _SONNET_IN * 1.25, places=6)


if __name__ == "__main__":
    unittest.main()
