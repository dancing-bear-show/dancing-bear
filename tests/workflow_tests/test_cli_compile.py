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

    def test_resolution_carries_dispatch_metadata(self) -> None:
        """A resolution must carry everything needed to dispatch a stage.

        The skill's documented compile-to-spawn path reads stage name, index,
        kind and executor from this payload. A missing key forces the
        orchestrator back to the parsed YAML, which defeats the manifest.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(_write_yaml(tmp_dir, _MINIMAL_YAML))
            payload = _build_compile_payload(path)
        res = {r["stage"]: r for r in payload["resolutions"]}["gather"]
        for key in ("index", "kind", "executor", "human_gate", "sub_workflow"):
            self.assertIn(key, res)
        self.assertEqual(res["kind"], "gather")
        self.assertEqual(res["index"], 0)

    def test_cache_key_includes_payload_schema_version(self) -> None:
        """A payload-schema bump must invalidate caches written by the old one.

        The key is derived from YAML + root + params, so without the schema
        version a cache written before `agent_isolation` was added would still
        be served — silently dropping isolation for any workflow already
        compiled once.
        """
        from workflow import cli_compile

        args = (b"name: x\n", "/repo", [])
        before = cli_compile._compile_cache_path(*args)
        original = cli_compile._COMPILE_PAYLOAD_SCHEMA
        try:
            cli_compile._COMPILE_PAYLOAD_SCHEMA = original + 1
            after = cli_compile._compile_cache_path(*args)
        finally:
            cli_compile._COMPILE_PAYLOAD_SCHEMA = original
        self.assertNotEqual(before, after)

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


# ---------------------------------------------------------------------------
# `when` visibility in the compiled manifest
# ---------------------------------------------------------------------------


_CONDITIONAL_YAML = (
    "name: conditional-wf\n"
    'version: "1.0"\n'
    "description: Two mutually-exclusive branches\n"
    "trigger:\n"
    "  source: manual\n"
    "  params:\n"
    "    mode: fast\n"
    "stages:\n"
    "  - name: always\n"
    "    kind: execute\n"
    "    description: Runs unconditionally\n"
    "    agent:\n"
    "      role: doc-writer\n"
    "  - name: fast-path\n"
    "    kind: execute\n"
    "    description: Fast branch\n"
    "    agent:\n"
    "      role: doc-writer\n"
    "    when: '\"{mode}\" contains \"fast\"'\n"
    "  - name: slow-path\n"
    "    kind: execute\n"
    "    description: Slow branch\n"
    "    agent:\n"
    "      role: doc-writer\n"
    "    when: '\"{mode}\" does not contain \"fast\"'\n"
)


class TestManifestWhenVisibility(unittest.TestCase):
    """The manifest must say which conditional stages actually run.

    Without `when`/`will_run`, mutually-exclusive stages are listed as equally
    runnable, so an orchestrator dispatching from `resolutions` alone runs BOTH
    branches — and two stages declaring the same output silently clobber each
    other.
    """

    def _resolutions(self, yaml_text: str = _CONDITIONAL_YAML) -> dict:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "wf.yaml"
            path.write_text(yaml_text)
            payload = _build_compile_payload(str(path))
        return {r["stage"]: r for r in payload["resolutions"]}

    def test_resolutions_carry_the_when_expression(self):
        res = self._resolutions()
        self.assertIsNone(res["always"]["when"])
        self.assertIn("contains", res["fast-path"]["when"])

    def test_will_run_reflects_the_resolved_param(self):
        res = self._resolutions()
        self.assertTrue(res["fast-path"]["will_run"])
        self.assertFalse(res["slow-path"]["will_run"])

    def test_unconditional_stage_always_runs(self):
        self.assertTrue(self._resolutions()["always"]["will_run"])

    def test_exactly_one_branch_runs(self):
        res = self._resolutions()
        running = [n for n in ("fast-path", "slow-path") if res[n]["will_run"]]
        self.assertEqual(running, ["fast-path"])

    def test_flipping_the_param_flips_the_branch(self):
        res = self._resolutions(_CONDITIONAL_YAML.replace("    mode: fast", "    mode: slow"))
        self.assertFalse(res["fast-path"]["will_run"])
        self.assertTrue(res["slow-path"]["will_run"])

    def test_manifest_agrees_with_the_runtime_evaluator(self):
        # The manifest disagreeing with the orchestrator would be worse than
        # omitting the field, so pin them to the same answer.
        import re

        from workflow.compiler import resolve_params

        def runtime_eval(when, params):
            if when is None:
                return True
            expr = resolve_params(when, params)
            m = re.fullmatch(r'"(.*?)"\s+does not contain\s+"(.*?)"', expr)
            if m:
                return m.group(2) not in m.group(1)
            m = re.fullmatch(r'"(.*?)"\s+contains\s+"(.*?)"', expr)
            if m:
                return m.group(2) in m.group(1)
            return True

        res = self._resolutions()
        params = {"mode": "fast"}
        for name, r in res.items():
            self.assertEqual(
                r["will_run"], runtime_eval(r["when"], params), f"disagreement on {name}"
            )


# ---------------------------------------------------------------------------
# Real workflows keep their documented review path
# ---------------------------------------------------------------------------


class TestSwarmPathContract(unittest.TestCase):
    """code-review-swarm.yaml documents which callers take which path.

    Its header says: "code-review.yaml defaults to small; other callers
    default to large." Once fragment trigger params are inherited, a caller
    that does not declare pr_size picks up the fragment's own "small" default
    and silently switches to the single-agent reviewer. These pin the real
    workflows against that.
    """

    _REPO = Path(__file__).resolve().parents[2]

    def _pr_size_stages(self, rel_path: str):
        from workflow.cli_compile import _build_compile_payload

        path = self._REPO / rel_path
        if not path.exists():  # pragma: no cover - workflow renamed or removed
            self.skipTest(f"{rel_path} not present")
        payload = _build_compile_payload(str(path))
        return [
            r for r in payload["resolutions"]
            if r.get("when") and "pr_size" in r["when"]
        ]

    def _running(self, rel_path: str):
        stages = self._pr_size_stages(rel_path)
        self.assertTrue(stages, f"{rel_path} has no pr_size-gated stages")
        return [r["stage"] for r in stages if r["will_run"]]

    def test_code_review_takes_the_consolidated_path(self):
        running = self._running("workflows/code/code-review.yaml")
        self.assertEqual(running, ["review-consolidated"])

    def test_coverage_uplift_takes_the_fan_out_path(self):
        running = self._running("workflows/code/coverage-uplift.yaml")
        self.assertNotIn("review-review-consolidated", running)
        self.assertGreater(len(running), 1, "expected the multi-stage fan-out")

    def test_review_and_fix_takes_the_fan_out_path(self):
        running = self._running("workflows/code/review-and-fix.yaml")
        self.assertNotIn("review-consolidated", running)
        self.assertGreater(len(running), 1, "expected the multi-stage fan-out")

    def test_exactly_one_branch_runs_in_each_caller(self):
        # The manifest must never present both branches as runnable: they
        # declare the same outputs and would clobber each other.
        for rel in (
            "workflows/code/code-review.yaml",
            "workflows/code/coverage-uplift.yaml",
            "workflows/code/review-and-fix.yaml",
        ):
            with self.subTest(workflow=rel):
                stages = self._pr_size_stages(rel)
                consolidated = [
                    r for r in stages if r["stage"].endswith("review-consolidated")
                ]
                fanned = [r for r in stages if r not in consolidated]
                self.assertTrue(consolidated, "no consolidated stage found")
                c_runs = any(r["will_run"] for r in consolidated)
                f_runs = any(r["will_run"] for r in fanned)
                self.assertNotEqual(
                    c_runs, f_runs, "exactly one branch must run, not both or neither"
                )


# ---------------------------------------------------------------------------
# Manifest must not diverge from the runtime
# ---------------------------------------------------------------------------


class TestWhenWhitespace(unittest.TestCase):
    """_validate_when accepts padding; both evaluators must too.

    _validate_when validates `spec.when.strip()`, so `  "{m}" contains "x"  `
    compiles cleanly. The runtime evaluator used re.fullmatch on the
    unstripped string and raised WorkflowExecutionError at dispatch, while the
    manifest evaluator returned its permissive fallback True — advertising a
    branch that could not run.
    """

    _PADDED = '  "{mode}" contains "fast"  '

    def test_manifest_evaluates_a_padded_expression(self):
        from workflow.cli_compile import _eval_when_for_manifest

        self.assertTrue(_eval_when_for_manifest(self._PADDED, {"mode": "fast"}))
        self.assertFalse(_eval_when_for_manifest(self._PADDED, {"mode": "slow"}))

    def test_padded_expression_is_not_the_permissive_fallback(self):
        # Before the fix this returned True for BOTH params, because neither
        # regex matched and the fallback fired. Asserting only the True case
        # would have passed against the bug.
        from workflow.cli_compile import _eval_when_for_manifest

        self.assertNotEqual(
            _eval_when_for_manifest(self._PADDED, {"mode": "fast"}),
            _eval_when_for_manifest(self._PADDED, {"mode": "slow"}),
        )

    def test_runtime_evaluator_accepts_padding(self):
        # Call the shared matcher both evaluators use rather than re-stating
        # its regex here: a copy of the pattern in the test would keep passing
        # if the real one changed, which is the drift this test exists to catch.
        from workflow.compiler import match_when_expression

        self.assertIs(match_when_expression(self._PADDED, {"mode": "fast"}), True)
        self.assertIs(match_when_expression(self._PADDED, {"mode": "slow"}), False)

    def test_validate_when_accepts_padding(self):
        # The premise: if the compiler rejected padding, there would be no
        # divergence to fix.
        from workflow.compiler import _WHEN_PATTERN

        self.assertIsNotNone(_WHEN_PATTERN.fullmatch(self._PADDED.strip()))


class TestSharedWhenMatcher(unittest.TestCase):
    """match_when_expression is the single source both evaluators share.

    The manifest evaluator and orchestrator._eval_when previously each carried
    their own copy of the two regexes, with only a docstring ("Mirrors
    orchestrator._eval_when exactly") holding them in sync. They now call this
    one function and differ only in what they do with an unmatched expression,
    so that difference is what these tests pin.
    """

    def test_recognised_forms(self):
        from workflow.compiler import match_when_expression

        params = {"skip": "coverage,security"}
        cases = [
            ('"{skip}" contains "coverage"', True),
            ('"{skip}" contains "reuse"', False),
            ('"{skip}" does not contain "reuse"', True),
            ('"{skip}" does not contain "coverage"', False),
        ]
        for expr, expected in cases:
            with self.subTest(expr=expr):
                self.assertIs(match_when_expression(expr, params), expected)

    def test_unrecognised_form_returns_none(self):
        # None, not a bool: each caller supplies its own fallback, and a bool
        # here would silently impose one of them on both.
        from workflow.compiler import match_when_expression

        self.assertIsNone(match_when_expression("not an expression", {}))

    def test_callers_keep_their_divergent_fallbacks(self):
        from workflow.cli_compile import _eval_when_for_manifest
        from workflow.orchestrator import (
            WorkflowExecutionError,
            WorkflowOrchestrator,
        )

        bogus = "not an expression"
        # The manifest is permissive: a manifest field is not the place to
        # fail a build.
        self.assertTrue(_eval_when_for_manifest(bogus, {}))
        # The runtime is strict: reaching dispatch with an unparseable
        # expression means _validate_when let a bug through.
        orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
        with self.assertRaises(WorkflowExecutionError):
            orch._eval_when(bogus, {})


class TestManifestHonoursParamOverrides(unittest.TestCase):
    """will_run must reflect --params, not just declared defaults.

    The run path merges caller overrides over the declared trigger params. A
    manifest computed from defaults alone advertises the default branch while
    execution takes the other one.
    """

    _YAML = (
        "name: override-wf\n"
        'version: "1.0"\n'
        "description: Two branches keyed on mode\n"
        "trigger:\n"
        "  source: manual\n"
        "  params:\n"
        "    mode: fast\n"
        "    other: y\n"
        "stages:\n"
        "  - name: fast-path\n"
        "    kind: execute\n"
        "    description: fast\n"
        "    agent:\n"
        "      role: doc-writer\n"
        "    when: '\"{mode}\" contains \"fast\"'\n"
        "  - name: slow-path\n"
        "    kind: execute\n"
        "    description: slow\n"
        "    agent:\n"
        "      role: doc-writer\n"
        "    when: '\"{mode}\" does not contain \"fast\"'\n"
    )

    def _running(self, overrides=None):
        from workflow.cli_compile import _build_compile_payload

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "wf.yaml"
            path.write_text(self._YAML)
            payload = _build_compile_payload(str(path), overrides)
        return [r["stage"] for r in payload["resolutions"] if r["will_run"]]

    def test_declared_default_selects_the_default_branch(self):
        self.assertEqual(self._running(), ["fast-path"])

    def test_override_flips_the_branch(self):
        self.assertEqual(self._running(["mode=slow"]), ["slow-path"])

    def test_override_matching_the_default_is_a_no_op(self):
        self.assertEqual(self._running(["mode=fast"]), ["fast-path"])

    def test_unrelated_override_leaves_the_branch_alone(self):
        self.assertEqual(self._running(["other=x"]), ["fast-path"])

    def test_malformed_override_is_ignored_not_fatal(self):
        # No "=" — dropped rather than raising. It cannot select a wrong
        # branch: an unresolved {placeholder} is a non-match either way.
        self.assertEqual(self._running(["justakey"]), ["fast-path"])

    def test_value_containing_equals_is_preserved(self):
        from workflow.cli_compile import _parse_param_overrides

        self.assertEqual(_parse_param_overrides(["k=a=b"]), {"k": "a=b"})

    def test_exactly_one_branch_runs_under_override(self):
        self.assertEqual(len(self._running(["mode=slow"])), 1)


if __name__ == "__main__":
    unittest.main()
