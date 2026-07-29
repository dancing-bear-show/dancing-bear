"""Tests for workflow.parser — fan_out, executor, sub-workflow, and DAG shapes."""

from __future__ import annotations

import unittest

from workflow.models import StageKind
from workflow.parser import WorkflowParseError, parse_workflow_str


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


# ---------------------------------------------------------------------------
# fan_out tests
# ---------------------------------------------------------------------------


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
# DAG shared dependency
# ---------------------------------------------------------------------------


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
