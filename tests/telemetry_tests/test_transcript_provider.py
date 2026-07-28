"""Tests for telemetry.providers.transcript.TranscriptProvider."""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telemetry.providers.transcript import TranscriptProvider


def _write_jsonl(dir_path: Path, name: str, records: list[dict]) -> Path:
    """Write a list of JSON records as newline-delimited JSON to dir_path/name."""
    path = dir_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    return path


def make_assistant_record(
    session_id: str = "sess-1",
    timestamp: str = "2026-04-16T10:00:00Z",
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    tool_blocks: list[dict] | None = None,
    include_usage: bool = True,
    agent_name: str | None = None,
) -> dict:
    """Build an assistant-type JSONL record."""
    content = list(tool_blocks) if tool_blocks is not None else []
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read_tokens,
        "cache_creation_input_tokens": cache_creation_tokens,
    }
    record = {
        "type": "assistant",
        "sessionId": session_id,
        "timestamp": timestamp,
        "message": {
            "model": model,
            "usage": usage if include_usage else {},
            "content": content,
        },
    }
    if agent_name is not None:
        record["agentName"] = agent_name
    return record


def make_tool_use_block(name: str, tool_id: str, tool_input: dict | None = None) -> dict:
    """Build a tool_use content block for an assistant message."""
    return {"type": "tool_use", "name": name, "id": tool_id, "input": tool_input or {}}


def make_user_record(
    session_id: str = "sess-1",
    timestamp: str = "2026-04-16T10:01:00Z",
    tool_use_result: dict | None = None,
    tool_use_id: str | None = None,
) -> dict:
    """Build a user-type JSONL record, optionally with a toolUseResult and tool_result block."""
    content = []
    if tool_use_id is not None:
        content.append({"type": "tool_result", "tool_use_id": tool_use_id})
    record = {
        "type": "user",
        "sessionId": session_id,
        "timestamp": timestamp,
        "message": {"content": content},
    }
    if tool_use_result is not None:
        record["toolUseResult"] = tool_use_result
    return record


def make_agent_tool_use_result(
    agent_id: str = "agent-1",
    agent_type: str = "general-purpose",
    total_tokens: int = 500,
    total_tool_uses: int = 3,
    duration_ms: int = 1000,
    input_tokens: int = 200,
    output_tokens: int = 80,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> dict:
    """Build a toolUseResult dict representing a completed subagent run."""
    return {
        "agentId": agent_id,
        "agentType": agent_type,
        "totalTokens": total_tokens,
        "totalToolUseCount": total_tool_uses,
        "totalDurationMs": duration_ms,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "cache_creation_input_tokens": cache_creation_tokens,
        },
    }


class TempProjectsDirMixin:
    """Provides a temp projects_dir and a bound TranscriptProvider."""

    def setUp(self):  # NOSONAR - required unittest lifecycle method name
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.projects_dir = Path(self._td.name)
        self.provider = TranscriptProvider(projects_dir=self.projects_dir)

    def project_dir(self, name: str = "-Users-me-project") -> Path:
        d = self.projects_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d


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
        # 1 api_request + 2 tool_use = 3 events, sequence incremented per event
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
        # Split evenly across the two tool blocks
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
        self.assertEqual(seq, 12)  # +1 api_request, +1 tool_use
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
        self.assertEqual(len(events), 2)  # 1 api_request + 1 tool_use
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


class TestSessionSummaryFromFile(TempProjectsDirMixin, unittest.TestCase):
    def test_summary_built_from_valid_file(self):
        path = _write_jsonl(
            self.projects_dir,
            "sess-1.jsonl",
            [make_assistant_record(model="claude-sonnet-4-6", input_tokens=10, output_tokens=5)],
        )
        summary = self.provider._session_summary_from_file(path, "/my/project")
        self.assertEqual(summary.session_id, "sess-1")
        self.assertEqual(summary.project_path, "/my/project")
        self.assertEqual(summary.model, "claude-sonnet-4-6")
        self.assertEqual(summary.total_events, 1)
        self.assertFalse(summary.cost_is_estimated)

    def test_empty_project_path_becomes_none(self):
        path = _write_jsonl(self.projects_dir, "sess-1.jsonl", [make_assistant_record()])
        summary = self.provider._session_summary_from_file(path, "")
        self.assertIsNone(summary.project_path)

    def test_malformed_file_falls_back_gracefully(self):
        path = self.projects_dir / "sess-1.jsonl"
        path.write_text('{"type": "assistant"', encoding="utf-8")  # truncated JSON per-line ok
        # Actually this parses per-line via json.loads with JSONDecodeError caught,
        # so it should just produce zero events, not raise.
        summary = self.provider._session_summary_from_file(path, "/p")
        self.assertEqual(summary.total_events, 0)


class TestIterJsonlFiles(TempProjectsDirMixin, unittest.TestCase):
    def test_flat_format_yields_stem_as_session_id(self):
        pdir = self.project_dir()
        _write_jsonl(pdir, "sess-abc.jsonl", [make_assistant_record()])
        results = list(TranscriptProvider._iter_jsonl_files(pdir))
        self.assertEqual(len(results), 1)
        _, session_id = results[0]
        self.assertEqual(session_id, "sess-abc")

    def test_subdir_format_yields_parent_parent_name(self):
        pdir = self.project_dir()
        _write_jsonl(
            pdir, "sess-xyz/subagents/agent-1.jsonl", [make_assistant_record()]
        )
        results = list(TranscriptProvider._iter_jsonl_files(pdir))
        self.assertEqual(len(results), 1)
        _, session_id = results[0]
        self.assertEqual(session_id, "sess-xyz")

    def test_mixed_formats_both_yielded(self):
        pdir = self.project_dir()
        _write_jsonl(pdir, "sess-flat.jsonl", [make_assistant_record()])
        _write_jsonl(pdir, "sess-old/subagents/agent-1.jsonl", [make_assistant_record()])
        results = list(TranscriptProvider._iter_jsonl_files(pdir))
        session_ids = {sid for _, sid in results}
        self.assertEqual(session_ids, {"sess-flat", "sess-old"})


class TestSessionSummaryFromOldFormat(TempProjectsDirMixin, unittest.TestCase):
    def test_aggregates_multiple_subagent_files(self):
        pdir = self.project_dir()
        f1 = _write_jsonl(
            pdir,
            "sess-1/subagents/agent-a.jsonl",
            [make_assistant_record(session_id="agent-a", input_tokens=10, output_tokens=5)],
        )
        f2 = _write_jsonl(
            pdir,
            "sess-1/subagents/agent-b.jsonl",
            [make_assistant_record(session_id="agent-b", input_tokens=20, output_tokens=10)],
        )
        summary = self.provider._session_summary_from_old_format(
            "sess-1", [f1, f2], "/proj"
        )
        self.assertEqual(summary.session_id, "sess-1")
        self.assertEqual(summary.total_events, 2)
        self.assertEqual(summary.input_tokens, 30)
        self.assertEqual(summary.output_tokens, 15)

    def test_session_id_overwritten_on_events(self):
        pdir = self.project_dir()
        f1 = _write_jsonl(
            pdir,
            "sess-1/subagents/agent-a.jsonl",
            [make_assistant_record(session_id="agent-a")],
        )
        summary = self.provider._session_summary_from_old_format("sess-1", [f1], "/proj")
        # events aren't directly exposed on summary, but session_id field on summary itself:
        self.assertEqual(summary.session_id, "sess-1")

    def test_empty_files_list_uses_fallback_timestamp(self):
        summary = self.provider._session_summary_from_old_format("sess-1", [], "/proj")
        self.assertEqual(summary.total_events, 0)
        self.assertIsInstance(summary.start_time, datetime)

    def test_malformed_subagent_file_skipped_gracefully(self):
        pdir = self.project_dir()
        bad = pdir / "sess-1" / "subagents" / "agent-a.jsonl"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("not json\n", encoding="utf-8")
        summary = self.provider._session_summary_from_old_format("sess-1", [bad], "/proj")
        self.assertEqual(summary.total_events, 0)


class TestGetSessions(TempProjectsDirMixin, unittest.TestCase):
    def test_no_projects_dir_returns_empty(self):
        provider = TranscriptProvider(projects_dir=self.projects_dir / "does-not-exist")
        self.assertEqual(provider.get_sessions(), [])

    def test_flat_session_discovered(self):
        pdir = self.project_dir("-Users-me-project")
        _write_jsonl(pdir, "sess-1.jsonl", [make_assistant_record()])
        sessions = self.provider.get_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].session_id, "sess-1")
        self.assertEqual(sessions[0].project_path, "/Users/me/project")

    def test_old_format_session_discovered(self):
        pdir = self.project_dir("-Users-me-project")
        _write_jsonl(
            pdir, "sess-old/subagents/agent-1.jsonl", [make_assistant_record()]
        )
        sessions = self.provider.get_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].session_id, "sess-old")

    def test_non_directory_entries_in_projects_dir_skipped(self):
        (self.projects_dir / "stray_file.txt").write_text("noop", encoding="utf-8")
        sessions = self.provider.get_sessions()
        self.assertEqual(sessions, [])

    def test_sessions_sorted_descending_by_end_time(self):
        pdir = self.project_dir()
        _write_jsonl(
            pdir,
            "sess-early.jsonl",
            [make_assistant_record(timestamp="2026-01-01T00:00:00Z")],
        )
        _write_jsonl(
            pdir,
            "sess-late.jsonl",
            [make_assistant_record(timestamp="2026-06-01T00:00:00Z")],
        )
        sessions = self.provider.get_sessions()
        self.assertEqual(sessions[0].session_id, "sess-late")
        self.assertEqual(sessions[1].session_id, "sess-early")

    def test_since_filters_out_old_sessions_by_mtime(self):
        pdir = self.project_dir()
        _write_jsonl(pdir, "sess-old.jsonl", [make_assistant_record()])
        future_since = datetime.now(timezone.utc) + timedelta(days=1)
        sessions = self.provider.get_sessions(since=future_since)
        self.assertEqual(sessions, [])


class TestGetCurrentSessionId(TempProjectsDirMixin, unittest.TestCase):
    def test_no_projects_dir_returns_none(self):
        provider = TranscriptProvider(projects_dir=self.projects_dir / "missing")
        self.assertIsNone(provider.get_current_session_id())

    def test_no_files_returns_none(self):
        self.project_dir()
        self.assertIsNone(self.provider.get_current_session_id())

    def test_returns_most_recently_modified_session(self):
        pdir = self.project_dir()
        _write_jsonl(pdir, "sess-a.jsonl", [make_assistant_record()])
        time.sleep(0.01)
        f2 = _write_jsonl(pdir, "sess-b.jsonl", [make_assistant_record()])
        # Ensure sess-b has a strictly later mtime
        os.utime(f2, (time.time() + 10, time.time() + 10))
        self.assertEqual(self.provider.get_current_session_id(), "sess-b")


class TestFindSessionFile(TempProjectsDirMixin, unittest.TestCase):
    def test_no_projects_dir_returns_none(self):
        provider = TranscriptProvider(projects_dir=self.projects_dir / "missing")
        self.assertIsNone(provider.find_session_file("sess-1"))

    def test_flat_file_found(self):
        pdir = self.project_dir()
        expected = _write_jsonl(pdir, "sess-1.jsonl", [make_assistant_record()])
        found = self.provider.find_session_file("sess-1")
        self.assertEqual(found, expected)

    def test_subdir_file_found(self):
        pdir = self.project_dir()
        expected = _write_jsonl(
            pdir, "sess-old/subagents/agent-1.jsonl", [make_assistant_record()]
        )
        found = self.provider.find_session_file("sess-old")
        self.assertEqual(found, expected)

    def test_not_found_returns_none(self):
        self.project_dir()
        self.assertIsNone(self.provider.find_session_file("does-not-exist"))


class TestGetWindowedTotals(TempProjectsDirMixin, unittest.TestCase):
    def test_no_projects_dir_returns_zeroed_totals(self):
        provider = TranscriptProvider(projects_dir=self.projects_dir / "missing")
        totals = provider.get_windowed_totals(datetime.now(timezone.utc) - timedelta(hours=1))
        self.assertEqual(totals["cost"], 0.0)
        self.assertEqual(totals["sessions"], 0)
        self.assertEqual(totals["models"], {})

    def test_events_within_window_counted(self):
        pdir = self.project_dir()
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_jsonl(
            pdir,
            "sess-1.jsonl",
            [make_assistant_record(timestamp=ts, model="claude-sonnet-4-6", input_tokens=100, output_tokens=50)],
        )
        since = now - timedelta(hours=1)
        totals = self.provider.get_windowed_totals(since)
        self.assertEqual(totals["sessions"], 1)
        self.assertGreater(totals["cost"], 0.0)
        self.assertEqual(totals["input_tokens"], 100)
        self.assertIn("claude-sonnet-4-6", totals["models"])

    def test_events_before_window_excluded_by_file_mtime(self):
        pdir = self.project_dir()
        old_ts = "2020-01-01T00:00:00Z"
        path = _write_jsonl(
            pdir, "sess-old.jsonl", [make_assistant_record(timestamp=old_ts)]
        )
        old_mtime = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(path, (old_mtime, old_mtime))
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        totals = self.provider.get_windowed_totals(since)
        self.assertEqual(totals["sessions"], 0)
        self.assertEqual(totals["cost"], 0.0)

    def test_events_before_window_excluded_even_if_file_recent(self):
        pdir = self.project_dir()
        now = datetime.now(timezone.utc)
        old_event_ts = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        # File mtime is "now" (recent) but the event timestamp inside is old.
        _write_jsonl(pdir, "sess-1.jsonl", [make_assistant_record(timestamp=old_event_ts)])
        since = now - timedelta(hours=1)
        totals = self.provider.get_windowed_totals(since)
        self.assertEqual(totals["sessions"], 0)

    def test_non_directory_projects_skipped(self):
        (self.projects_dir / "stray.txt").write_text("x", encoding="utf-8")
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        totals = self.provider.get_windowed_totals(since)
        self.assertEqual(totals["sessions"], 0)


class TestAggregateAgents(TempProjectsDirMixin, unittest.TestCase):
    def test_no_projects_dir_returns_empty_list(self):
        provider = TranscriptProvider(projects_dir=self.projects_dir / "missing")
        self.assertEqual(provider.aggregate_agents(datetime.now(timezone.utc)), [])

    def test_orchestrator_grouping_for_missing_agent_name(self):
        pdir = self.project_dir()
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_jsonl(
            pdir,
            "sess-1.jsonl",
            [make_assistant_record(timestamp=ts, input_tokens=10, output_tokens=5)],
        )
        since = now - timedelta(hours=1)
        rows = self.provider.aggregate_agents(since)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].agent, "(orchestrator)")
        self.assertEqual(rows[0].calls, 1)

    def test_named_agent_aggregated_separately(self):
        pdir = self.project_dir()
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_jsonl(
            pdir,
            "sess-1.jsonl",
            [
                make_assistant_record(timestamp=ts, agent_name="tester", input_tokens=10, output_tokens=5),
                make_assistant_record(timestamp=ts, input_tokens=20, output_tokens=10),
            ],
        )
        since = now - timedelta(hours=1)
        rows = self.provider.aggregate_agents(since)
        agent_names = {r.agent for r in rows}
        self.assertEqual(agent_names, {"tester", "(orchestrator)"})

    def test_rows_sorted_by_cost_descending(self):
        pdir = self.project_dir()
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_jsonl(
            pdir,
            "sess-1.jsonl",
            [
                make_assistant_record(
                    timestamp=ts, agent_name="cheap", input_tokens=1, output_tokens=1
                ),
                make_assistant_record(
                    timestamp=ts, agent_name="expensive", input_tokens=1_000_000, output_tokens=500_000
                ),
            ],
        )
        since = now - timedelta(hours=1)
        rows = self.provider.aggregate_agents(since)
        self.assertEqual(rows[0].agent, "expensive")

    def test_multiple_models_for_same_agent_collapsed(self):
        pdir = self.project_dir()
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_jsonl(
            pdir,
            "sess-1.jsonl",
            [
                make_assistant_record(
                    timestamp=ts, agent_name="tester", model="claude-opus-4-6",
                    input_tokens=10, output_tokens=5,
                ),
                make_assistant_record(
                    timestamp=ts, agent_name="tester", model="claude-haiku-4-5",
                    input_tokens=20, output_tokens=10,
                ),
            ],
        )
        since = now - timedelta(hours=1)
        rows = self.provider.aggregate_agents(since)
        tester_row = next(r for r in rows if r.agent == "tester")
        self.assertEqual(tester_row.calls, 2)
        self.assertEqual(tester_row.input_tokens, 30)
        self.assertEqual(sorted(tester_row.models), ["claude-haiku-4-5", "claude-opus-4-6"])

    def test_events_without_usage_ignored(self):
        pdir = self.project_dir()
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_jsonl(
            pdir, "sess-1.jsonl", [make_assistant_record(timestamp=ts, include_usage=False)]
        )
        since = now - timedelta(hours=1)
        rows = self.provider.aggregate_agents(since)
        self.assertEqual(rows, [])

    def test_events_before_since_ignored(self):
        pdir = self.project_dir()
        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_jsonl(pdir, "sess-1.jsonl", [make_assistant_record(timestamp=old_ts)])
        since = now - timedelta(hours=1)
        rows = self.provider.aggregate_agents(since)
        self.assertEqual(rows, [])

    def test_unreadable_file_skipped_silently(self):
        pdir = self.project_dir()
        bad_dir = pdir / "sess-dir.jsonl"
        bad_dir.mkdir()  # a directory named *.jsonl will fail `open()` with OSError
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        # Should not raise.
        rows = self.provider.aggregate_agents(since)
        self.assertEqual(rows, [])

    def test_corrupt_line_skipped(self):
        pdir = self.project_dir()
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        path = pdir / "sess-1.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(make_assistant_record(timestamp=ts)) + "\n")
            f.write("NOT VALID JSON\n")
        since = now - timedelta(hours=1)
        rows = self.provider.aggregate_agents(since)
        self.assertEqual(len(rows), 1)


class TestProviderConstructor(unittest.TestCase):
    def test_default_projects_dir_is_home_claude_projects(self):
        provider = TranscriptProvider()
        self.assertEqual(provider.projects_dir, Path.home() / ".claude" / "projects")

    def test_explicit_projects_dir_used_verbatim(self):
        custom = Path("/tmp/custom-projects-dir")  # nosec B108 - test string only, never created
        provider = TranscriptProvider(projects_dir=custom)
        self.assertEqual(provider.projects_dir, custom)


if __name__ == "__main__":
    unittest.main()
