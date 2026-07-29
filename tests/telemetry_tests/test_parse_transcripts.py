"""Tests for telemetry/parse_transcripts.py."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import click
from click.testing import CliRunner

from telemetry.parse_transcripts import (
    ParseResult,
    _append_bash_command,
    _emit_rows,
    _extract_tool_preview,
    _find_jsonl_files,
    _load_json_nullable,
    _load_or_init_session_index,
    _parse_content_blocks,
    _parse_since_window,
    _process_jsonl_file,
    _process_one_file,
    _process_one_record,
    _process_tool_use_blocks,
    _process_user_role_record,
    _safe_mtime,
    _session_id_from_path,
    _token_estimate,
    parse_transcripts,
    run_parse_transcripts,
)


# ---------------------------------------------------------------------------
# _token_estimate
# ---------------------------------------------------------------------------

class TestTokenEstimate(unittest.TestCase):
    def test_divides_len_by_4(self):
        self.assertEqual(_token_estimate("abcd"), 1)

    def test_minimum_is_1(self):
        self.assertEqual(_token_estimate(""), 1)
        self.assertEqual(_token_estimate("a"), 1)

    def test_longer_text(self):
        text = "a" * 100
        self.assertEqual(_token_estimate(text), 25)


# ---------------------------------------------------------------------------
# _load_json_nullable
# ---------------------------------------------------------------------------

class TestLoadJsonNullable(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmpdir = Path(self._td.name)

    def test_returns_dict_for_valid_json(self):
        p = self.tmpdir / "valid.json"
        p.write_text(json.dumps({"key": "val"}), encoding="utf-8")
        result = _load_json_nullable(p)
        self.assertEqual(result, {"key": "val"})

    def test_returns_none_for_missing_file(self):
        result = _load_json_nullable(Path("/nonexistent/path.json"))
        self.assertIsNone(result)

    def test_returns_none_for_invalid_json(self):
        p = self.tmpdir / "bad.json"
        p.write_text("not json", encoding="utf-8")
        result = _load_json_nullable(p)
        self.assertIsNone(result)

    def test_returns_none_for_non_dict_json(self):
        p = self.tmpdir / "list.json"
        p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        result = _load_json_nullable(p)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _parse_since_window
# ---------------------------------------------------------------------------

class TestParseSinceWindow(unittest.TestCase):
    def test_all_returns_none(self):
        result = _parse_since_window("all")
        self.assertIsNone(result)

    def test_all_case_insensitive(self):
        result = _parse_since_window("ALL")
        self.assertIsNone(result)

    def test_7d_returns_datetime(self):
        result = _parse_since_window("7d")
        self.assertIsInstance(result, datetime)

    def test_30d_returns_datetime(self):
        result = _parse_since_window("30d")
        self.assertIsInstance(result, datetime)

    def test_1h_returns_datetime(self):
        result = _parse_since_window("1h")
        self.assertIsInstance(result, datetime)

    def test_bare_integer_raises_bad_parameter(self):
        with self.assertRaises(click.BadParameter):
            _parse_since_window("100")

    def test_float_prefix_raises_bad_parameter(self):
        with self.assertRaises(click.BadParameter):
            _parse_since_window("1.5d")

    def test_unknown_suffix_raises_bad_parameter(self):
        with self.assertRaises(click.BadParameter):
            _parse_since_window("7x")

    def test_empty_string_raises_bad_parameter(self):
        with self.assertRaises(click.BadParameter):
            _parse_since_window("")


# ---------------------------------------------------------------------------
# _find_jsonl_files
# ---------------------------------------------------------------------------

class TestFindJsonlFiles(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.projects_dir = Path(self._td.name)

    def _write_jsonl(self, rel_path: str, content: str = '{"type":"user"}\n') -> Path:
        p = self.projects_dir / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_returns_empty_when_dir_missing(self):
        missing = Path("/nonexistent/projects")
        result = _find_jsonl_files(missing, None)
        self.assertEqual(result, [])

    def test_finds_jsonl_files(self):
        self._write_jsonl("project-a/session1.jsonl")
        self._write_jsonl("project-b/session2.jsonl")
        result = _find_jsonl_files(self.projects_dir, None)
        self.assertEqual(len(result), 2)

    def test_ignores_non_jsonl_files(self):
        self._write_jsonl("project-a/session1.jsonl")
        (self.projects_dir / "project-a" / "readme.txt").write_text("x")
        result = _find_jsonl_files(self.projects_dir, None)
        self.assertEqual(len(result), 1)

    def test_since_future_cutoff_excludes_all_files(self):
        self._write_jsonl("project-a/session1.jsonl")
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        result = _find_jsonl_files(self.projects_dir, future)
        self.assertEqual(result, [])

    def test_since_none_returns_all(self):
        self._write_jsonl("project-a/session1.jsonl")
        result = _find_jsonl_files(self.projects_dir, None)
        self.assertEqual(len(result), 1)

    def test_empty_dir_returns_empty(self):
        result = _find_jsonl_files(self.projects_dir, None)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# _extract_tool_preview
# ---------------------------------------------------------------------------

class TestExtractToolPreview(unittest.TestCase):
    def test_dict_serialized_to_json(self):
        result = _extract_tool_preview({"command": "ls"})
        self.assertIn("command", result)
        self.assertIn("ls", result)

    def test_non_dict_converted_to_str(self):
        result = _extract_tool_preview("some string")
        self.assertEqual(result, "some string")

    def test_truncated_at_200(self):
        long_input = {"key": "x" * 300}
        result = _extract_tool_preview(long_input)
        self.assertLessEqual(len(result), 200)

    def test_empty_dict(self):
        result = _extract_tool_preview({})
        self.assertEqual(result, "{}")

    def test_none_value(self):
        result = _extract_tool_preview(None)
        self.assertEqual(result, "None")


# ---------------------------------------------------------------------------
# _append_bash_command
# ---------------------------------------------------------------------------

class TestAppendBashCommand(unittest.TestCase):
    def _make_index(self) -> dict:
        return {"bash_commands": [], "tool_calls": [], "prompts": []}

    def test_non_bash_returns_0(self):
        idx = self._make_index()
        result = _append_bash_command("Read", {"path": "file.py"}, idx)
        self.assertEqual(result, 0)
        self.assertEqual(idx["bash_commands"], [])

    def test_bash_with_command_returns_1(self):
        idx = self._make_index()
        result = _append_bash_command("Bash", {"command": "ls -la"}, idx)
        self.assertEqual(result, 1)
        self.assertEqual(idx["bash_commands"], ["ls -la"])

    def test_bash_without_command_returns_0(self):
        idx = self._make_index()
        result = _append_bash_command("Bash", {}, idx)
        self.assertEqual(result, 0)
        self.assertEqual(idx["bash_commands"], [])

    def test_bash_with_non_dict_input_returns_0(self):
        idx = self._make_index()
        result = _append_bash_command("Bash", "not a dict", idx)
        self.assertEqual(result, 0)

    def test_bash_with_empty_command_returns_0(self):
        idx = self._make_index()
        result = _append_bash_command("Bash", {"command": ""}, idx)
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# _process_tool_use_blocks
# ---------------------------------------------------------------------------

class TestProcessToolUseBlocks(unittest.TestCase):
    def _make_index(self) -> dict:
        return {"bash_commands": [], "tool_calls": [], "prompts": []}

    def test_empty_blocks_returns_0(self):
        idx = self._make_index()
        result = _process_tool_use_blocks([], idx)
        self.assertEqual(result, 0)

    def test_non_tool_use_type_skipped(self):
        idx = self._make_index()
        blocks = [{"type": "text", "text": "hello"}]
        result = _process_tool_use_blocks(blocks, idx)
        self.assertEqual(result, 0)
        self.assertEqual(idx["tool_calls"], [])

    def test_tool_use_block_added_to_tool_calls(self):
        idx = self._make_index()
        blocks = [{"type": "tool_use", "name": "Read", "input": {"path": "x.py"}}]
        _process_tool_use_blocks(blocks, idx)
        self.assertEqual(len(idx["tool_calls"]), 1)
        self.assertEqual(idx["tool_calls"][0]["name"], "Read")

    def test_bash_block_counted(self):
        idx = self._make_index()
        blocks = [{"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}}]
        result = _process_tool_use_blocks(blocks, idx)
        self.assertEqual(result, 1)
        self.assertIn("echo hi", idx["bash_commands"])

    def test_non_dict_block_skipped(self):
        idx = self._make_index()
        result = _process_tool_use_blocks(["not-a-dict"], idx)
        self.assertEqual(result, 0)
        self.assertEqual(idx["tool_calls"], [])

    def test_multiple_blocks_mixed(self):
        idx = self._make_index()
        blocks = [
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
            {"type": "text", "text": "ignore me"},
        ]
        result = _process_tool_use_blocks(blocks, idx)
        self.assertEqual(result, 1)
        self.assertEqual(len(idx["tool_calls"]), 2)

    def test_tool_use_input_preview_stored(self):
        idx = self._make_index()
        blocks = [{"type": "tool_use", "name": "Edit", "input": {"path": "main.py"}}]
        _process_tool_use_blocks(blocks, idx)
        self.assertIn("input_preview", idx["tool_calls"][0])


# ---------------------------------------------------------------------------
# _process_user_role_record
# ---------------------------------------------------------------------------

class TestProcessUserRoleRecord(unittest.TestCase):
    def _make_index(self) -> dict:
        return {"bash_commands": [], "tool_calls": [], "prompts": []}

    def test_plain_string_content_adds_prompt(self):
        idx = self._make_index()
        record = {"message": {"content": "Hello assistant"}}
        result = _process_user_role_record(record, idx, 0, 0)
        self.assertEqual(result, 1)
        self.assertEqual(len(idx["prompts"]), 1)
        self.assertEqual(idx["prompts"][0]["text"], "Hello assistant")

    def test_empty_string_content_returns_0(self):
        idx = self._make_index()
        record = {"message": {"content": "   "}}
        result = _process_user_role_record(record, idx, 0, 0)
        self.assertEqual(result, 0)
        self.assertEqual(idx["prompts"], [])

    def test_list_content_with_text_block_adds_prompt(self):
        idx = self._make_index()
        record = {"message": {"content": [{"type": "text", "text": "Hello from block"}]}}
        result = _process_user_role_record(record, idx, 0, 0)
        self.assertEqual(result, 1)
        self.assertEqual(idx["prompts"][0]["text"], "Hello from block")

    def test_list_content_with_tool_result_block_skipped(self):
        idx = self._make_index()
        record = {"message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}]}}
        result = _process_user_role_record(record, idx, 0, 0)
        self.assertEqual(result, 0)
        self.assertEqual(idx["prompts"], [])

    def test_non_dict_message_uses_record_content(self):
        idx = self._make_index()
        record = {"message": "not a dict", "content": "top-level content"}
        result = _process_user_role_record(record, idx, 0, 0)
        self.assertEqual(result, 1)

    def test_prompt_index_increments_correctly(self):
        idx = self._make_index()
        record = {"message": {"content": "First"}}
        _process_user_role_record(record, idx, 5, 0)
        self.assertEqual(idx["prompts"][0]["prompt_index"], 5)

    def test_none_content_returns_0(self):
        idx = self._make_index()
        record = {"message": {"content": None}}
        result = _process_user_role_record(record, idx, 0, 0)
        self.assertEqual(result, 0)

    def test_token_estimate_set(self):
        idx = self._make_index()
        text = "a" * 40
        record = {"message": {"content": text}}
        _process_user_role_record(record, idx, 0, 0)
        self.assertEqual(idx["prompts"][0]["token_estimate"], 10)

    def test_multiple_text_blocks_in_list(self):
        idx = self._make_index()
        record = {
            "message": {
                "content": [
                    {"type": "text", "text": "First block"},
                    {"type": "text", "text": "Second block"},
                ]
            }
        }
        result = _process_user_role_record(record, idx, 0, 0)
        self.assertEqual(result, 2)
        self.assertEqual(len(idx["prompts"]), 2)

    def test_empty_text_in_text_block_skipped(self):
        idx = self._make_index()
        record = {"message": {"content": [{"type": "text", "text": "   "}]}}
        result = _process_user_role_record(record, idx, 0, 0)
        self.assertEqual(result, 0)

    def test_non_dict_block_in_list_skipped(self):
        idx = self._make_index()
        record = {"message": {"content": ["not a dict"]}}
        result = _process_user_role_record(record, idx, 0, 0)
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# _parse_content_blocks
# ---------------------------------------------------------------------------

class TestParseContentBlocks(unittest.TestCase):
    def test_returns_list_from_msg(self):
        record = {}
        msg = {"content": [{"type": "tool_use"}]}
        result = _parse_content_blocks(record, msg)
        self.assertEqual(len(result), 1)

    def test_non_list_content_returns_empty(self):
        record = {}
        msg = {"content": "plain string"}
        result = _parse_content_blocks(record, msg)
        self.assertEqual(result, [])

    def test_empty_msg_falls_back_to_record(self):
        record = {"content": [{"type": "tool_use"}]}
        msg = {}
        result = _parse_content_blocks(record, msg)
        self.assertEqual(len(result), 1)

    def test_none_msg_uses_record_content(self):
        record = {"content": [{"type": "tool_use"}]}
        result = _parse_content_blocks(record, {})
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# _process_one_record
# ---------------------------------------------------------------------------

class TestProcessOneRecord(unittest.TestCase):
    def _make_index(self) -> dict:
        return {"bash_commands": [], "tool_calls": [], "prompts": []}

    def test_no_role_returns_zeros(self):
        idx = self._make_index()
        record = {"message": {}}
        result = _process_one_record(record, idx, 0, 0)
        self.assertEqual(result, (0, 0))

    def test_user_role_processes_prompt(self):
        idx = self._make_index()
        record = {"message": {"role": "user", "content": "Hello"}}
        p_delta, b_delta = _process_one_record(record, idx, 0, 0)
        self.assertEqual(p_delta, 1)
        self.assertEqual(b_delta, 0)

    def test_assistant_role_processes_tool_use(self):
        idx = self._make_index()
        record = {
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
            }
        }
        p_delta, b_delta = _process_one_record(record, idx, 0, 0)
        self.assertEqual(p_delta, 0)
        self.assertEqual(b_delta, 1)

    def test_non_dict_message_falls_back_to_record_role(self):
        idx = self._make_index()
        # role in top-level record, content is none
        record = {"message": "bad", "role": "user"}
        # No crash — role from fallback, content empty
        p_delta, b_delta = _process_one_record(record, idx, 0, 0)
        self.assertEqual(b_delta, 0)

    def test_both_user_prompt_and_no_tool_blocks_counted(self):
        idx = self._make_index()
        record = {
            "message": {
                "role": "user",
                "content": "write tests for me",
            }
        }
        p_delta, b_delta = _process_one_record(record, idx, 0, 0)
        self.assertEqual(p_delta, 1)
        self.assertEqual(b_delta, 0)


# ---------------------------------------------------------------------------
# _process_jsonl_file
# ---------------------------------------------------------------------------

class TestProcessJsonlFile(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.dir = Path(self._td.name)

    def _make_index(self) -> dict:
        return {
            "session_id": "s1",
            "project_path": "",
            "last_updated": "",
            "prompts": [],
            "bash_commands": [],
            "tool_calls": [],
            "prompt_count": 0,
            "bash_count": 0,
        }

    def _write_jsonl_file(self, name: str, records: list[dict]) -> Path:
        p = self.dir / name
        with open(p, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return p

    def test_empty_file_returns_zeros(self):
        p = self.dir / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        idx = self._make_index()
        prompts, bash, nbytes, offset = _process_jsonl_file(p, 0, idx, str(self.dir))
        self.assertEqual(prompts, 0)
        self.assertEqual(bash, 0)
        self.assertEqual(nbytes, 0)

    def test_user_prompt_record_extracted(self):
        p = self._write_jsonl_file("s1.jsonl", [
            {"message": {"role": "user", "content": "Hello there"}}
        ])
        idx = self._make_index()
        prompts, _, nbytes, _ = _process_jsonl_file(p, 0, idx, str(self.dir))
        self.assertEqual(prompts, 1)
        self.assertGreater(nbytes, 0)
        self.assertEqual(idx["prompts"][0]["text"], "Hello there")

    def test_bash_command_extracted(self):
        p = self._write_jsonl_file("s1.jsonl", [
            {
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}}],
                }
            }
        ])
        idx = self._make_index()
        _, bash, _, _ = _process_jsonl_file(p, 0, idx, str(self.dir))
        self.assertEqual(bash, 1)
        self.assertIn("echo hi", idx["bash_commands"])

    def test_corrupt_line_skipped(self):
        p = self.dir / "mixed.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"message": {"role": "user", "content": "valid"}}) + "\n")
            f.write("NOT JSON\n")
            f.write(json.dumps({"message": {"role": "user", "content": "also valid"}}) + "\n")
        idx = self._make_index()
        prompts, _, _, _ = _process_jsonl_file(p, 0, idx, str(self.dir))
        self.assertEqual(prompts, 2)

    def test_start_offset_at_eof_skips_processing(self):
        record = {"message": {"role": "user", "content": "Hello"}}
        p = self._write_jsonl_file("s1.jsonl", [record])
        file_size = p.stat().st_size
        idx = self._make_index()
        prompts, _, nbytes, _ = _process_jsonl_file(p, file_size, idx, str(self.dir))
        self.assertEqual(prompts, 0)
        self.assertEqual(nbytes, 0)

    def test_truncated_file_reprocessed_from_start(self):
        record = {"message": {"role": "user", "content": "Hello"}}
        p = self._write_jsonl_file("s1.jsonl", [record])
        file_size = p.stat().st_size
        idx = self._make_index()
        # Offset beyond file size triggers reset-to-zero reprocess
        prompts, _, _, _ = _process_jsonl_file(p, file_size + 1000, idx, str(self.dir))
        self.assertEqual(prompts, 1)

    def test_missing_file_returns_zeros(self):
        idx = self._make_index()
        result = _process_jsonl_file(Path("/nonexistent/file.jsonl"), 0, idx, "")
        self.assertEqual(result, (0, 0, 0, 0))

    def test_blank_lines_skipped(self):
        p = self.dir / "blanks.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n")
            f.write("   \n")
            f.write(json.dumps({"message": {"role": "user", "content": "real"}}) + "\n")
        idx = self._make_index()
        prompts, _, _, _ = _process_jsonl_file(p, 0, idx, str(self.dir))
        self.assertEqual(prompts, 1)

    def test_non_dict_record_skipped(self):
        p = self.dir / "list.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps([1, 2, 3]) + "\n")
        idx = self._make_index()
        prompts, _, nbytes, _ = _process_jsonl_file(p, 0, idx, str(self.dir))
        self.assertEqual(prompts, 0)
        self.assertGreater(nbytes, 0)

    def test_last_updated_set_after_processing(self):
        record = {"message": {"role": "user", "content": "test"}}
        p = self._write_jsonl_file("s1.jsonl", [record])
        idx = self._make_index()
        _process_jsonl_file(p, 0, idx, str(self.dir))
        self.assertNotEqual(idx["last_updated"], "")

    def test_partial_line_at_eof_not_advanced(self):
        # Write a record without trailing newline to simulate partial write
        p = self.dir / "partial.jsonl"
        with open(p, "wb") as f:
            f.write(json.dumps({"message": {"role": "user", "content": "Complete"}}).encode() + b"\n")
            f.write(b'{"partial": "no newline at eof"')
        idx = self._make_index()
        prompts, _, _, new_offset = _process_jsonl_file(p, 0, idx, str(self.dir))
        self.assertEqual(prompts, 1)
        # HWM should not have advanced past the complete line
        self.assertGreater(new_offset, 0)

    def test_project_path_set_in_index(self):
        record = {"message": {"role": "user", "content": "test"}}
        p = self._write_jsonl_file("sess.jsonl", [record])
        idx = self._make_index()
        _process_jsonl_file(p, 0, idx, "/my/project")
        self.assertEqual(idx["project_path"], "/my/project")


# ---------------------------------------------------------------------------
# _session_id_from_path
# ---------------------------------------------------------------------------

class TestSessionIdFromPath(unittest.TestCase):
    def test_stem_extracted(self):
        p = Path("/some/dir/my-session-id.jsonl")
        self.assertEqual(_session_id_from_path(p), "my-session-id")

    def test_complex_stem(self):
        p = Path("/projects/-Users-me-proj/abcdef123456.jsonl")
        self.assertEqual(_session_id_from_path(p), "abcdef123456")


# ---------------------------------------------------------------------------
# _safe_mtime
# ---------------------------------------------------------------------------

class TestSafeMtime(unittest.TestCase):
    def test_returns_mtime_for_existing_file(self):
        with tempfile.NamedTemporaryFile() as f:
            result = _safe_mtime(Path(f.name))
        self.assertGreater(result, 0.0)

    def test_returns_0_for_missing_file(self):
        result = _safe_mtime(Path("/nonexistent/file.txt"))
        self.assertEqual(result, 0.0)


# ---------------------------------------------------------------------------
# _load_or_init_session_index
# ---------------------------------------------------------------------------

class TestLoadOrInitSessionIndex(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.index_dir = Path(self._td.name)

    def test_returns_fresh_index_when_missing(self):
        idx = _load_or_init_session_index(self.index_dir, "new-session")
        self.assertEqual(idx["session_id"], "new-session")
        self.assertEqual(idx["prompts"], [])
        self.assertEqual(idx["bash_commands"], [])
        self.assertEqual(idx["tool_calls"], [])
        self.assertEqual(idx["prompt_count"], 0)
        self.assertEqual(idx["bash_count"], 0)

    def test_loads_existing_index(self):
        data = {
            "session_id": "existing",
            "project_path": "/foo",
            "last_updated": "2026-01-01",
            "prompts": [{"text": "hi"}],
            "bash_commands": ["ls"],
            "tool_calls": [],
            "prompt_count": 1,
            "bash_count": 1,
        }
        (self.index_dir / "existing.json").write_text(json.dumps(data), encoding="utf-8")
        idx = _load_or_init_session_index(self.index_dir, "existing")
        self.assertEqual(idx["session_id"], "existing")
        self.assertEqual(len(idx["prompts"]), 1)

    def test_corrupted_count_coerced_to_list_len(self):
        data = {
            "session_id": "s1",
            "project_path": "",
            "last_updated": "",
            "prompts": [{"text": "hi"}],
            "bash_commands": [],
            "tool_calls": [],
            "prompt_count": "NOT_AN_INT",
            "bash_count": "ALSO_BAD",
        }
        (self.index_dir / "s1.json").write_text(json.dumps(data), encoding="utf-8")
        idx = _load_or_init_session_index(self.index_dir, "s1")
        self.assertEqual(idx["prompt_count"], 1)
        self.assertEqual(idx["bash_count"], 0)

    def test_missing_list_fields_initialized(self):
        data = {"session_id": "s2", "project_path": "", "last_updated": ""}
        (self.index_dir / "s2.json").write_text(json.dumps(data), encoding="utf-8")
        idx = _load_or_init_session_index(self.index_dir, "s2")
        self.assertIsInstance(idx["prompts"], list)
        self.assertIsInstance(idx["bash_commands"], list)
        self.assertIsInstance(idx["tool_calls"], list)

    def test_numeric_count_coerced_from_valid_value(self):
        data = {
            "session_id": "s3",
            "project_path": "",
            "last_updated": "",
            "prompts": [{"text": "a"}, {"text": "b"}],
            "bash_commands": ["cmd1"],
            "tool_calls": [],
            "prompt_count": 2,
            "bash_count": 1,
        }
        (self.index_dir / "s3.json").write_text(json.dumps(data), encoding="utf-8")
        idx = _load_or_init_session_index(self.index_dir, "s3")
        self.assertEqual(idx["prompt_count"], 2)
        self.assertEqual(idx["bash_count"], 1)


# ---------------------------------------------------------------------------
# _process_one_file
# ---------------------------------------------------------------------------

class TestProcessOneFile(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmpdir = Path(self._td.name)
        self.index_dir = self.tmpdir / "index"
        self.index_dir.mkdir()
        self.state_path = self.index_dir / ".state.json"
        self.state_path.write_text(json.dumps({}), encoding="utf-8")

    def _write_jsonl(self, name: str, records: list[dict]) -> Path:
        p = self.tmpdir / name
        with open(p, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return p

    def test_happy_path_returns_ok(self):
        p = self._write_jsonl("session1.jsonl", [
            {"message": {"role": "user", "content": "Hello"}}
        ])
        state: dict = {}
        result = _process_one_file(p, self.index_dir, state, self.state_path, False)
        self.assertIsInstance(result, ParseResult)
        self.assertEqual(result.session_id, "session1")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.prompts_added, 1)

    def test_no_force_skips_already_processed(self):
        record = {"message": {"role": "user", "content": "Forced"}}
        p = self._write_jsonl("force_session.jsonl", [record])
        state: dict = {str(p.resolve()): p.stat().st_size}
        result = _process_one_file(p, self.index_dir, state, self.state_path, False)
        self.assertEqual(result.status, "skipped")

    def test_force_reprocesses_from_start(self):
        record = {"message": {"role": "user", "content": "Forced"}}
        p = self._write_jsonl("force_session2.jsonl", [record])
        state: dict = {str(p.resolve()): p.stat().st_size}
        result = _process_one_file(p, self.index_dir, state, self.state_path, True)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.prompts_added, 1)

    def test_empty_file_returns_skipped(self):
        p = self.tmpdir / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        state: dict = {}
        result = _process_one_file(p, self.index_dir, state, self.state_path, False)
        self.assertEqual(result.status, "skipped")

    def test_corrupted_state_entry_reprocesses(self):
        p = self._write_jsonl("sess.jsonl", [
            {"message": {"role": "user", "content": "Hi"}}
        ])
        state: dict = {str(p.resolve()): "not_an_int"}
        result = _process_one_file(p, self.index_dir, state, self.state_path, False)
        self.assertEqual(result.prompts_added, 1)

    def test_index_file_created_on_disk(self):
        p = self._write_jsonl("new_sess.jsonl", [
            {"message": {"role": "user", "content": "Data"}}
        ])
        state: dict = {}
        _process_one_file(p, self.index_dir, state, self.state_path, False)
        self.assertTrue((self.index_dir / "new_sess.json").exists())

    def test_state_updated_with_new_offset(self):
        p = self._write_jsonl("state_sess.jsonl", [
            {"message": {"role": "user", "content": "Update state"}}
        ])
        state: dict = {}
        _process_one_file(p, self.index_dir, state, self.state_path, False)
        abs_path = str(p.resolve())
        self.assertIn(abs_path, state)
        self.assertGreater(state[abs_path], 0)

    def test_parse_result_bash_added(self):
        p = self._write_jsonl("bash_sess.jsonl", [
            {
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
                }
            }
        ])
        state: dict = {}
        result = _process_one_file(p, self.index_dir, state, self.state_path, False)
        self.assertEqual(result.bash_added, 1)


# ---------------------------------------------------------------------------
# run_parse_transcripts
# ---------------------------------------------------------------------------

class TestRunParseTranscripts(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmpdir = Path(self._td.name)
        self.index_dir = self.tmpdir / "index"
        self.projects_dir = self.tmpdir / "projects"
        self.projects_dir.mkdir()

    def _write_jsonl(self, rel: str, records: list[dict]) -> Path:
        p = self.projects_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return p

    def test_empty_projects_dir_returns_empty_list(self):
        results = run_parse_transcripts(
            since="all",
            projects_dir=self.projects_dir,
            index_dir=self.index_dir,
            force=False,
            limit=0,
        )
        self.assertEqual(results, [])

    def test_processes_jsonl_files(self):
        self._write_jsonl("proj/session1.jsonl", [
            {"message": {"role": "user", "content": "Hello"}}
        ])
        results = run_parse_transcripts(
            since="all",
            projects_dir=self.projects_dir,
            index_dir=self.index_dir,
            force=False,
            limit=0,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].prompts_added, 1)

    def test_limit_applied(self):
        self._write_jsonl("proj/session1.jsonl", [
            {"message": {"role": "user", "content": "Hello"}}
        ])
        self._write_jsonl("proj/session2.jsonl", [
            {"message": {"role": "user", "content": "World"}}
        ])
        results = run_parse_transcripts(
            since="all",
            projects_dir=self.projects_dir,
            index_dir=self.index_dir,
            force=False,
            limit=1,
        )
        self.assertEqual(len(results), 1)

    def test_invalid_since_raises_bad_parameter(self):
        with self.assertRaises(click.BadParameter):
            run_parse_transcripts(
                since="badvalue",
                projects_dir=self.projects_dir,
                index_dir=self.index_dir,
                force=False,
                limit=0,
            )

    def test_creates_index_dir(self):
        new_index = self.tmpdir / "new_index_dir"
        self.assertFalse(new_index.exists())
        run_parse_transcripts(
            since="all",
            projects_dir=self.projects_dir,
            index_dir=new_index,
            force=False,
            limit=0,
        )
        self.assertTrue(new_index.exists())

    def test_none_projects_dir_defaults_to_home_claude(self):
        # Patch Path.home to return our tmpdir so we don't touch real ~/.claude
        fake_home = self.tmpdir / "fakehome"
        fake_home.mkdir()
        (fake_home / ".claude" / "projects").mkdir(parents=True)
        with patch("telemetry.parse_transcripts.Path.home", return_value=fake_home):
            results = run_parse_transcripts(
                since="all",
                projects_dir=None,
                index_dir=self.index_dir,
                force=False,
                limit=0,
            )
        self.assertEqual(results, [])

    def test_multiple_sessions_all_processed(self):
        for i in range(3):
            self._write_jsonl(f"proj/session{i}.jsonl", [
                {"message": {"role": "user", "content": f"Message {i}"}}
            ])
        results = run_parse_transcripts(
            since="all",
            projects_dir=self.projects_dir,
            index_dir=self.index_dir,
            force=False,
            limit=0,
        )
        self.assertEqual(len(results), 3)


# ---------------------------------------------------------------------------
# _emit_rows
# ---------------------------------------------------------------------------

class TestEmitRows(unittest.TestCase):
    def test_json_output(self):
        import io
        rows = [{"a": 1, "b": "x"}]
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_rows(rows, fmt="json")
        output = buf.getvalue()
        parsed = json.loads(output)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["a"], 1)

    def test_table_output_has_header_and_data(self):
        import io
        rows = [{"session_id": "abc123", "status": "ok"}]
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_rows(rows, fmt="table")
        output = buf.getvalue()
        self.assertIn("session_id", output)
        self.assertIn("abc123", output)

    def test_empty_table_no_output(self):
        import io
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_rows([], fmt="table")
        self.assertEqual(buf.getvalue(), "")

    def test_custom_headers_limit_columns(self):
        import io
        rows = [{"a": 1, "b": 2, "c": 3}]
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_rows(rows, fmt="table", headers=["a", "b"])
        output = buf.getvalue()
        self.assertIn("a", output)
        # 'c' should not appear if only a and b are specified as headers
        self.assertNotIn("c", output)

    def test_table_separator_line_present(self):
        import io
        rows = [{"col": "val"}]
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_rows(rows, fmt="table")
        output = buf.getvalue()
        self.assertIn("-", output)


# ---------------------------------------------------------------------------
# parse_transcripts CLI command
# ---------------------------------------------------------------------------

class TestParseTranscriptsCli(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmpdir = Path(self._td.name)
        self.projects_dir = self.tmpdir / "projects"
        self.projects_dir.mkdir()
        self.index_dir = self.tmpdir / "index"

    def _write_jsonl(self, rel: str, records: list[dict]) -> Path:
        p = self.projects_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return p

    def test_cli_no_sessions_message(self):
        runner = CliRunner()
        result = runner.invoke(parse_transcripts, [
            "--projects-dir", str(self.projects_dir),
            "--index-dir", str(self.index_dir),
        ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No sessions processed", result.output)

    def test_cli_json_format(self):
        self._write_jsonl("proj/s1.jsonl", [
            {"message": {"role": "user", "content": "Hello"}}
        ])
        runner = CliRunner()
        result = runner.invoke(parse_transcripts, [
            "--projects-dir", str(self.projects_dir),
            "--index-dir", str(self.index_dir),
            "--format", "json",
        ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertIn("session_id", data[0])

    def test_cli_table_format(self):
        self._write_jsonl("proj/s2.jsonl", [
            {"message": {"role": "user", "content": "World"}}
        ])
        runner = CliRunner()
        result = runner.invoke(parse_transcripts, [
            "--projects-dir", str(self.projects_dir),
            "--index-dir", str(self.index_dir),
            "--format", "table",
        ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("session_id", result.output)

    def test_cli_invalid_since_exits_1(self):
        runner = CliRunner()
        result = runner.invoke(parse_transcripts, [
            "--projects-dir", str(self.projects_dir),
            "--index-dir", str(self.index_dir),
            "--since", "badvalue",
        ])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("error", result.output.lower())

    def test_cli_force_flag(self):
        self._write_jsonl("proj/s3.jsonl", [
            {"message": {"role": "user", "content": "Force me"}}
        ])
        runner = CliRunner()
        result = runner.invoke(parse_transcripts, [
            "--projects-dir", str(self.projects_dir),
            "--index-dir", str(self.index_dir),
            "--force",
        ])
        self.assertEqual(result.exit_code, 0)

    def test_cli_limit_flag(self):
        self._write_jsonl("proj/s4.jsonl", [
            {"message": {"role": "user", "content": "Limit one"}}
        ])
        self._write_jsonl("proj/s5.jsonl", [
            {"message": {"role": "user", "content": "Limit two"}}
        ])
        runner = CliRunner()
        result = runner.invoke(parse_transcripts, [
            "--projects-dir", str(self.projects_dir),
            "--index-dir", str(self.index_dir),
            "--limit", "1",
            "--format", "json",
        ])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertEqual(len(data), 1)

    def test_cli_since_7d(self):
        runner = CliRunner()
        result = runner.invoke(parse_transcripts, [
            "--projects-dir", str(self.projects_dir),
            "--index-dir", str(self.index_dir),
            "--since", "7d",
        ])
        self.assertEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
