"""Tests for workflow.parser — YAML loading and validation.

Split versions of these tests live in:
  - test_parser_core.py   (parse, defaults, validation errors, edge cases, malformed sub-structures)
  - test_parser_fanout.py (fan_out, executor, sub_workflow, DAG shapes)
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.models import StageKind
from workflow.parser import WorkflowParseError, parse_workflow, parse_workflow_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_yaml(*, extra_stages: str = "") -> str:
    """Return a minimal valid workflow YAML string."""
    return f"""\
name: minimal
version: "0.1"
description: A minimal workflow
trigger:
  source: manual
stages:
  - name: stage-a
    kind: gather
    description: First stage
    agent:
      role: researcher
{extra_stages}
"""


# ---------------------------------------------------------------------------
# Happy path — parse from string
# ---------------------------------------------------------------------------


class TestParseFromString(unittest.TestCase):
    """parse_workflow_str() with minimal valid YAML."""

    def test_returns_workflow_definition(self) -> None:
        wf = parse_workflow_str(_minimal_yaml())
        self.assertEqual(wf.name, "minimal")

    def test_version_coerced_to_string(self) -> None:
        yaml_str = """\
name: test
version: "0.1"
description: desc
trigger:
  source: manual
stages:
  - name: s
    kind: gather
    description: d
    agent:
      role: researcher
"""
        wf = parse_workflow_str(yaml_str)
        self.assertIsInstance(wf.version, str)

    def test_custom_source_in_error_messages(self) -> None:
        bad_yaml = "name: only-name\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        with self.assertRaisesRegex(WorkflowParseError, "my-source"):
            parse_workflow_str(bad_yaml, source="my-source")


class TestDefaults(unittest.TestCase):
    """Minimal YAML verifies default field values."""

    def setUp(self) -> None:
        self.wf = parse_workflow_str(_minimal_yaml())
        self.stage = self.wf.stages[0]

    def test_stage_depends_on_empty(self) -> None:
        self.assertEqual(self.stage.depends_on, ())

    def test_stage_reads_from_empty(self) -> None:
        self.assertEqual(self.stage.reads_from, ())

    def test_stage_validation_none(self) -> None:
        self.assertIsNone(self.stage.validation)

    def test_stage_human_gate_false(self) -> None:
        self.assertIs(self.stage.human_gate, False)

    def test_stage_required_true(self) -> None:
        self.assertIs(self.stage.required, True)

    def test_workspace_dir_none(self) -> None:
        self.assertIsNone(self.wf.workspace_dir)

    def test_metadata_empty(self) -> None:
        self.assertEqual(self.wf.metadata, {})


# ---------------------------------------------------------------------------
# Validation errors — parametrized via subTest
# ---------------------------------------------------------------------------


_VALIDATION_ERROR_CASES = [
    (
        "version: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n",
        "missing required key 'name'",
        "missing-name",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n",
        "missing required key 'stages'",
        "missing-stages-key",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
        "  - name: dup\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
        "  - name: dup\n    kind: gather\n    description: d\n    agent:\n      role: r\n",
        "duplicate stage name 'dup'",
        "duplicate-stage-names",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
        "  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n    depends_on: [ghost]\n",
        "depends_on unknown stage 'ghost'",
        "dangling-depends-on",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
        "  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n    reads_from: [ghost]\n",
        "reads_from unknown stage 'ghost'",
        "dangling-reads-from",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
        "  - name: a\n    kind: gather\n    description: d\n    agent:\n      role: r\n    depends_on: [c]\n"
        "  - name: b\n    kind: gather\n    description: d\n    agent:\n      role: r\n    depends_on: [a]\n"
        "  - name: c\n    kind: gather\n    description: d\n    agent:\n      role: r\n    depends_on: [b]\n",
        "cycle",
        "cycle-abc",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
        "  - name: self\n    kind: gather\n    description: d\n    agent:\n      role: r\n    depends_on: [self]\n",
        "cycle",
        "self-dependency",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
        "  - name: s\n    kind: bogus\n    description: d\n    agent:\n      role: r\n",
        "invalid kind 'bogus'",
        "invalid-stage-kind",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
        "  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
        "    outputs:\n      - name: o\n        mode: bogus\n",
        "invalid mode 'bogus'",
        "invalid-output-mode",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
        "  - name: s\n    kind: validate\n    description: d\n    agent:\n      role: r\n"
        "    validation:\n      strategy: bogus\n",
        "invalid strategy 'bogus'",
        "invalid-validation-strategy",
    ),
]


class TestValidationErrors(unittest.TestCase):
    def test_all_validation_errors(self) -> None:
        for yaml_str, match, case_id in _VALIDATION_ERROR_CASES:
            with self.subTest(id=case_id):
                with self.assertRaises(WorkflowParseError) as ctx:
                    parse_workflow_str(yaml_str)
                self.assertRegex(str(ctx.exception), match)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    def test_empty_stages_list_raises(self) -> None:
        """stages: [] is rejected — must be a non-empty list."""
        yaml_str = "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages: []\n"
        with self.assertRaisesRegex(WorkflowParseError, "non-empty"):
            parse_workflow_str(yaml_str)

    def test_version_as_number_coerced_to_string(self) -> None:
        """YAML parses version: 1.0 as float; parser should coerce to str."""
        yaml_str = """\
name: n
version: 1.0
description: d
trigger:
  source: x
stages:
  - name: s
    kind: gather
    description: d
    agent:
      role: researcher
"""
        wf = parse_workflow_str(yaml_str)
        self.assertIsInstance(wf.version, str)
        self.assertEqual(wf.version, "1.0")

    def test_minimal_stage_all_defaults(self) -> None:
        """A stage with only the four required fields gets all defaults."""
        wf = parse_workflow_str(_minimal_yaml())
        stage = wf.stages[0]
        self.assertEqual(stage.kind, StageKind.gather)
        self.assertEqual(stage.depends_on, ())
        self.assertEqual(stage.outputs, ())
        self.assertIsNone(stage.validation)
        self.assertIs(stage.human_gate, False)
        self.assertIs(stage.required, True)
        self.assertEqual(stage.reads_from, ())
        self.assertEqual(stage.writes_to, ())

    def test_file_not_found_raises(self) -> None:
        tmp_dir = tempfile.mkdtemp()
        with self.assertRaisesRegex(WorkflowParseError, "file not found"):
            parse_workflow(Path(tmp_dir) / "nonexistent.yaml")


# ---------------------------------------------------------------------------
# reads_from ordering validation
# ---------------------------------------------------------------------------


class TestReadsFromOrdering(unittest.TestCase):
    """reads_from entries must be transitively reachable via depends_on."""

    def test_direct_dependency_is_valid(self) -> None:
        """reads_from a direct dependency is allowed."""
        yaml_str = """\
name: n
version: '1'
description: d
trigger:
  source: x
stages:
  - name: gather
    kind: gather
    description: d
    agent:
      role: r
  - name: compose
    kind: execute
    description: d
    agent:
      role: r
    depends_on: [gather]
    reads_from: [gather]
"""
        wf = parse_workflow_str(yaml_str)
        self.assertEqual(wf.stages[1].reads_from, ("gather",))

    def test_unreachable_reads_from_raises(self) -> None:
        """reads_from a stage not in the transitive depends_on chain is rejected."""
        yaml_str = """\
name: n
version: '1'
description: d
trigger:
  source: x
stages:
  - name: gather-a
    kind: gather
    description: d
    agent:
      role: r
  - name: gather-b
    kind: gather
    description: d
    agent:
      role: r
  - name: compose
    kind: execute
    description: d
    agent:
      role: r
    depends_on: [gather-a]
    reads_from: [gather-b]
"""
        with self.assertRaisesRegex(WorkflowParseError, "reads_from 'gather-b'.*not a transitive dependency"):
            parse_workflow_str(yaml_str)


# ---------------------------------------------------------------------------
# Malformed sub-structure parsing
# ---------------------------------------------------------------------------


_MALFORMED_CASES = [
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger: a-string\n"
        "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n",
        "trigger.*mapping",
        "trigger-not-a-dict",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  params: {}\n"
        "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n",
        "trigger missing required key 'source'",
        "trigger-missing-source",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent: not-a-dict\n",
        "agent.*mapping",
        "agent-not-a-dict",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      model: foo\n",
        "agent missing required key 'role'",
        "agent-missing-role",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
        "    outputs:\n      - just-a-string\n",
        "output entry must be a mapping",
        "output-not-a-dict",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
        "    outputs:\n      - mode: generate\n",
        "output missing required key 'name'",
        "output-missing-name",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
        "    outputs:\n      - name: out\n",
        "output 'out' missing required key 'mode'",
        "output-missing-mode",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - name: s\n    kind: validate\n    description: d\n    agent:\n      role: r\n"
        "    validation: a-string\n",
        "validation.*mapping",
        "validation-not-a-dict",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - name: s\n    kind: validate\n    description: d\n    agent:\n      role: r\n"
        "    validation:\n      criteria: [some criterion]\n",
        "validation missing required key 'strategy'",
        "validation-missing-strategy",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - just-a-string\n",
        "stage entry must be a mapping",
        "stage-not-a-dict",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - kind: gather\n    description: d\n    agent:\n      role: r\n",
        "stage missing required key 'name'",
        "stage-missing-name",
    ),
    (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - name: s\n    description: d\n    agent:\n      role: r\n",
        "stage missing required key 'kind'",
        "stage-missing-kind",
    ),
]


class TestMalformedSubStructures(unittest.TestCase):
    """Malformed sub-structures raise WorkflowParseError."""

    def test_all_malformed_cases(self) -> None:
        for yaml_str, match, case_id in _MALFORMED_CASES:
            with self.subTest(id=case_id):
                with self.assertRaises(WorkflowParseError) as ctx:
                    parse_workflow_str(yaml_str)
                self.assertRegex(str(ctx.exception), match)


class TestNonMappingTopLevel(unittest.TestCase):
    def test_non_mapping_top_level_raises(self) -> None:
        """A YAML string that is not a mapping at top level raises WorkflowParseError."""
        with self.assertRaisesRegex(WorkflowParseError, "expected a YAML mapping"):
            parse_workflow_str("- item1\n- item2\n")


# ---------------------------------------------------------------------------
# fan_out tests
# ---------------------------------------------------------------------------


def _fan_out_two_stage_yaml(fan_out_extra: str = "") -> str:
    """Return a two-stage workflow YAML with fan_out on the second stage."""
    return (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n"
        "  - name: gather\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
        "    writes_to:\n      - items.json\n"
        "  - name: fan-stage\n    kind: execute\n    description: Process\n"
        "    depends_on: [gather]\n    reads_from: [gather]\n    agent:\n      role: r\n"
        "    fan_out:\n      source: gather\n      field: items\n      key: team\n"
        + fan_out_extra
    )


class TestFanOut(unittest.TestCase):
    def test_fan_out_default_mode_is_agent(self) -> None:
        defn = parse_workflow_str(_fan_out_two_stage_yaml())
        fan_stage = next(s for s in defn.stages if s.name == "fan-stage")
        self.assertIsNotNone(fan_stage.fan_out)
        self.assertEqual(fan_stage.fan_out.mode, "agent")

    def test_fan_out_worker_queue_mode(self) -> None:
        extra = "      mode: worker_queue\n      script: ./bin/mail-assistant filters apply --team {team}\n"
        defn = parse_workflow_str(_fan_out_two_stage_yaml(extra))
        fan_stage = next(s for s in defn.stages if s.name == "fan-stage")
        self.assertIsNotNone(fan_stage.fan_out)
        self.assertEqual(fan_stage.fan_out.mode, "worker_queue")
        self.assertIn("{team}", fan_stage.fan_out.script)

    def test_fan_out_script_defaults_empty(self) -> None:
        defn = parse_workflow_str(_fan_out_two_stage_yaml())
        fan_stage = next(s for s in defn.stages if s.name == "fan-stage")
        self.assertIsNotNone(fan_stage.fan_out)
        self.assertEqual(fan_stage.fan_out.script, "")

    def test_fan_out_invalid_mode_raises(self) -> None:
        extra = "      mode: batch\n"
        with self.assertRaisesRegex(WorkflowParseError, "invalid mode 'batch'"):
            parse_workflow_str(_fan_out_two_stage_yaml(extra))


_FAN_OUT_MISSING_KEY_CASES = [
    (
        "    fan_out:\n      field: items\n      key: id\n",
        "fan_out missing required key 'source'",
        "fan-out-missing-source",
    ),
    (
        "    fan_out:\n      source: gather-stage\n      key: id\n",
        "fan_out missing required key 'field'",
        "fan-out-missing-field",
    ),
    (
        "    fan_out:\n      source: gather-stage\n      field: items\n",
        "fan_out missing required key 'key'",
        "fan-out-missing-key",
    ),
]


class TestFanOutMissingRequiredKeys(unittest.TestCase):
    def test_all_missing_key_cases(self) -> None:
        for fan_out_yaml, match, case_id in _FAN_OUT_MISSING_KEY_CASES:
            yaml_str = (
                "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
                "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
                + fan_out_yaml
            )
            with self.subTest(id=case_id):
                with self.assertRaises(WorkflowParseError) as ctx:
                    parse_workflow_str(yaml_str)
                self.assertRegex(str(ctx.exception), match)

    def test_fan_out_not_a_mapping_raises(self) -> None:
        yaml_str = (
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
            "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
            "    fan_out: a-string\n"
        )
        with self.assertRaisesRegex(WorkflowParseError, "fan_out must be a mapping"):
            parse_workflow_str(yaml_str)


# ---------------------------------------------------------------------------
# executor tests
# ---------------------------------------------------------------------------


class TestExecutor(unittest.TestCase):
    def test_executor_inline_parses_correctly(self) -> None:
        yaml_str = """\
name: n
version: '1'
description: d
trigger:
  source: manual
stages:
  - name: auth-check
    kind: gather
    executor: inline
    description: Quick auth probe
    agent:
      role: researcher
"""
        wf = parse_workflow_str(yaml_str)
        self.assertEqual(wf.stages[0].executor, "inline")

    def test_executor_inline_agent_block_optional(self) -> None:
        yaml_str = """\
name: n
version: '1'
description: d
trigger:
  source: manual
stages:
  - name: auth-check
    kind: gather
    executor: inline
    description: Quick auth probe
    writes_to: []
"""
        wf = parse_workflow_str(yaml_str)
        self.assertEqual(wf.stages[0].executor, "inline")
        self.assertEqual(wf.stages[0].agent.role, "inline")

    def test_executor_agent_default(self) -> None:
        wf = parse_workflow_str(_minimal_yaml())
        self.assertEqual(wf.stages[0].executor, "agent")

    def test_executor_invalid_value_raises(self) -> None:
        yaml_str = """\
name: n
version: '1'
description: d
trigger:
  source: manual
stages:
  - name: s
    kind: gather
    executor: lambda
    description: d
    agent:
      role: researcher
"""
        with self.assertRaisesRegex(WorkflowParseError, "invalid executor 'lambda'"):
            parse_workflow_str(yaml_str)


# ---------------------------------------------------------------------------
# sub_workflow field validation
# ---------------------------------------------------------------------------


class TestSubWorkflow(unittest.TestCase):
    def test_parse_stage_sub_workflow_kind_missing_path(self) -> None:
        from workflow.parser import _parse_stage

        stage_data: dict[str, object] = {
            "name": "my-sub",
            "kind": "sub-workflow",
            "description": "test",
            "agent": {"role": "researcher", "model": "sonnet", "tools": [], "access": "read-only"},
        }
        with self.assertRaisesRegex(WorkflowParseError, "missing or empty 'sub_workflow' path"):
            _parse_stage(stage_data, source="test.yaml")

    def test_parse_stage_sub_workflow_happy_path(self) -> None:
        from workflow.parser import _parse_stage

        stage_data: dict[str, object] = {
            "name": "my-sub",
            "kind": "sub-workflow",
            "description": "Delegates to a child workflow",
            "agent": {"role": "researcher", "model": "sonnet", "tools": [], "access": "read-only"},
            "sub_workflow": "workflows/sub.yaml",
        }
        stage = _parse_stage(stage_data, source="test.yaml")
        self.assertEqual(stage.sub_workflow, "workflows/sub.yaml")
        self.assertEqual(stage.kind, StageKind.sub_workflow)


# ---------------------------------------------------------------------------
# _parse_agent — isolation field and unknown-key rejection
# ---------------------------------------------------------------------------


class TestParseAgentIsolation(unittest.TestCase):
    """Tests for _parse_agent isolation parsing and unknown-key rejection."""

    def _parse_agent(self, data: dict) -> object:
        from workflow.parser_fields import _parse_agent
        return _parse_agent(data, source="test.yaml")

    def test_unhashable_isolation_raises_parse_error(self) -> None:
        """A list/dict isolation must not escape as TypeError.

        `isolation not in _VALID_ISOLATIONS` raises TypeError on an unhashable
        YAML value, which surfaces as a traceback rather than a parse error.
        """
        from workflow.parser_errors import WorkflowParseError

        for bad in (["worktree"], {}, {"mode": "worktree"}):
            with self.subTest(value=bad):
                with self.assertRaises(WorkflowParseError) as ctx:
                    self._parse_agent({"role": "code-writer", "isolation": bad})
                self.assertIn("invalid isolation", str(ctx.exception))

    def test_non_string_isolation_raises_parse_error(self) -> None:
        from workflow.parser_errors import WorkflowParseError

        for bad in (5, True):
            with self.subTest(value=bad):
                with self.assertRaises(WorkflowParseError):
                    self._parse_agent({"role": "code-writer", "isolation": bad})

    # (b) isolation: worktree is parsed through to AgentSpec.isolation
    def test_isolation_worktree_parsed(self) -> None:
        spec = self._parse_agent({"role": "code-writer", "isolation": "worktree"})
        self.assertEqual(spec.isolation, "worktree")

    # (c) isolation absent — defaults to None
    def test_isolation_absent_defaults_to_none(self) -> None:
        spec = self._parse_agent({"role": "researcher"})
        self.assertIsNone(spec.isolation)

    # (d) invalid isolation value raises with message naming valid option
    def test_invalid_isolation_raises(self) -> None:
        with self.assertRaises(Exception) as ctx:
            self._parse_agent({"role": "researcher", "isolation": "sandbox"})
        msg = str(ctx.exception)
        self.assertIn("sandbox", msg)
        self.assertIn("worktree", msg)

    # (e) unknown agent key raises — realistic typo "isolaton" (missing 'i')
    def test_unknown_key_typo_raises(self) -> None:
        with self.assertRaises(Exception) as ctx:
            self._parse_agent({"role": "code-writer", "isolaton": "worktree"})
        msg = str(ctx.exception)
        self.assertIn("isolaton", msg)

    # (e) a completely foreign unknown key also raises
    def test_unknown_key_raises_naming_key(self) -> None:
        with self.assertRaises(Exception) as ctx:
            self._parse_agent({"role": "researcher", "timeout": "30s"})
        msg = str(ctx.exception)
        self.assertIn("timeout", msg)

    # (f) all four previously-valid keys still parse without raising
    def test_role_only_parses(self) -> None:
        spec = self._parse_agent({"role": "researcher"})
        self.assertEqual(spec.role, "researcher")

    def test_model_key_parses(self) -> None:
        spec = self._parse_agent({"role": "code-writer", "model": "sonnet"})
        self.assertEqual(spec.model, "sonnet")

    def test_tools_key_parses(self) -> None:
        spec = self._parse_agent({"role": "reviewer", "tools": ["Read", "Bash"]})
        self.assertEqual(spec.tools, ("Read", "Bash"))

    def test_access_key_parses(self) -> None:
        spec = self._parse_agent({"role": "code-writer", "access": "read-write"})
        self.assertEqual(spec.access.value, "read-write")

    # (h) end-to-end: workflow YAML with agent.isolation: worktree parses correctly
    def test_e2e_isolation_worktree_in_yaml(self) -> None:
        yaml_str = """\
name: iso-test
version: "0.1"
description: Isolation round-trip test
trigger:
  source: manual
stages:
  - name: write-stage
    kind: execute
    description: Isolated code-writer stage
    agent:
      role: code-writer
      isolation: worktree
"""
        wf = parse_workflow_str(yaml_str)
        self.assertEqual(len(wf.stages), 1)
        self.assertEqual(wf.stages[0].agent.isolation, "worktree")

    # (h) stage without isolation key yields isolation=None end-to-end
    def test_e2e_isolation_absent_in_yaml(self) -> None:
        wf = parse_workflow_str(_minimal_yaml())
        self.assertIsNone(wf.stages[0].agent.isolation)


class TestDagSharedDependency(unittest.TestCase):
    def test_validate_dag_shared_dependency_does_not_raise(self) -> None:
        yaml_str = """\
name: n
version: '1'
description: d
trigger:
  source: x
stages:
  - name: merge
    kind: execute
    description: d
    agent:
      role: r
    depends_on: [branch-a, branch-b]
  - name: branch-a
    kind: gather
    description: d
    agent:
      role: r
    depends_on: [shared]
  - name: branch-b
    kind: gather
    description: d
    agent:
      role: r
    depends_on: [shared]
  - name: shared
    kind: gather
    description: d
    agent:
      role: r
"""
        wf = parse_workflow_str(yaml_str)
        self.assertEqual(len(wf.stages), 4)


if __name__ == "__main__":
    unittest.main()
