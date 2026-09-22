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
    _roles_that_cannot_write,
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


class TestRolesThatCannotWrite(unittest.TestCase):
    """_roles_that_cannot_write reads the agent definitions rather than guessing.

    Driven from a temp directory rather than the repo's real .claude/agents/, so
    these stay true when a role's frontmatter changes -- which is the whole point
    of deriving the set instead of hardcoding it.
    """

    def _agents_dir(self, tmp_dir: str, defs: dict[str, str]) -> Path:
        d = Path(tmp_dir) / "agents"
        d.mkdir()
        for name, disallowed in defs.items():
            (d / f"{name}.md").write_text(
                f"---\nname: {name}\ndisallowedTools: {disallowed}\n---\n\n# {name}\n",
                encoding="utf-8",
            )
        return d

    def test_role_disallowing_write_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = self._agents_dir(tmp_dir, {"Explore": "Agent, Edit, Write, NotebookEdit"})
            self.assertEqual(_roles_that_cannot_write(d), frozenset({"Explore"}))

    def test_role_allowing_write_is_not_reported(self) -> None:
        # The post-#392 researcher shape: Edit disallowed, Write permitted.
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = self._agents_dir(tmp_dir, {"researcher": "Edit, NotebookEdit"})
            self.assertEqual(_roles_that_cannot_write(d), frozenset())

    def test_substring_does_not_false_positive(self) -> None:
        # "NotebookEdit" contains no bare "Write", but a naive substring test on
        # a name like "WriteSomething" would match. Tokens are compared, not text.
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = self._agents_dir(tmp_dir, {"r": "NotebookEdit, WriteSomethingElse"})
            self.assertEqual(_roles_that_cannot_write(d), frozenset())

    def test_missing_directory_returns_empty(self) -> None:
        # Linting from outside a checkout must degrade to "no warnings", not raise.
        self.assertEqual(
            _roles_that_cannot_write(Path("/no/such/agents/dir")), frozenset()
        )


def _access_yaml(*, role: str, tools: str, access: str = "") -> str:
    access_line = f"      access: {access}\n" if access else ""
    return f"""\
name: access-wf
version: "1.0"
description: Test workflow
trigger:
  source: manual
stages:
  - name: work
    kind: gather
    description: Do the thing
    agent:
      role: {role}
      tools: [{tools}]
{access_line}"""


class TestCheckAgentAccess(unittest.TestCase):
    """access: is documentation, not enforcement -- the linter says so out loud."""

    def _lint(self, yaml_str: str) -> LintResult:
        with tempfile.TemporaryDirectory() as tmp_dir:
            wf = Path(tmp_dir) / "wf.yaml"
            wf.write_text(yaml_str, encoding="utf-8")
            return lint_workflow(wf)

    def _access_warnings(self, result: LintResult) -> list[LintWarning]:
        return [w for w in result.warnings if w.field == "agent.access"]

    def test_read_only_listing_write_warns(self) -> None:
        result = self._lint(
            _access_yaml(role="researcher", tools="Bash, Read, Write", access="read-only")
        )
        warnings = self._access_warnings(result)
        self.assertEqual(len(warnings), 1)
        self.assertIn("read-only", warnings[0].message)
        self.assertIn("Write", warnings[0].message)
        # A warning, never an error: 87 stages carried this shape and still ran.
        self.assertTrue(result.valid)

    def test_read_only_listing_edit_warns(self) -> None:
        result = self._lint(
            _access_yaml(role="reviewer", tools="Read, Edit", access="read-only")
        )
        self.assertEqual(len(self._access_warnings(result)), 1)

    def test_read_write_listing_write_is_clean(self) -> None:
        result = self._lint(
            _access_yaml(role="researcher", tools="Bash, Read, Write", access="read-write")
        )
        self.assertEqual(self._access_warnings(result), [])

    def test_omitted_access_does_not_warn(self) -> None:
        """A stage that declares no access: is claiming nothing.

        access defaults to read_only when the key is absent, so warning on the
        default would fire on every minimal stage in the tree -- and it broke a
        --strict lint fixture that was legitimately clean.
        """
        result = self._lint(_access_yaml(role="researcher", tools="Bash, Read"))
        self.assertEqual(self._access_warnings(result), [])

    def test_read_only_without_write_tools_is_clean(self) -> None:
        result = self._lint(
            _access_yaml(role="researcher", tools="Bash, Read", access="read-only")
        )
        self.assertEqual(self._access_warnings(result), [])

    def test_read_write_on_role_that_cannot_write_warns(self) -> None:
        """The unsatisfiable-stage case: the run stalls on a missing output.

        Explore still disallows Write, so a stage assigning it read-write is
        declaring a capability the role does not have.
        """
        result = self._lint(
            _access_yaml(role="Explore", tools="Read", access="read-write")
        )
        warnings = self._access_warnings(result)
        self.assertEqual(len(warnings), 1)
        self.assertIn("cannot produce its outputs", warnings[0].message)

    def test_warning_names_the_agent_definition_file(self) -> None:
        """The message must point at the real gate, not at the YAML."""
        result = self._lint(
            _access_yaml(role="researcher", tools="Read, Write", access="read-only")
        )
        self.assertIn(
            ".claude/agents/researcher.md", self._access_warnings(result)[0].message
        )


if __name__ == "__main__":
    unittest.main()
