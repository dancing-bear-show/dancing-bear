"""Tests for workflow.cli_compile — compile cache helpers and _cmd_compile handler."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.workflow_tests.helpers.factories import make_cli_args as _make_args
from tests.workflow_tests.helpers.factories import write_yaml as _write_yaml
from workflow.cli_compile import (
    _build_compile_payload,
    _cmd_compile,
    _compile_cache_path,
    _fragment_bytes,
    _render_compile_output,
    _try_read_cached_compile,
    _write_once,
)


# ---------------------------------------------------------------------------
# Minimal YAML fixture
# ---------------------------------------------------------------------------

_MINIMAL_YAML = """\
name: compile-test-wf
version: "0.1.0"
description: "Compile test workflow"
trigger:
  source: manual
stages:
  - name: gather
    kind: gather
    description: "Gather"
    agent:
      role: researcher
"""

_TWO_STAGE_YAML = """\
name: two-stage-wf
version: "0.1.0"
description: "Two stage compile"
trigger:
  source: manual
stages:
  - name: gather
    kind: gather
    description: "Gather"
    agent:
      role: researcher
  - name: propose
    kind: propose
    description: "Propose"
    depends_on: [gather]
    agent:
      role: code-writer
"""


# ---------------------------------------------------------------------------
# _fragment_bytes
# ---------------------------------------------------------------------------


class TestFragmentBytes(unittest.TestCase):
    def test_no_includes_returns_empty_bytes(self) -> None:
        yaml_bytes = _MINIMAL_YAML.encode()
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _fragment_bytes(yaml_bytes, Path(tmp_dir) / "wf.yaml")
        self.assertEqual(result, b"")

    def test_returns_bytes_type(self) -> None:
        yaml_bytes = b"name: test\n"
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _fragment_bytes(yaml_bytes, Path(tmp_dir) / "wf.yaml")
        self.assertIsInstance(result, bytes)

    def test_yaml_with_include_returns_fragment_content(self) -> None:
        fragment_content = "fragment: true\nstages: []\n"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "frag.yaml"
            frag.write_text(fragment_content, encoding="utf-8")
            yaml_with_include = """\
name: wf
version: "0.1"
description: "test"
trigger:
  source: manual
include:
  - path: frag.yaml
stages:
  - name: gather
    kind: gather
    description: "g"
    agent:
      role: researcher
"""
            yaml_bytes = yaml_with_include.encode()
            result = _fragment_bytes(yaml_bytes, tmp_path / "wf.yaml")
        self.assertIsInstance(result, bytes)


# ---------------------------------------------------------------------------
# _compile_cache_path
# ---------------------------------------------------------------------------


class TestCompileCachePath(unittest.TestCase):
    def test_returns_path_object(self) -> None:
        yaml_bytes = _MINIMAL_YAML.encode()
        cache_path = _compile_cache_path(yaml_bytes, "/project", [])
        self.assertIsInstance(cache_path, Path)

    def test_filename_starts_with_workflow_compile(self) -> None:
        yaml_bytes = _MINIMAL_YAML.encode()
        cache_path = _compile_cache_path(yaml_bytes, "/project", [])
        self.assertTrue(cache_path.name.startswith("workflow-compile-"))

    def test_different_content_produces_different_cache_key(self) -> None:
        path1 = _compile_cache_path(b"content-a", "/project", [])
        path2 = _compile_cache_path(b"content-b", "/project", [])
        self.assertNotEqual(path1, path2)

    def test_same_content_same_root_same_params_same_key(self) -> None:
        yaml_bytes = b"same-content"
        path1 = _compile_cache_path(yaml_bytes, "/same-root", ["a=1"])
        path2 = _compile_cache_path(yaml_bytes, "/same-root", ["a=1"])
        self.assertEqual(path1, path2)

    def test_different_params_different_key(self) -> None:
        yaml_bytes = b"same-content"
        path1 = _compile_cache_path(yaml_bytes, "/root", ["env=prod"])
        path2 = _compile_cache_path(yaml_bytes, "/root", ["env=staging"])
        self.assertNotEqual(path1, path2)

    def test_different_project_root_different_key(self) -> None:
        yaml_bytes = b"same-content"
        path1 = _compile_cache_path(yaml_bytes, "/root-a", [])
        path2 = _compile_cache_path(yaml_bytes, "/root-b", [])
        self.assertNotEqual(path1, path2)


# ---------------------------------------------------------------------------
# _try_read_cached_compile
# ---------------------------------------------------------------------------


class TestTryReadCachedCompile(unittest.TestCase):
    def test_missing_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "nonexistent.json"
            result = _try_read_cached_compile(cache_path)
        self.assertIsNone(result)

    def test_valid_json_dict_returns_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "cache.json"
            cache_path.write_text('{"name": "wf", "total_stages": 1}', encoding="utf-8")
            result = _try_read_cached_compile(cache_path)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["name"], "wf")

    def test_corrupt_json_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "corrupt.json"
            cache_path.write_text("not-json{{{{", encoding="utf-8")
            result = _try_read_cached_compile(cache_path)
        self.assertIsNone(result)

    def test_json_array_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "array.json"
            cache_path.write_text("[1, 2, 3]", encoding="utf-8")
            result = _try_read_cached_compile(cache_path)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _write_once
# ---------------------------------------------------------------------------


class TestWriteOnce(unittest.TestCase):
    def test_writes_content_to_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "output.json"
            _write_once(target, b'{"key": "value"}')
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), '{"key": "value"}')

    def test_does_not_overwrite_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "output.json"
            target.write_bytes(b"original")
            _write_once(target, b"new-content")
            self.assertEqual(target.read_bytes(), b"original")

    def test_multiple_writes_to_same_path_only_first_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "once.json"
            _write_once(target, b"first")
            _write_once(target, b"second")
            self.assertEqual(target.read_bytes(), b"first")


# ---------------------------------------------------------------------------
# _render_compile_output
# ---------------------------------------------------------------------------


class TestRenderCompileOutput(unittest.TestCase):
    def _sample_payload(self) -> dict:
        return {
            "name": "my-wf",
            "total_stages": 2,
            "total_groups": 2,
            "max_parallelism": 1,
            "compiled_at": "2026-04-01T00:00:00Z",
            "contract_warnings": 0,
            "groups": [
                {"group": 0, "stages": "gather", "parallelism": 1},
                {"group": 1, "stages": "propose", "parallelism": 1},
            ],
            "resolutions": [
                {"stage": "gather", "template_resolved": False, "guide_resolved": False, "cli_commands": 0},
                {"stage": "propose", "template_resolved": False, "guide_resolved": False, "cli_commands": 0},
            ],
            "contract_warnings_detail": [],
        }

    def test_json_format_prints_full_payload(self) -> None:
        payload = self._sample_payload()
        out = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", io.StringIO()):
            _render_compile_output(payload, "json")
        data = json.loads(out.getvalue())
        self.assertIn("name", data)
        self.assertEqual(data["name"], "my-wf")

    def test_table_format_prints_summary(self) -> None:
        payload = self._sample_payload()
        out = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", io.StringIO()):
            _render_compile_output(payload, "table")
        output = out.getvalue()
        self.assertIn("name", output)
        self.assertIn("my-wf", output)

    def test_contract_warnings_printed_to_stderr(self) -> None:
        payload = self._sample_payload()
        payload["contract_warnings"] = 1
        payload["contract_warnings_detail"] = [
            {"stage": "gather", "upstream": "propose", "message": "reads_from mismatch"}
        ]
        err = io.StringIO()
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", err):
            _render_compile_output(payload, "table")
        self.assertIn("contract warning", err.getvalue())

    def test_empty_groups_not_emitted_in_table(self) -> None:
        payload = self._sample_payload()
        payload["groups"] = []
        out = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", io.StringIO()):
            _render_compile_output(payload, "table")
        # Should still work without crashing
        self.assertIn("name", out.getvalue())


# ---------------------------------------------------------------------------
# _build_compile_payload
# ---------------------------------------------------------------------------


class TestBuildCompilePayload(unittest.TestCase):
    def test_payload_contains_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            payload = _build_compile_payload(path)
        self.assertEqual(payload["name"], "compile-test-wf")

    def test_resolution_carries_agent_spec(self) -> None:
        """Agent role/model/isolation reach the manifest.

        The orchestrator spawns agents from this payload, so a stage's
        isolation must survive compilation — otherwise `isolation: worktree`
        parses fine and still never reaches the Agent() call.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            payload = _build_compile_payload(path)
        res = {r["stage"]: r for r in payload["resolutions"]}["gather"]
        self.assertEqual(res["agent_role"], "researcher")
        self.assertIsNone(res["agent_model"])
        self.assertIsNone(res["agent_isolation"])

    def test_resolution_carries_worktree_isolation(self) -> None:
        yaml_src = _MINIMAL_YAML.replace(
            "      role: researcher\n",
            "      role: code-writer\n      isolation: worktree\n",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, yaml_src))
            payload = _build_compile_payload(path)
        res = {r["stage"]: r for r in payload["resolutions"]}["gather"]
        self.assertEqual(res["agent_isolation"], "worktree")
        self.assertEqual(res["agent_role"], "code-writer")

    def test_payload_total_stages_matches_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            payload = _build_compile_payload(path)
        self.assertEqual(payload["total_stages"], 1)

    def test_two_stage_workflow_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _TWO_STAGE_YAML))
            payload = _build_compile_payload(path)
        self.assertEqual(payload["total_stages"], 2)
        self.assertEqual(payload["total_groups"], 2)

    def test_payload_contains_groups_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            payload = _build_compile_payload(path)
        self.assertIn("groups", payload)
        self.assertIsInstance(payload["groups"], list)

    def test_payload_contains_resolutions_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            payload = _build_compile_payload(path)
        self.assertIn("resolutions", payload)

    def test_payload_has_compiled_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            payload = _build_compile_payload(path)
        self.assertIn("compiled_at", payload)
        self.assertIn("T", payload["compiled_at"])

    def test_payload_has_contract_warnings_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            payload = _build_compile_payload(path)
        self.assertIn("contract_warnings", payload)
        self.assertIsInstance(payload["contract_warnings"], int)

    def test_max_parallelism_is_int(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            payload = _build_compile_payload(path)
        self.assertIsInstance(payload["max_parallelism"], int)


# ---------------------------------------------------------------------------
# _cmd_compile
# ---------------------------------------------------------------------------


class TestCmdCompile(unittest.TestCase):
    def test_returns_zero_on_valid_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            args = _make_args(path=path, format="json", no_cache=True)
            out = io.StringIO()
            with patch("sys.stdout", out), patch("sys.stderr", io.StringIO()):
                rc = _cmd_compile(args)
            self.assertEqual(rc, 0)

    def test_output_contains_workflow_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            args = _make_args(path=path, format="json", no_cache=True)
            out = io.StringIO()
            with patch("sys.stdout", out), patch("sys.stderr", io.StringIO()):
                _cmd_compile(args)
            data = json.loads(out.getvalue())
            self.assertEqual(data["name"], "compile-test-wf")

    def test_returns_one_when_file_missing(self) -> None:
        args = _make_args(path="/no/such/wf.yaml", format="json", no_cache=True)
        with patch("sys.stderr", io.StringIO()):
            rc = _cmd_compile(args)
        self.assertEqual(rc, 1)

    def test_cache_hit_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            # Pre-build a payload that would come from a cache
            cached_payload = {
                "name": "cached-wf",
                "total_stages": 1,
                "total_groups": 1,
                "max_parallelism": 1,
                "compiled_at": "2026-01-01T00:00:00Z",
                "contract_warnings": 0,
                "groups": [],
                "resolutions": [],
                "contract_warnings_detail": [],
            }
            args = _make_args(path=path, format="json", no_cache=False)
            out = io.StringIO()
            # Patch _try_read_cached_compile to return our cached payload
            with patch("workflow.cli_compile._try_read_cached_compile", return_value=cached_payload), \
                 patch("sys.stdout", out), \
                 patch("sys.stderr", io.StringIO()):
                rc = _cmd_compile(args)
            self.assertEqual(rc, 0)
            data = json.loads(out.getvalue())
            self.assertEqual(data["name"], "cached-wf")

    def test_no_cache_flag_bypasses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            args = _make_args(path=path, format="json", no_cache=True)
            out = io.StringIO()
            with patch("workflow.cli_compile._try_read_cached_compile") as mock_cache, \
                 patch("sys.stdout", out), \
                 patch("sys.stderr", io.StringIO()):
                rc = _cmd_compile(args)
            # _try_read_cached_compile should not be called when no_cache=True
            mock_cache.assert_not_called()
            self.assertEqual(rc, 0)

    def test_table_format_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            args = _make_args(path=path, format="table", no_cache=True)
            out = io.StringIO()
            with patch("sys.stdout", out), patch("sys.stderr", io.StringIO()):
                rc = _cmd_compile(args)
            self.assertEqual(rc, 0)
            self.assertIn("name", out.getvalue())

    def test_writes_compile_cache_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            args = _make_args(path=path, format="json", no_cache=True)
            written_paths = []

            __import__(
                "workflow.cli_compile", fromlist=["_write_once"]
            )._write_once

            def capture_write(p, content):
                written_paths.append(p)

            with patch("workflow.cli_compile._write_once", side_effect=capture_write), \
                 patch("sys.stdout", io.StringIO()), \
                 patch("sys.stderr", io.StringIO()):
                _cmd_compile(args)

            self.assertEqual(len(written_paths), 1)
            self.assertIn("workflow-compile-", written_paths[0].name)

    def test_io_error_reading_yaml_returns_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            args = _make_args(path=path, format="json", no_cache=True)
            with patch("pathlib.Path.read_bytes", side_effect=OSError("disk error")), \
                 patch("sys.stderr", io.StringIO()):
                rc = _cmd_compile(args)
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
