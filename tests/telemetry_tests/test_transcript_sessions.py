"""Tests for TranscriptProvider session-level methods (TestSessionSummaryFromFile,
TestIterJsonlFiles, TestSessionSummaryFromOldFormat, TestGetSessions,
TestGetCurrentSessionId, TestFindSessionFile, TestGetWindowedTotals,
TestAggregateAgents, TestProviderConstructor)."""
from __future__ import annotations

import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telemetry.providers.transcript import TranscriptProvider

from tests.telemetry_tests.shared_fixtures import (
    TempProjectsDirMixin,
    _write_jsonl,
    make_assistant_record,
)


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
        path.write_text('{"type": "assistant"', encoding="utf-8")
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
        f2 = _write_jsonl(pdir, "sess-b.jsonl", [make_assistant_record()])
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
        bad_dir.mkdir()
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        rows = self.provider.aggregate_agents(since)
        self.assertEqual(rows, [])

    def test_corrupt_line_skipped(self):
        pdir = self.project_dir()
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        path = pdir / "sess-1.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            import json as _json
            f.write(_json.dumps(make_assistant_record(timestamp=ts)) + "\n")
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
