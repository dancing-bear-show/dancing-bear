"""Tests for workflow.linter.

Covers LintResult serialisation, _compute_dag_depth, _extract_var_refs, and
lint_workflow end-to-end behaviour (happy path, file errors, parse errors,
variable-reference warnings, and CLI command validation).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.linter import (
    LintError,
    LintResult,
    LintWarning,
    _compute_dag_depth,
    _extract_var_refs,
    lint_workflow,
)


# ---------------------------------------------------------------------------
# Minimal workflow YAML helpers
# ---------------------------------------------------------------------------


def _minimal_yaml(*, name: str = "test-wf", extra: str = "") -> str:
    return f"""\
name: {name}
version: "1.0"
description: Test workflow
trigger:
  source: manual
  params:
    team: my-team
stages:
  - name: gather
    kind: gather
    description: Gather data for {{team}}
    agent:
      role: researcher
{extra}
"""


def _fan_out_workflow_yaml(*, executor_line: str = "", mode_line: str = "") -> str:
    """A gather stage feeding a fan-stage, with optional executor/mode lines."""
    return f"""\
name: n
version: "1.0"
description: d
trigger:
  source: manual
stages:
  - name: gather
    kind: gather
    description: d
    agent:
      role: r
    writes_to:
      - items.json
  - name: fan-stage
    kind: execute
{executor_line}    description: Process {{team}}
    depends_on: [gather]
    reads_from: [gather]
    agent:
      role: r
    fan_out:
      source: gather
      field: items
      key: team
{mode_line}"""


# ---------------------------------------------------------------------------
# LintError / LintWarning / LintResult dataclasses
# ---------------------------------------------------------------------------


class TestLintResultAsDict(unittest.TestCase):
    def test_valid_empty_result_as_dict(self) -> None:
        r = LintResult(file="workflow.yaml")
        d = r.as_dict()
        self.assertEqual(d["file"], "workflow.yaml")
        self.assertIs(d["valid"], True)
        self.assertEqual(d["errors"], [])
        self.assertEqual(d["warnings"], [])
        self.assertEqual(d["stages"], 0)
        self.assertEqual(d["dag_depth"], 0)

    def test_errors_serialised(self) -> None:
        r = LintResult(file="wf.yaml", valid=False)
        r.errors.append(LintError(stage="<global>", field="file", message="not found"))
        d = r.as_dict()
        self.assertEqual(len(d["errors"]), 1)
        self.assertEqual(d["errors"][0], {"stage": "<global>", "field": "file", "message": "not found"})

    def test_warnings_serialised(self) -> None:
        r = LintResult(file="wf.yaml")
        r.warnings.append(LintWarning(stage="gather", field="description", message="undeclared {foo}"))
        d = r.as_dict()
        self.assertEqual(len(d["warnings"]), 1)
        self.assertEqual(d["warnings"][0]["stage"], "gather")

    def test_lint_error_is_frozen(self) -> None:
        e = LintError(stage="s", field="f", message="m")
        with self.assertRaises((AttributeError, TypeError)):
            e.message = "changed"  # type: ignore[misc]

    def test_lint_warning_is_frozen(self) -> None:
        w = LintWarning(stage="s", field="f", message="m")
        with self.assertRaises((AttributeError, TypeError)):
            w.message = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _extract_var_refs
# ---------------------------------------------------------------------------


class TestExtractVarRefs(unittest.TestCase):
    def test_single_ref(self) -> None:
        self.assertEqual(_extract_var_refs("Hello {team}"), {"team"})

    def test_multiple_refs(self) -> None:
        refs = _extract_var_refs("Hello {team} and {incident_id}")
        self.assertEqual(refs, {"team", "incident_id"})

    def test_double_brace_excluded(self) -> None:
        self.assertEqual(_extract_var_refs("{{not_a_param}}"), set())

    def test_no_refs(self) -> None:
        self.assertEqual(_extract_var_refs("No params here"), set())

    def test_empty_string(self) -> None:
        self.assertEqual(_extract_var_refs(""), set())


# ---------------------------------------------------------------------------
# _compute_dag_depth
# ---------------------------------------------------------------------------


class TestComputeDagDepth(unittest.TestCase):
    def _make_stages(self, names_deps: list[tuple[str, list[str]]]):
        from types import SimpleNamespace
        return tuple(
            SimpleNamespace(name=n, depends_on=d) for n, d in names_deps
        )

    def test_empty_returns_zero(self) -> None:
        self.assertEqual(_compute_dag_depth(()), 0)

    def test_single_stage_depth_one(self) -> None:
        stages = self._make_stages([("gather", [])])
        self.assertEqual(_compute_dag_depth(stages), 1)

    def test_serial_chain_depth_equals_length(self) -> None:
        stages = self._make_stages([
            ("a", []),
            ("b", ["a"]),
            ("c", ["b"]),
        ])
        self.assertEqual(_compute_dag_depth(stages), 3)

    def test_parallel_stages_depth_one(self) -> None:
        stages = self._make_stages([("a", []), ("b", [])])
        self.assertEqual(_compute_dag_depth(stages), 1)

    def test_diamond_depth_three(self) -> None:
        stages = self._make_stages([
            ("root", []),
            ("left", ["root"]),
            ("right", ["root"]),
            ("merge", ["left", "right"]),
        ])
        self.assertEqual(_compute_dag_depth(stages), 3)


# ---------------------------------------------------------------------------
# lint_workflow — file-level errors
# ---------------------------------------------------------------------------


class TestLintWorkflowFileErrors(unittest.TestCase):
    def test_missing_file_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = lint_workflow(Path(tmp_dir) / "does-not-exist.yaml")
            self.assertFalse(result.valid)
            self.assertTrue(any("not found" in e.message for e in result.errors))

    def test_valid_yaml_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf = Path(tmp_dir) / "wf.yaml"
            wf.write_text(_minimal_yaml(), encoding="utf-8")
            result = lint_workflow(wf)
            self.assertTrue(result.valid)
            self.assertEqual(result.stages, 1)

    def test_invalid_yaml_syntax_produces_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf = Path(tmp_dir) / "bad.yaml"
            wf.write_text("name: [\nbroken yaml\n", encoding="utf-8")
            result = lint_workflow(wf)
            self.assertFalse(result.valid)


# ---------------------------------------------------------------------------
# lint_workflow — variable reference warnings
# ---------------------------------------------------------------------------


class TestLintWorkflowVarRefWarnings(unittest.TestCase):
    def test_declared_param_no_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf = Path(tmp_dir) / "wf.yaml"
            wf.write_text(_minimal_yaml(), encoding="utf-8")
            result = lint_workflow(wf)
            # {team} is declared in trigger.params so no warning expected
            self.assertFalse(any("team" in w.message for w in result.warnings))

    def test_undeclared_param_produces_warning(self) -> None:
        extra = """\
  - name: process
    kind: execute
    description: Process {undeclared_param}
    agent:
      role: researcher
    depends_on: [gather]
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf = Path(tmp_dir) / "wf.yaml"
            wf.write_text(_minimal_yaml(extra=extra), encoding="utf-8")
            result = lint_workflow(wf)
            self.assertTrue(any("undeclared_param" in w.message for w in result.warnings))


# ---------------------------------------------------------------------------
# _check_fan_out_worker_queue
# ---------------------------------------------------------------------------


class TestCheckFanOutWorkerQueue(unittest.TestCase):
    def test_worker_queue_with_empty_script_produces_error(self) -> None:
        yaml_str = _fan_out_workflow_yaml(mode_line="      mode: worker_queue\n")
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf = Path(tmp_dir) / "wf.yaml"
            wf.write_text(yaml_str, encoding="utf-8")
            result = lint_workflow(wf)
            self.assertFalse(result.valid)
            self.assertTrue(any("worker_queue" in e.message for e in result.errors))


# ---------------------------------------------------------------------------
# _check_inline_executor
# ---------------------------------------------------------------------------


class TestCheckInlineExecutor(unittest.TestCase):
    def test_inline_with_fan_out_produces_error(self) -> None:
        yaml_str = _fan_out_workflow_yaml(executor_line="    executor: inline\n")
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf = Path(tmp_dir) / "wf.yaml"
            wf.write_text(yaml_str, encoding="utf-8")
            result = lint_workflow(wf)
            self.assertFalse(result.valid)
            self.assertTrue(any("inline" in e.message for e in result.errors))


if __name__ == "__main__":
    unittest.main()
