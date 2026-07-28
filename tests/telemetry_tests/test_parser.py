"""Tests for telemetry parser and pricing."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from telemetry.parser import iter_session_files, parse_session, _parse_ts
from telemetry.pricing import compute_cost, model_tier


class TestParseTs(unittest.TestCase):
    def test_trailing_z(self):
        dt = _parse_ts("2026-04-16T14:23:01.000Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 14)
        self.assertIsNotNone(dt.tzinfo)

    def test_offset_normalized_to_utc(self):
        dt = _parse_ts("2026-04-16T14:23:01+05:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.utcoffset().total_seconds(), 0)  # converted to UTC
        self.assertEqual(dt.hour, 9)  # 14:23 +05:00 = 09:23 UTC

    def test_naive_gets_utc(self):
        dt = _parse_ts("2026-04-16T14:23:01")
        self.assertIsNotNone(dt)
        self.assertIsNotNone(dt.tzinfo)

    def test_invalid_returns_none(self):
        self.assertIsNone(_parse_ts("not-a-date"))
        self.assertIsNone(_parse_ts(""))


class TestParseSession(unittest.TestCase):
    def _write_jsonl(self, records):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "test-session.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
        return path

    def test_assistant_usage(self):
        path = self._write_jsonl([
            {
                "type": "assistant",
                "timestamp": "2026-04-16T10:00:00Z",
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 200,
                        "cache_creation_input_tokens": 30,
                    },
                    "content": [
                        {"type": "tool_use", "name": "Read", "id": "t1", "input": {}},
                        {"type": "tool_use", "name": "Read", "id": "t2", "input": {}},
                        {"type": "tool_use", "name": "Bash", "id": "t3", "input": {}},
                    ],
                },
            }
        ])
        stats = parse_session(path)
        self.assertEqual(stats.events, 1)
        self.assertEqual(stats.model, "claude-opus-4-6")
        self.assertEqual(stats.input_tokens, 100)
        self.assertEqual(stats.output_tokens, 50)
        self.assertEqual(stats.cache_read_tokens, 200)
        self.assertEqual(stats.cache_create_tokens, 30)
        self.assertEqual(stats.tool_counts["Read"], 2)
        self.assertEqual(stats.tool_counts["Bash"], 1)

    def test_subagent_usage_accumulated(self):
        path = self._write_jsonl([
            {
                "type": "assistant",
                "timestamp": "2026-04-16T10:00:00Z",
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                    "content": [],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-04-16T10:01:00Z",
                "message": {"content": []},
                "toolUseResult": {
                    "usage": {"input_tokens": 200, "output_tokens": 80},
                },
            },
        ])
        stats = parse_session(path)
        self.assertEqual(stats.input_tokens, 300)
        self.assertEqual(stats.output_tokens, 130)

    def test_corrupt_line_skipped(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "corrupt.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"type":"assistant","timestamp":"2026-04-16T10:00:00Z",'
                    '"message":{"model":"claude-opus-4-6","usage":{"input_tokens":10,"output_tokens":5},"content":[]}}\n')
            f.write("NOT VALID JSON\n")
            f.write('{"type":"assistant","timestamp":"2026-04-16T10:01:00Z",'
                    '"message":{"model":"claude-opus-4-6","usage":{"input_tokens":20,"output_tokens":10},"content":[]}}\n')
        stats = parse_session(path)
        self.assertEqual(stats.events, 2)
        self.assertEqual(stats.input_tokens, 30)

    def test_missing_model(self):
        path = self._write_jsonl([
            {
                "type": "assistant",
                "timestamp": "2026-04-16T10:00:00Z",
                "message": {
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "content": [],
                },
            },
        ])
        stats = parse_session(path)
        self.assertEqual(stats.model, "")
        self.assertEqual(stats.events, 1)

    def test_empty_session(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        stats = parse_session(path)
        self.assertEqual(stats.events, 0)

    def test_blank_lines_skipped(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "blank.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"type":"assistant","timestamp":"2026-04-16T10:00:00Z",'
                    '"message":{"model":"m","usage":{"input_tokens":10,"output_tokens":5},"content":[]}}\n')
            f.write("\n")
            f.write("   \n")
            f.write('{"type":"assistant","timestamp":"2026-04-16T10:01:00Z",'
                    '"message":{"model":"m","usage":{"input_tokens":20,"output_tokens":10},"content":[]}}\n')
        stats = parse_session(path)
        self.assertEqual(stats.events, 2)
        self.assertEqual(stats.input_tokens, 30)

    def test_time_range(self):
        path = self._write_jsonl([
            {"type": "assistant", "timestamp": "2026-04-16T10:00:00Z",
             "message": {"model": "m", "usage": {}, "content": []}},
            {"type": "assistant", "timestamp": "2026-04-16T10:30:00Z",
             "message": {"model": "m", "usage": {}, "content": []}},
        ])
        stats = parse_session(path)
        self.assertAlmostEqual(stats.duration_seconds, 1800.0, places=0)


class TestIterSessionFiles(unittest.TestCase):
    def test_missing_projects_dir_yields_nothing(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        missing = Path(td.name) / "does-not-exist"
        with mock.patch("telemetry.parser.PROJECTS_DIR", missing):
            self.assertEqual(list(iter_session_files()), [])

    def test_yields_recent_files_skips_old_and_non_jsonl(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        projects_dir = Path(td.name)
        proj = projects_dir / "proj-a"
        proj.mkdir()

        recent = proj / "recent.jsonl"
        recent.write_text("{}\n", encoding="utf-8")

        old = proj / "old.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(days=30)).timestamp()
        os.utime(old, (old_ts, old_ts))

        not_jsonl = proj / "notes.txt"
        not_jsonl.write_text("ignore me", encoding="utf-8")

        stray_file = projects_dir / "not-a-project.txt"
        stray_file.write_text("ignore me too", encoding="utf-8")

        with mock.patch("telemetry.parser.PROJECTS_DIR", projects_dir):
            found = list(iter_session_files(days=7))

        self.assertEqual(found, [recent])


class TestPricing(unittest.TestCase):
    def test_model_tier_detection(self):
        self.assertEqual(model_tier("claude-opus-4-6"), "opus")
        self.assertEqual(model_tier("claude-sonnet-4-6"), "sonnet")
        self.assertEqual(model_tier("claude-haiku-4-5-20251001"), "haiku")
        self.assertEqual(model_tier("unknown-model"), "unknown")

    def test_compute_cost(self):
        # Opus pricing: $5/M input, $25/M output (Apr 2026 rates)
        cost = compute_cost(1_000_000, 0, 0, 0, "claude-opus-4-6")
        self.assertAlmostEqual(cost, 5.0, places=2)

        cost = compute_cost(0, 1_000_000, 0, 0, "claude-opus-4-6")
        self.assertAlmostEqual(cost, 25.0, places=2)

    def test_zero_tokens(self):
        cost = compute_cost(0, 0, 0, 0, "claude-opus-4-6")
        self.assertEqual(cost, 0.0)

    def test_unknown_model_falls_back_to_haiku(self):
        # Unknown models fall back to haiku ($1/M input) — not zero
        cost = compute_cost(1_000_000, 0, 0, 0, "unknown-model-xyz")
        self.assertGreater(cost, 0.0)


if __name__ == "__main__":
    unittest.main()
