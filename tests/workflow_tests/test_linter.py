"""Tests for workflow.linter.

Covers LintResult serialisation, _compute_dag_depth, _extract_var_refs, and
lint_workflow end-to-end behaviour (happy path, file errors, parse errors,
variable-reference warnings, and CLI command validation).
"""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

import pytest

from workflow.linter import (
    LintError,
    LintResult,
    LintWarning,
    _check_fan_out_worker_queue,
    _check_inline_executor,
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


# ---------------------------------------------------------------------------
# LintError / LintWarning / LintResult dataclasses
# ---------------------------------------------------------------------------


class TestLintResultAsDict:
    def test_valid_empty_result_as_dict(self) -> None:
        r = LintResult(file="workflow.yaml")
        d = r.as_dict()
        assert d["file"] == "workflow.yaml"
        assert d["valid"] is True
        assert d["errors"] == []
        assert d["warnings"] == []
        assert d["stages"] == 0
        assert d["dag_depth"] == 0

    def test_errors_serialised(self) -> None:
        r = LintResult(file="wf.yaml", valid=False)
        r.errors.append(LintError(stage="<global>", field="file", message="not found"))
        d = r.as_dict()
        assert len(d["errors"]) == 1
        assert d["errors"][0] == {"stage": "<global>", "field": "file", "message": "not found"}

    def test_warnings_serialised(self) -> None:
        r = LintResult(file="wf.yaml")
        r.warnings.append(LintWarning(stage="gather", field="description", message="undeclared {foo}"))
        d = r.as_dict()
        assert len(d["warnings"]) == 1
        assert d["warnings"][0]["stage"] == "gather"

    def test_lint_error_is_frozen(self) -> None:
        e = LintError(stage="s", field="f", message="m")
        with pytest.raises((AttributeError, TypeError)):
            e.message = "changed"  # type: ignore[misc]

    def test_lint_warning_is_frozen(self) -> None:
        w = LintWarning(stage="s", field="f", message="m")
        with pytest.raises((AttributeError, TypeError)):
            w.message = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _extract_var_refs
# ---------------------------------------------------------------------------


class TestExtractVarRefs:
    def test_single_ref(self) -> None:
        assert _extract_var_refs("Hello {team}") == {"team"}

    def test_multiple_refs(self) -> None:
        refs = _extract_var_refs("Hello {team} and {incident_id}")
        assert refs == {"team", "incident_id"}

    def test_double_brace_excluded(self) -> None:
        assert _extract_var_refs("{{not_a_param}}") == set()

    def test_no_refs(self) -> None:
        assert _extract_var_refs("No params here") == set()

    def test_empty_string(self) -> None:
        assert _extract_var_refs("") == set()


# ---------------------------------------------------------------------------
# _compute_dag_depth
# ---------------------------------------------------------------------------


class TestComputeDagDepth:
    def _make_stages(self, names_deps: list[tuple[str, list[str]]]):
        from types import SimpleNamespace
        return tuple(
            SimpleNamespace(name=n, depends_on=d) for n, d in names_deps
        )

    def test_empty_returns_zero(self) -> None:
        assert _compute_dag_depth(()) == 0

    def test_single_stage_depth_one(self) -> None:
        stages = self._make_stages([("gather", [])])
        assert _compute_dag_depth(stages) == 1

    def test_serial_chain_depth_equals_length(self) -> None:
        stages = self._make_stages([
            ("a", []),
            ("b", ["a"]),
            ("c", ["b"]),
        ])
        assert _compute_dag_depth(stages) == 3

    def test_parallel_stages_depth_one(self) -> None:
        stages = self._make_stages([("a", []), ("b", [])])
        assert _compute_dag_depth(stages) == 1

    def test_diamond_depth_three(self) -> None:
        stages = self._make_stages([
            ("root", []),
            ("left", ["root"]),
            ("right", ["root"]),
            ("merge", ["left", "right"]),
        ])
        assert _compute_dag_depth(stages) == 3


# ---------------------------------------------------------------------------
# lint_workflow — file-level errors
# ---------------------------------------------------------------------------


class TestLintWorkflowFileErrors:
    def test_missing_file_returns_error(self, tmp_path: Path) -> None:
        result = lint_workflow(tmp_path / "does-not-exist.yaml")
        assert result.valid is False
        assert any("not found" in e.message for e in result.errors)

    def test_valid_yaml_passes(self, tmp_path: Path) -> None:
        wf = tmp_path / "wf.yaml"
        wf.write_text(_minimal_yaml(), encoding="utf-8")
        result = lint_workflow(wf)
        assert result.valid is True
        assert result.stages == 1

    def test_invalid_yaml_syntax_produces_error(self, tmp_path: Path) -> None:
        wf = tmp_path / "bad.yaml"
        wf.write_text("name: [\nbroken yaml\n", encoding="utf-8")
        result = lint_workflow(wf)
        assert result.valid is False


# ---------------------------------------------------------------------------
# lint_workflow — variable reference warnings
# ---------------------------------------------------------------------------


class TestLintWorkflowVarRefWarnings:
    def test_declared_param_no_warning(self, tmp_path: Path) -> None:
        wf = tmp_path / "wf.yaml"
        wf.write_text(_minimal_yaml(), encoding="utf-8")
        result = lint_workflow(wf)
        # {team} is declared in trigger.params so no warning expected
        assert not any("team" in w.message for w in result.warnings)

    def test_undeclared_param_produces_warning(self, tmp_path: Path) -> None:
        extra = """\
  - name: process
    kind: execute
    description: Process {undeclared_param}
    agent:
      role: researcher
    depends_on: [gather]
"""
        wf = tmp_path / "wf.yaml"
        wf.write_text(_minimal_yaml(extra=extra), encoding="utf-8")
        result = lint_workflow(wf)
        assert any("undeclared_param" in w.message for w in result.warnings)


# ---------------------------------------------------------------------------
# _check_fan_out_worker_queue
# ---------------------------------------------------------------------------


class TestCheckFanOutWorkerQueue:
    def test_worker_queue_with_empty_script_produces_error(self, tmp_path: Path) -> None:
        yaml_str = """\
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
    description: Process {team}
    depends_on: [gather]
    reads_from: [gather]
    agent:
      role: r
    fan_out:
      source: gather
      field: items
      key: team
      mode: worker_queue
"""
        wf = tmp_path / "wf.yaml"
        wf.write_text(yaml_str, encoding="utf-8")
        result = lint_workflow(wf)
        assert result.valid is False
        assert any("worker_queue" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# _check_inline_executor
# ---------------------------------------------------------------------------


class TestCheckInlineExecutor:
    def test_inline_with_fan_out_produces_error(self, tmp_path: Path) -> None:
        yaml_str = """\
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
    executor: inline
    description: Process {team}
    depends_on: [gather]
    reads_from: [gather]
    agent:
      role: r
    fan_out:
      source: gather
      field: items
      key: team
"""
        wf = tmp_path / "wf.yaml"
        wf.write_text(yaml_str, encoding="utf-8")
        result = lint_workflow(wf)
        assert result.valid is False
        assert any("inline" in e.message for e in result.errors)
