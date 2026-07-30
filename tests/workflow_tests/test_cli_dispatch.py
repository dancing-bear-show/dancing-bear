"""Tests for workflow.cli_dispatch — subcommand handlers and shared helpers."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.workflow_tests.helpers.factories import (
    make_cli_args as _make_args,
    make_stage_result,
    make_stage_spec,
    make_workflow_definition,
    make_workflow_manifest,
    write_yaml,
)
from workflow.cli_dispatch import (
    _build_plan_json,
    _build_resolved_params,
    _build_stage_row,
    _cmd_init_workspace,
    _cmd_lint,
    _cmd_list,
    _cmd_parse,
    _cmd_resume,
    _cmd_run,
    _cmd_status,
    _cmd_validate_fragment,
    _confirm_execution,
    _generate_run_id,
    _load_definition,
    _load_manifest,
    _parse_params,
    _resolve_base_dir,
    _stage_names_from_manifest,
    _stage_names_from_plan,
)
from workflow.models import StageStatus


# ---------------------------------------------------------------------------
# Minimal YAML workflow fixture
# ---------------------------------------------------------------------------

_MINIMAL_YAML = """\
name: test-wf
version: "0.1.0"
description: "Minimal test workflow"
trigger:
  source: manual
stages:
  - name: gather
    kind: gather
    description: "Gather stage"
    agent:
      role: researcher
"""


def _write_yaml(tmp_dir: str, content: str, name: str = "wf.yaml") -> str:
    """Write YAML content to a temp file and return its path as a string."""
    return str(write_yaml(tmp_dir, content, name))


# ---------------------------------------------------------------------------
# _parse_params
# ---------------------------------------------------------------------------


class TestParseParams(unittest.TestCase):
    def test_empty_list_returns_empty_dict(self) -> None:
        params, err = _parse_params([])
        self.assertEqual(params, {})
        self.assertIsNone(err)

    def test_valid_key_value_pairs(self) -> None:
        params, err = _parse_params(["env=prod", "team=mail"])
        self.assertEqual(params, {"env": "prod", "team": "mail"})
        self.assertIsNone(err)

    def test_value_with_equals_sign(self) -> None:
        params, err = _parse_params(["url=http://foo?x=1"])
        self.assertEqual(params["url"], "http://foo?x=1")
        self.assertIsNone(err)

    def test_invalid_format_returns_error(self) -> None:
        params, err = _parse_params(["not-a-kv-pair"])
        self.assertEqual(params, {})
        self.assertIsNotNone(err)
        self.assertIn("key=value", err)

    def test_invalid_entry_error_includes_value(self) -> None:
        _, err = _parse_params(["badformat"])
        self.assertIn("badformat", err)


# ---------------------------------------------------------------------------
# _generate_run_id
# ---------------------------------------------------------------------------


class TestGenerateRunId(unittest.TestCase):
    def test_contains_workflow_name(self) -> None:
        run_id = _generate_run_id("my-workflow")
        self.assertIn("my-workflow", run_id)

    def test_is_string(self) -> None:
        run_id = _generate_run_id("wf")
        self.assertIsInstance(run_id, str)

    def test_ids_are_unique(self) -> None:
        ids = {_generate_run_id("wf") for _ in range(5)}
        self.assertGreater(len(ids), 1)

    def test_contains_date_part(self) -> None:
        run_id = _generate_run_id("wf")
        parts = run_id.split("-")
        self.assertGreaterEqual(len(parts), 3)


# ---------------------------------------------------------------------------
# _stage_names_from_plan
# ---------------------------------------------------------------------------


class TestStageNamesFromPlan(unittest.TestCase):
    def test_returns_empty_when_no_plan_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            names = _stage_names_from_plan(Path(tmp_dir))
            self.assertEqual(names, [])

    def test_returns_stage_names_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            plan = {
                "parallel_groups": [
                    {"stages": ["gather"]},
                    {"stages": ["propose", "validate"]},
                ]
            }
            (Path(tmp_dir) / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            names = _stage_names_from_plan(Path(tmp_dir))
            self.assertEqual(names, ["gather", "propose", "validate"])

    def test_returns_empty_on_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "plan.json").write_text("not-json{{{", encoding="utf-8")
            names = _stage_names_from_plan(Path(tmp_dir))
            self.assertEqual(names, [])

    def test_returns_empty_when_parallel_groups_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "plan.json").write_text('{"other": 1}', encoding="utf-8")
            names = _stage_names_from_plan(Path(tmp_dir))
            self.assertEqual(names, [])


# ---------------------------------------------------------------------------
# _stage_names_from_manifest
# ---------------------------------------------------------------------------


class TestStageNamesFromManifest(unittest.TestCase):
    def test_returns_empty_when_no_manifest_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            names = _stage_names_from_manifest(Path(tmp_dir))
            self.assertEqual(names, [])

    def test_returns_stage_names_from_parallel_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = {
                "parallel_groups": [
                    ["gather"],
                    ["propose"],
                ]
            }
            (Path(tmp_dir) / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            names = _stage_names_from_manifest(Path(tmp_dir))
            self.assertEqual(names, ["gather", "propose"])

    def test_returns_empty_on_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "manifest.json").write_text("{bad}", encoding="utf-8")
            names = _stage_names_from_manifest(Path(tmp_dir))
            self.assertEqual(names, [])


# ---------------------------------------------------------------------------
# _build_stage_row
# ---------------------------------------------------------------------------


class TestBuildStageRow(unittest.TestCase):
    def test_none_status_marks_needs_run(self) -> None:
        row = _build_stage_row("gather", None)
        self.assertEqual(row["needs_run"], "yes")
        self.assertEqual(row["status"], "-")
        self.assertEqual(row["stage"], "gather")

    def test_success_status_marks_no_rerun(self) -> None:
        row = _build_stage_row("gather", StageStatus.success)
        self.assertEqual(row["needs_run"], "no")
        self.assertEqual(row["status"], "success")

    def test_failed_status_marks_needs_run(self) -> None:
        row = _build_stage_row("propose", StageStatus.failed)
        self.assertEqual(row["needs_run"], "yes")
        self.assertIn("failed", row["reason"])

    def test_pending_status_marks_needs_run(self) -> None:
        row = _build_stage_row("validate", StageStatus.pending)
        self.assertEqual(row["needs_run"], "yes")

    def test_skipped_status_marks_needs_run(self) -> None:
        row = _build_stage_row("optional", StageStatus.skipped)
        self.assertEqual(row["needs_run"], "yes")


# ---------------------------------------------------------------------------
# _build_plan_json
# ---------------------------------------------------------------------------


class TestBuildPlanJson(unittest.TestCase):
    def test_contains_workflow_name(self) -> None:
        manifest = make_workflow_manifest()
        plan = _build_plan_json("my-wf", "run-001", manifest)
        self.assertEqual(plan["workflow_name"], "my-wf")

    def test_contains_run_id(self) -> None:
        manifest = make_workflow_manifest()
        plan = _build_plan_json("wf", "run-abc", manifest)
        self.assertEqual(plan["run_id"], "run-abc")

    def test_total_stages_matches_manifest(self) -> None:
        from workflow.compiler import compile_workflow
        stages = (
            make_stage_spec(name="a"),
            make_stage_spec(name="b"),
        )
        wf = make_workflow_definition(stages=stages)
        manifest = compile_workflow(wf)
        plan = _build_plan_json("wf", "run-1", manifest)
        self.assertEqual(plan["total_stages"], 2)

    def test_parallel_groups_included(self) -> None:
        manifest = make_workflow_manifest()
        plan = _build_plan_json("wf", "run-1", manifest)
        self.assertIn("parallel_groups", plan)
        self.assertIsInstance(plan["parallel_groups"], list)

    def test_stage_details_has_kind(self) -> None:
        manifest = make_workflow_manifest()
        plan = _build_plan_json("wf", "run-1", manifest)
        for _name, detail in plan["stage_details"].items():
            self.assertIn("kind", detail)
            self.assertIn("agent_role", detail)


# ---------------------------------------------------------------------------
# _resolve_base_dir
# ---------------------------------------------------------------------------


class TestResolveBaseDir(unittest.TestCase):
    def test_override_takes_priority(self) -> None:
        defn = make_workflow_definition()
        result = _resolve_base_dir("/my/override", defn, {})
        self.assertEqual(result, "/my/override")

    def test_falls_back_to_tempdir_when_no_workspace(self) -> None:
        defn = make_workflow_definition()
        import tempfile as _tf
        result = _resolve_base_dir(None, defn, {})
        self.assertEqual(result, _tf.gettempdir())

    def test_uses_workspace_dir_from_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            defn = make_workflow_definition(workspace_dir=f"{tmp_dir}/runs/run-001")
            result = _resolve_base_dir(None, defn, {})
            self.assertIn(tmp_dir, result)


# ---------------------------------------------------------------------------
# _confirm_execution
# ---------------------------------------------------------------------------


class TestConfirmExecution(unittest.TestCase):
    def test_non_interactive_stdin_returns_true(self) -> None:
        with patch("sys.stdin") as mock_stdin, \
             patch("sys.stderr", io.StringIO()):
            mock_stdin.isatty.return_value = False
            result = _confirm_execution("test-wf", 3)
        self.assertTrue(result)

    def test_tty_with_y_response_returns_true(self) -> None:
        with patch("sys.stdin") as mock_stdin, \
             patch("builtins.input", return_value="y"), \
             patch("sys.stderr", io.StringIO()):
            mock_stdin.isatty.return_value = True
            result = _confirm_execution("test-wf", 3)
        self.assertTrue(result)

    def test_tty_with_n_response_returns_false(self) -> None:
        with patch("sys.stdin") as mock_stdin, \
             patch("builtins.input", return_value="n"), \
             patch("sys.stderr", io.StringIO()):
            mock_stdin.isatty.return_value = True
            result = _confirm_execution("test-wf", 3)
        self.assertFalse(result)

    def test_tty_with_yes_response_returns_true(self) -> None:
        with patch("sys.stdin") as mock_stdin, \
             patch("builtins.input", return_value="yes"), \
             patch("sys.stderr", io.StringIO()):
            mock_stdin.isatty.return_value = True
            result = _confirm_execution("test-wf", 3)
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# _load_definition
# ---------------------------------------------------------------------------


class TestLoadDefinition(unittest.TestCase):
    def test_valid_yaml_returns_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            defn = _load_definition(path)
            self.assertEqual(defn.name, "test-wf")

    def test_missing_file_raises_system_exit(self) -> None:
        with self.assertRaises(SystemExit):
            _load_definition("/nonexistent/path/wf.yaml")

    def test_invalid_yaml_raises_system_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, "invalid: yaml: {{{")
            with self.assertRaises(SystemExit):
                _load_definition(path)


# ---------------------------------------------------------------------------
# _load_manifest
# ---------------------------------------------------------------------------


class TestLoadManifest(unittest.TestCase):
    def test_valid_yaml_returns_defn_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            defn, manifest = _load_manifest(path)
            self.assertEqual(defn.name, "test-wf")
            self.assertGreater(len(manifest.parallel_groups), 0)

    def test_missing_file_raises_system_exit(self) -> None:
        with self.assertRaises(SystemExit):
            _load_manifest("/no/such/wf.yaml")


# ---------------------------------------------------------------------------
# _build_resolved_params
# ---------------------------------------------------------------------------


class TestBuildResolvedParams(unittest.TestCase):
    def test_cli_params_override_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            params = _build_resolved_params(path, {"work_dir": "/custom"})
            self.assertEqual(params["work_dir"], "/custom")

    def test_work_dir_defaults_to_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            params = _build_resolved_params(path, {})
            self.assertIn("work_dir", params)
            self.assertTrue(params["work_dir"].endswith("out"))


# ---------------------------------------------------------------------------
# _cmd_parse
# ---------------------------------------------------------------------------


class TestCmdParse(unittest.TestCase):
    def test_returns_zero_on_valid_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(path=path, format="json")
            with patch("sys.stdout", io.StringIO()):
                rc = _cmd_parse(args)
            self.assertEqual(rc, 0)

    def test_outputs_workflow_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(path=path, format="json")
            out = io.StringIO()
            with patch("sys.stdout", out):
                _cmd_parse(args)
            output = out.getvalue()
            self.assertIn("test-wf", output)

    def test_returns_one_when_file_missing(self) -> None:
        args = _make_args(path="/no/such/file.yaml", format="json")
        with patch("sys.stderr", io.StringIO()):
            rc = _cmd_parse(args)
        self.assertEqual(rc, 1)

    def test_table_format_emits_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(path=path, format="table")
            out = io.StringIO()
            with patch("sys.stdout", out):
                rc = _cmd_parse(args)
            self.assertEqual(rc, 0)
            self.assertIn("name", out.getvalue())


# ---------------------------------------------------------------------------
# _cmd_lint
# ---------------------------------------------------------------------------


class TestCmdLint(unittest.TestCase):
    def test_returns_zero_on_valid_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(file=path, format="json", strict=False)
            with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
                rc = _cmd_lint(args)
            self.assertEqual(rc, 0)

    def test_returns_one_when_file_missing(self) -> None:
        args = _make_args(file="/no/such/file.yaml", format="json", strict=False)
        with patch("sys.stderr", io.StringIO()):
            rc = _cmd_lint(args)
        self.assertEqual(rc, 1)

    def test_outputs_valid_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(file=path, format="json", strict=False)
            out = io.StringIO()
            with patch("sys.stdout", out), patch("sys.stderr", io.StringIO()):
                _cmd_lint(args)
            data = json.loads(out.getvalue())
            self.assertIn("valid", data)
            self.assertTrue(data["valid"])

    def test_strict_mode_on_clean_workflow_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(file=path, format="json", strict=True)
            with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
                rc = _cmd_lint(args)
            self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# _cmd_validate_fragment
# ---------------------------------------------------------------------------


class TestCmdValidateFragment(unittest.TestCase):
    def test_returns_one_when_file_missing(self) -> None:
        args = _make_args(file="/no/such/fragment.yaml", format="json", strict=False)
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = _cmd_validate_fragment(args)
        self.assertEqual(rc, 1)
        data = json.loads(out.getvalue())
        self.assertFalse(data["valid"])

    def test_valid_fragment_returns_zero(self) -> None:
        fragment_yaml = """\
fragment: true
stages:
  - name: frag-gather
    kind: gather
    description: "Fragment gather"
    agent:
      role: researcher
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, fragment_yaml, name="frag.yaml")
            args = _make_args(file=path, format="json", strict=False)
            out = io.StringIO()
            with patch("sys.stdout", out):
                rc = _cmd_validate_fragment(args)
            self.assertEqual(rc, 0)
            data = json.loads(out.getvalue())
            self.assertTrue(data["valid"])

    def test_fragment_with_dangling_deps_strict_fails(self) -> None:
        fragment_yaml = """\
fragment: true
stages:
  - name: frag-b
    kind: propose
    description: "Needs A"
    depends_on: [frag-a]
    agent:
      role: researcher
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, fragment_yaml, name="frag.yaml")
            args = _make_args(file=path, format="json", strict=True)
            out = io.StringIO()
            with patch("sys.stdout", out):
                rc = _cmd_validate_fragment(args)
            self.assertEqual(rc, 1)

    def test_fragment_with_dangling_deps_non_strict_passes(self) -> None:
        fragment_yaml = """\
fragment: true
stages:
  - name: frag-b
    kind: propose
    description: "Needs external A"
    depends_on: [external-stage]
    agent:
      role: researcher
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, fragment_yaml, name="frag.yaml")
            args = _make_args(file=path, format="json", strict=False)
            out = io.StringIO()
            with patch("sys.stdout", out):
                rc = _cmd_validate_fragment(args)
            self.assertEqual(rc, 0)

    def test_fragment_output_includes_stage_count(self) -> None:
        fragment_yaml = """\
fragment: true
stages:
  - name: s1
    kind: gather
    description: "Stage 1"
    agent:
      role: researcher
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, fragment_yaml, name="frag.yaml")
            args = _make_args(file=path, format="json", strict=False)
            out = io.StringIO()
            with patch("sys.stdout", out):
                _cmd_validate_fragment(args)
            data = json.loads(out.getvalue())
            self.assertEqual(data["stage_count"], 1)


# ---------------------------------------------------------------------------
# _cmd_list
# ---------------------------------------------------------------------------


class TestCmdList(unittest.TestCase):
    def test_returns_one_when_no_workflows_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            args = _make_args(format="json")
            with patch("os.getcwd", return_value=tmp_dir), \
                 patch("sys.stderr", io.StringIO()):
                rc = _cmd_list(args)
            self.assertEqual(rc, 1)

    def test_returns_zero_and_lists_yaml_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            wf_dir = tmp_path / "workflows" / "code"
            wf_dir.mkdir(parents=True)
            (wf_dir / "a.yaml").write_text(_MINIMAL_YAML, encoding="utf-8")
            args = _make_args(format="json")
            out = io.StringIO()
            with patch("os.getcwd", return_value=tmp_dir), \
                 patch("sys.stdout", out):
                rc = _cmd_list(args)
            self.assertEqual(rc, 0)
            rows = json.loads(out.getvalue())
            self.assertIsInstance(rows, list)
            self.assertEqual(len(rows), 1)

    def test_parse_error_still_listed_with_error_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            wf_dir = tmp_path / "workflows"
            wf_dir.mkdir()
            (wf_dir / "broken.yaml").write_text("invalid: {{{", encoding="utf-8")
            args = _make_args(format="json")
            out = io.StringIO()
            with patch("os.getcwd", return_value=tmp_dir), \
                 patch("sys.stdout", out):
                rc = _cmd_list(args)
            self.assertEqual(rc, 0)
            rows = json.loads(out.getvalue())
            self.assertTrue(any("parse error" in r.get("description", "") for r in rows))

    def test_returns_one_when_no_yaml_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "workflows").mkdir()
            args = _make_args(format="json")
            with patch("os.getcwd", return_value=tmp_dir), \
                 patch("sys.stderr", io.StringIO()):
                rc = _cmd_list(args)
            self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# _cmd_status
# ---------------------------------------------------------------------------


class TestCmdStatus(unittest.TestCase):
    def test_returns_one_when_workspace_missing(self) -> None:
        args = _make_args(workspace_dir="/no/such/workspace", format="json")
        with patch("sys.stderr", io.StringIO()):
            rc = _cmd_status(args)
        self.assertEqual(rc, 1)

    def test_returns_one_when_no_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            args = _make_args(workspace_dir=tmp_dir, format="json")
            with patch("sys.stderr", io.StringIO()):
                rc = _cmd_status(args)
            self.assertEqual(rc, 1)

    def test_returns_zero_when_results_exist(self) -> None:
        from workflow.persistence import write_stage_result
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            result = make_stage_result(stage_name="gather", stage_index=0)
            write_stage_result(tmp_path, result)
            args = _make_args(workspace_dir=tmp_dir, format="json")
            out = io.StringIO()
            with patch("sys.stdout", out):
                rc = _cmd_status(args)
            self.assertEqual(rc, 0)
            rows = json.loads(out.getvalue())
            self.assertIsInstance(rows, list)
            self.assertEqual(rows[0]["stage"], "gather")


# ---------------------------------------------------------------------------
# _cmd_resume
# ---------------------------------------------------------------------------


class TestCmdResume(unittest.TestCase):
    def test_returns_one_when_workspace_missing(self) -> None:
        args = _make_args(workspace_dir="/no/such/workspace", format="json")
        with patch("sys.stderr", io.StringIO()):
            rc = _cmd_resume(args)
        self.assertEqual(rc, 1)

    def test_returns_one_when_no_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            args = _make_args(workspace_dir=tmp_dir, format="json")
            with patch("sys.stderr", io.StringIO()):
                rc = _cmd_resume(args)
            self.assertEqual(rc, 1)

    def test_returns_two_when_stages_pending(self) -> None:
        from workflow.persistence import write_manifest, write_stage_result
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest = make_workflow_manifest(
                parallel_groups=(("gather",), ("propose",))
            )
            write_manifest(tmp_path, manifest)
            plan = {
                "parallel_groups": [
                    {"stages": ["gather"]},
                    {"stages": ["propose"]},
                ]
            }
            (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            result = make_stage_result(stage_name="gather", stage_index=0, status=StageStatus.success)
            write_stage_result(tmp_path, result)
            args = _make_args(workspace_dir=tmp_dir, format="json")
            out = io.StringIO()
            with patch("sys.stdout", out):
                rc = _cmd_resume(args)
            self.assertEqual(rc, 2)

    def test_returns_zero_when_all_stages_done(self) -> None:
        from workflow.persistence import write_manifest, write_stage_result
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest = make_workflow_manifest(parallel_groups=(("gather",),))
            write_manifest(tmp_path, manifest)
            plan = {"parallel_groups": [{"stages": ["gather"]}]}
            (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            result = make_stage_result(stage_name="gather", stage_index=0, status=StageStatus.success)
            write_stage_result(tmp_path, result)
            args = _make_args(workspace_dir=tmp_dir, format="json")
            out = io.StringIO()
            with patch("sys.stdout", out):
                rc = _cmd_resume(args)
            self.assertEqual(rc, 0)

    def test_falls_back_to_manifest_when_no_plan(self) -> None:
        from workflow.persistence import write_manifest, write_stage_result
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest = make_workflow_manifest(parallel_groups=(("gather",),))
            write_manifest(tmp_path, manifest)
            # No plan.json — should fall back to manifest groups
            result = make_stage_result(stage_name="gather", stage_index=0, status=StageStatus.success)
            write_stage_result(tmp_path, result)
            args = _make_args(workspace_dir=tmp_dir, format="json")
            out = io.StringIO()
            with patch("sys.stdout", out):
                rc = _cmd_resume(args)
            self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# _cmd_init_workspace
# ---------------------------------------------------------------------------


class TestCmdInitWorkspace(unittest.TestCase):
    def test_returns_zero_and_prints_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(
                path=path, params=[], run_id="run-001",
                base_dir=tmp_dir, format="json",
            )
            out = io.StringIO()
            with patch("sys.stdout", out):
                rc = _cmd_init_workspace(args)
            self.assertEqual(rc, 0)
            printed = out.getvalue().strip()
            self.assertTrue(Path(printed).is_dir())

    def test_creates_manifest_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(
                path=path, params=[], run_id="run-002",
                base_dir=tmp_dir, format="json",
            )
            out = io.StringIO()
            with patch("sys.stdout", out):
                _cmd_init_workspace(args)
            workspace = Path(out.getvalue().strip())
            self.assertTrue((workspace / "manifest.json").exists())

    def test_creates_plan_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(
                path=path, params=[], run_id="run-003",
                base_dir=tmp_dir, format="json",
            )
            out = io.StringIO()
            with patch("sys.stdout", out):
                _cmd_init_workspace(args)
            workspace = Path(out.getvalue().strip())
            self.assertTrue((workspace / "plan.json").exists())

    def test_returns_one_when_file_missing(self) -> None:
        args = _make_args(
            path="/no/such/wf.yaml", params=[], run_id=None,
            base_dir="", format="json",
        )
        with patch("sys.stderr", io.StringIO()):
            rc = _cmd_init_workspace(args)
        self.assertEqual(rc, 1)

    def test_invalid_params_returns_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(
                path=path, params=["badparam"], run_id=None,
                base_dir=tmp_dir, format="json",
            )
            with patch("sys.stderr", io.StringIO()):
                rc = _cmd_init_workspace(args)
        self.assertEqual(rc, 1)

    def test_auto_generates_run_id_when_not_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(
                path=path, params=[], run_id="",
                base_dir=tmp_dir, format="json",
            )
            out = io.StringIO()
            with patch("sys.stdout", out):
                rc = _cmd_init_workspace(args)
            self.assertEqual(rc, 0)
            # Workspace should exist even with auto-generated run_id
            printed = out.getvalue().strip()
            self.assertTrue(Path(printed).is_dir())


# ---------------------------------------------------------------------------
# _cmd_run — dry-run path
# ---------------------------------------------------------------------------


class TestCmdRunDryRun(unittest.TestCase):
    def test_dry_run_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(
                path=path, params=[], execute=False,
                workspace=tmp_dir, run_id=None, format="json",
            )
            out = io.StringIO()
            with patch("sys.stdout", out), patch("sys.stderr", io.StringIO()):
                rc = _cmd_run(args)
            self.assertEqual(rc, 0)

    def test_dry_run_output_has_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(
                path=path, params=[], execute=False,
                workspace=tmp_dir, run_id=None, format="json",
            )
            out = io.StringIO()
            with patch("sys.stdout", out), patch("sys.stderr", io.StringIO()):
                _cmd_run(args)
            # Output contains multiple JSON objects; parse the first one
            decoder = json.JSONDecoder()
            output = out.getvalue()
            start = output.find("{")
            data, _ = decoder.raw_decode(output, start)
            self.assertIn("run_id", data)

    def test_dry_run_reports_dry_run_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(
                path=path, params=[], execute=False,
                workspace=tmp_dir, run_id=None, format="json",
            )
            out = io.StringIO()
            with patch("sys.stdout", out), patch("sys.stderr", io.StringIO()):
                _cmd_run(args)
            # Output contains multiple JSON objects; parse the first one
            decoder = json.JSONDecoder()
            output = out.getvalue()
            start = output.find("{")
            data, _ = decoder.raw_decode(output, start)
            self.assertTrue(data["dry_run"])

    def test_returns_one_when_file_missing(self) -> None:
        args = _make_args(
            path="/no/such.yaml", params=[], execute=False,
            workspace=None, run_id=None, format="json",
        )
        with patch("sys.stderr", io.StringIO()):
            rc = _cmd_run(args)
        self.assertEqual(rc, 1)

    def test_invalid_params_returns_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(
                path=path, params=["bad-param-no-equals"], execute=False,
                workspace=tmp_dir, run_id=None, format="json",
            )
            with patch("sys.stderr", io.StringIO()):
                rc = _cmd_run(args)
        self.assertEqual(rc, 1)

    def test_execute_with_non_interactive_stdin_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(
                path=path, params=[], execute=True,
                workspace=tmp_dir, run_id="run-xyz", format="json",
            )
            out = io.StringIO()
            err = io.StringIO()
            with patch("sys.stdout", out), \
                 patch("sys.stderr", err), \
                 patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = False
                rc = _cmd_run(args)
            self.assertIn(rc, (0, 2))

    def test_execute_aborted_when_user_says_no(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_yaml(tmp_dir, _MINIMAL_YAML)
            args = _make_args(
                path=path, params=[], execute=True,
                workspace=tmp_dir, run_id=None, format="json",
            )
            with patch("sys.stderr", io.StringIO()), \
                 patch("sys.stdin") as mock_stdin, \
                 patch("builtins.input", return_value="n"):
                mock_stdin.isatty.return_value = True
                rc = _cmd_run(args)
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
