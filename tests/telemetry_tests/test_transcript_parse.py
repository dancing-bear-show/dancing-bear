"""Tests for TranscriptProvider parsing methods (TestParseAssistantRecord,
TestParseUserRecord, TestComputeTokenCost, TestParseSessionWithAgents)."""
from __future__ import annotations

import json
import unittest
from datetime import datetime

from telemetry.providers.transcript import TranscriptProvider

from tests.telemetry_tests.shared_fixtures import (
    TempProjectsDirMixin,
    _write_jsonl,
    make_agent_tool_use_result,
    make_assistant_record,
    make_tool_use_block,
    make_user_record,
)


class TestParseAssistantRecord(TempProjectsDirMixin, unittest.TestCase):
    def test_usage_produces_api_request_event(self):
        record = make_assistant_record(input_tokens=100, output_tokens=50)
        events, seq = self.provider._parse_assistant_record(record, {}, 0)
        api_events = [e for e in events if e.event_type == "api_request"]
        self.assertEqual(len(api_events), 1)
        self.assertEqual(api_events[0].input_tokens, 100)
        self.assertEqual(api_events[0].output_tokens, 50)
        self.assertEqual(seq, 1)

    def test_no_usage_produces_no_api_request_event(self):
        record = make_assistant_record(include_usage=False)
        events, seq = self.provider._parse_assistant_record(record, {}, 0)
        api_events = [e for e in events if e.event_type == "api_request"]
        self.assertEqual(len(api_events), 0)
        self.assertEqual(seq, 0)

    def test_tool_use_blocks_produce_tool_events(self):
        record = make_assistant_record(
            tool_blocks=[
                make_tool_use_block("Read", "t1"),
                make_tool_use_block("Bash", "t2"),
            ]
        )
        events, seq = self.provider._parse_assistant_record(record, {}, 0)
        tool_events = [e for e in events if e.event_type == "tool_use"]
        self.assertEqual(len(tool_events), 2)
        self.assertEqual(tool_events[0].tool_name, "Read")
        self.assertEqual(tool_events[1].tool_name, "Bash")
        self.assertEqual(seq, 3)

    def test_cost_split_evenly_across_multiple_tool_blocks(self):
        record = make_assistant_record(
            input_tokens=1_000_000,
            output_tokens=0,
            tool_blocks=[
                make_tool_use_block("Read", "t1"),
                make_tool_use_block("Bash", "t2"),
            ],
        )
        events, _ = self.provider._parse_assistant_record(record, {}, 0)
        api_event = next(e for e in events if e.event_type == "api_request")
        tool_events = [e for e in events if e.event_type == "tool_use"]
        total_tool_cost = sum(e.cost_usd for e in tool_events)
        self.assertAlmostEqual(total_tool_cost, api_event.cost_usd, places=6)
        self.assertAlmostEqual(tool_events[0].cost_usd, tool_events[1].cost_usd, places=6)
        for e in tool_events:
            self.assertTrue(e.cost_is_estimated)

    def test_no_tool_blocks_zero_per_tool_cost(self):
        record = make_assistant_record(tool_blocks=[])
        events, _ = self.provider._parse_assistant_record(record, {}, 0)
        tool_events = [e for e in events if e.event_type == "tool_use"]
        self.assertEqual(tool_events, [])

    def test_agent_tool_name_tracked_in_agent_tool_inputs(self):
        record = make_assistant_record(
            tool_blocks=[
                make_tool_use_block(
                    "Agent", "t1", {"description": "do a thing", "model": "claude-opus-4-6"}
                )
            ]
        )
        agent_tool_inputs: dict[str, dict] = {}
        self.provider._parse_assistant_record(record, agent_tool_inputs, 0)
        self.assertIn("t1", agent_tool_inputs)
        self.assertEqual(agent_tool_inputs["t1"]["description"], "do a thing")

    def test_non_agent_tool_not_tracked(self):
        record = make_assistant_record(tool_blocks=[make_tool_use_block("Read", "t1")])
        agent_tool_inputs: dict[str, dict] = {}
        self.provider._parse_assistant_record(record, agent_tool_inputs, 0)
        self.assertEqual(agent_tool_inputs, {})

    def test_sequence_continues_from_input(self):
        record = make_assistant_record(tool_blocks=[make_tool_use_block("Read", "t1")])
        events, seq = self.provider._parse_assistant_record(record, {}, 10)
        self.assertEqual(seq, 12)
        self.assertEqual(events[0].sequence, 11)
        self.assertEqual(events[1].sequence, 12)

    def test_missing_timestamp_falls_back_to_now(self):
        record = make_assistant_record()
        record["timestamp"] = ""
        events, _ = self.provider._parse_assistant_record(record, {}, 0)
        self.assertIsInstance(events[0].timestamp, datetime)

    def test_session_id_propagated(self):
        record = make_assistant_record(session_id="my-session")
        events, _ = self.provider._parse_assistant_record(record, {}, 0)
        self.assertEqual(events[0].session_id, "my-session")


class TestParseUserRecord(TempProjectsDirMixin, unittest.TestCase):
    def test_no_tool_use_result_returns_none(self):
        record = make_user_record(tool_use_result=None)
        result = self.provider._parse_user_record(record, {})
        self.assertIsNone(result)

    def test_tool_use_result_without_agent_id_returns_none(self):
        record = make_user_record(tool_use_result={"usage": {}})
        result = self.provider._parse_user_record(record, {})
        self.assertIsNone(result)

    def test_agent_id_present_builds_agent_summary(self):
        record = make_user_record(
            tool_use_result=make_agent_tool_use_result(agent_id="agent-42"),
        )
        result = self.provider._parse_user_record(record, {})
        self.assertIsNotNone(result)
        self.assertEqual(result.agent_id, "agent-42")
        self.assertEqual(result.agent_type, "general-purpose")
        self.assertEqual(result.total_tokens, 500)
        self.assertEqual(result.total_tool_uses, 3)
        self.assertEqual(result.duration_ms, 1000)

    def test_description_resolved_from_agent_tool_inputs(self):
        record = make_user_record(
            tool_use_result=make_agent_tool_use_result(),
            tool_use_id="t1",
        )
        agent_tool_inputs = {"t1": {"description": "scan the repo", "model": "claude-opus-4-6"}}
        result = self.provider._parse_user_record(record, agent_tool_inputs)
        self.assertEqual(result.description, "scan the repo")
        self.assertEqual(result.model, "claude-opus-4-6")

    def test_description_empty_when_tool_use_id_not_found(self):
        record = make_user_record(
            tool_use_result=make_agent_tool_use_result(),
            tool_use_id="unknown-id",
        )
        result = self.provider._parse_user_record(record, {})
        self.assertEqual(result.description, "")
        self.assertEqual(result.model, "")

    def test_description_empty_when_no_tool_result_block(self):
        record = make_user_record(
            tool_use_result=make_agent_tool_use_result(),
            tool_use_id=None,
        )
        result = self.provider._parse_user_record(record, {"t1": {"description": "x"}})
        self.assertEqual(result.description, "")

    def test_cost_computed_from_sub_usage(self):
        record = make_user_record(
            tool_use_result=make_agent_tool_use_result(
                input_tokens=1_000_000, output_tokens=0
            ),
            tool_use_id="t1",
        )
        agent_tool_inputs = {"t1": {"model": "claude-opus-4-6"}}
        result = self.provider._parse_user_record(record, agent_tool_inputs)
        self.assertAlmostEqual(result.cost_usd, 5.0, places=2)


class TestComputeTokenCost(unittest.TestCase):
    def test_delegates_to_compute_cost(self):
        cost = TranscriptProvider._compute_token_cost(
            "claude-opus-4-6", 1_000_000, 0, 0, 0
        )
        self.assertAlmostEqual(cost, 5.0, places=2)

    def test_zero_tokens_zero_cost(self):
        cost = TranscriptProvider._compute_token_cost("claude-sonnet-4-6", 0, 0, 0, 0)
        self.assertEqual(cost, 0.0)


class TestParseSessionWithAgents(TempProjectsDirMixin, unittest.TestCase):
    def test_full_session_events_and_agents(self):
        path = _write_jsonl(
            self.projects_dir,
            "session.jsonl",
            [
                make_assistant_record(
                    tool_blocks=[
                        make_tool_use_block(
                            "Agent", "t1", {"description": "explore", "model": "claude-opus-4-6"}
                        )
                    ]
                ),
                make_user_record(
                    tool_use_result=make_agent_tool_use_result(agent_id="agent-1"),
                    tool_use_id="t1",
                ),
            ],
        )
        events, agents = self.provider.parse_session_with_agents(path)
        self.assertEqual(len(events), 2)
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0].agent_id, "agent-1")
        self.assertEqual(agents[0].description, "explore")

    def test_corrupt_line_skipped(self):
        path = self.projects_dir / "corrupt.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(make_assistant_record()) + "\n")
            f.write("NOT VALID JSON\n")
            f.write(json.dumps(make_assistant_record()) + "\n")
        events, _ = self.provider.parse_session_with_agents(path)
        api_events = [e for e in events if e.event_type == "api_request"]
        self.assertEqual(len(api_events), 2)

    def test_blank_lines_skipped(self):
        path = self.projects_dir / "blank.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(make_assistant_record()) + "\n")
            f.write("\n")
            f.write("   \n")
        events, _ = self.provider.parse_session_with_agents(path)
        self.assertEqual(len(events), 1)

    def test_empty_file(self):
        path = self.projects_dir / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        events, agents = self.provider.parse_session_with_agents(path)
        self.assertEqual(events, [])
        self.assertEqual(agents, [])

    def test_unknown_record_type_ignored(self):
        path = _write_jsonl(
            self.projects_dir, "session.jsonl", [{"type": "system", "foo": "bar"}]
        )
        events, agents = self.provider.parse_session_with_agents(path)
        self.assertEqual(events, [])
        self.assertEqual(agents, [])

    def test_user_record_without_agent_id_produces_no_agent(self):
        path = _write_jsonl(
            self.projects_dir,
            "session.jsonl",
            [make_user_record(tool_use_result={"usage": {}})],
        )
        _, agents = self.provider.parse_session_with_agents(path)
        self.assertEqual(agents, [])

    def test_parse_session_returns_only_events(self):
        path = _write_jsonl(self.projects_dir, "session.jsonl", [make_assistant_record()])
        events = self.provider.parse_session(path)
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events, list)


if __name__ == "__main__":
    unittest.main()
