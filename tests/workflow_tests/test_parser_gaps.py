"""Gap-filling tests for workflow.parser — domain rules, output checks, fan_out, executor."""

from __future__ import annotations

import unittest

from workflow.parser import WorkflowParseError, parse_workflow_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wf(stages: str) -> str:
    """Wrap a stages block into a minimal valid workflow YAML string."""
    return f"""\
name: test-wf
version: "0.1.0"
description: "Test"
trigger:
  source: manual
stages:
{stages}
"""


def _parse(stages: str) -> object:
    return parse_workflow_str(_wf(stages))


def _assert_parse_error_cases(
    test: unittest.TestCase, cases: tuple[tuple[str, str, str], ...]
) -> None:
    """Assert each (case_name, stages_yaml, expected_substring) raises WorkflowParseError."""
    for case_name, stages, expected in cases:
        with test.subTest(case_name):
            with test.assertRaises(WorkflowParseError) as ctx:
                _parse(stages)
            test.assertIn(expected, str(ctx.exception))


# ---------------------------------------------------------------------------
# _parse_trigger — error paths
# ---------------------------------------------------------------------------


class TestParseTriggerErrors(unittest.TestCase):
    def test_trigger_params_non_dict_raises(self) -> None:
        yaml = """\
name: wf
version: "0.1"
description: "t"
trigger:
  source: manual
  params: [a, b]
stages:
  - name: g
    kind: gather
    description: d
    agent:
      role: researcher
"""
        with self.assertRaises(WorkflowParseError) as ctx:
            parse_workflow_str(yaml)
        self.assertIn("params", str(ctx.exception))


# ---------------------------------------------------------------------------
# _parse_agent — error paths
# ---------------------------------------------------------------------------


class TestParseAgentErrors(unittest.TestCase):
    def test_invalid_access_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: gather
    description: d
    agent:
      role: researcher
      access: super-admin
""")
        self.assertIn("access", str(ctx.exception))

    def test_agent_tools_not_list_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: gather
    description: d
    agent:
      role: researcher
      tools: not-a-list
""")
        self.assertIn("tools", str(ctx.exception))


# ---------------------------------------------------------------------------
# _parse_output — error paths
# ---------------------------------------------------------------------------


class TestParseOutputErrors(unittest.TestCase):
    def test_output_errors_raise(self) -> None:
        cases = (
            (
                "missing_name",
                """\
  - name: s
    kind: gather
    description: d
    agent:
      role: researcher
    outputs:
      - mode: invoke
        description: no name here
""",
                "name",
            ),
            (
                "invalid_mode",
                """\
  - name: s
    kind: gather
    description: d
    agent:
      role: researcher
    outputs:
      - name: out
        mode: invalid-mode
""",
                "mode",
            ),
            (
                "input_mapping_non_dict",
                """\
  - name: s
    kind: gather
    description: d
    agent:
      role: researcher
    outputs:
      - name: out
        mode: invoke
        input_mapping: [a, b]
""",
                "input_mapping",
            ),
        )
        _assert_parse_error_cases(self, cases)


# ---------------------------------------------------------------------------
# _parse_domain_rule — error paths
# ---------------------------------------------------------------------------


class TestParseDomainRuleErrors(unittest.TestCase):
    def test_domain_rule_not_dict_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validation:
      strategy: unit
      domain_rules:
        - "just a string, not a dict"
""")
        self.assertIn("domain_rule", str(ctx.exception))

    def test_domain_rule_missing_id_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validation:
      strategy: unit
      domain_rules:
        - description: "Missing id"
""")
        self.assertIn("id", str(ctx.exception))

    def test_domain_rule_invalid_severity_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validation:
      strategy: unit
      domain_rules:
        - id: DR-001
          description: "Test"
          severity: ultra-critical
""")
        self.assertIn("severity", str(ctx.exception))

    def test_domain_rule_invalid_category_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validation:
      strategy: unit
      domain_rules:
        - id: DR-001
          description: "Test"
          category: unknown-category
""")
        self.assertIn("category", str(ctx.exception))

    def test_valid_domain_rule_parses(self) -> None:
        defn = _parse("""\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validation:
      strategy: unit
      domain_rules:
        - id: DR-001
          description: "Test rule"
          severity: critical
          category: accuracy
""")
        stage = defn.stages[0]
        self.assertEqual(len(stage.validation.domain_rules), 1)
        self.assertEqual(stage.validation.domain_rules[0].id, "DR-001")


# ---------------------------------------------------------------------------
# _parse_validation — error paths
# ---------------------------------------------------------------------------


class TestParseValidationErrors(unittest.TestCase):
    def test_validation_errors_raise(self) -> None:
        cases = (
            (
                "not_dict",
                """\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validation: "just a string"
""",
                "validation",
            ),
            (
                "missing_strategy",
                """\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validation:
      criteria: ["must be accurate"]
""",
                "strategy",
            ),
            (
                "invalid_strategy",
                """\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validation:
      strategy: galaxy-brain
""",
                "strategy",
            ),
        )
        _assert_parse_error_cases(self, cases)


# ---------------------------------------------------------------------------
# _parse_output_check — error paths
# ---------------------------------------------------------------------------


class TestParseOutputCheckErrors(unittest.TestCase):
    def test_output_check_not_dict_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validates_output:
      - "just a string"
""")
        self.assertIn("validates_output", str(ctx.exception))

    def test_output_check_missing_path_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validates_output:
      - checks: [is_json]
""")
        self.assertIn("path", str(ctx.exception))

    def test_output_check_absolute_path_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validates_output:
      - path: /absolute/path.json
        checks: [is_json]
""")
        self.assertIn("path", str(ctx.exception))

    def test_output_check_dotdot_path_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validates_output:
      - path: ../escape.json
        checks: [is_json]
""")
        self.assertIn("path", str(ctx.exception))

    def test_valid_output_check_parses(self) -> None:
        defn = _parse("""\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validates_output:
      - path: outputs/result.json
        checks: [is_json, non_empty]
""")
        stage = defn.stages[0]
        self.assertEqual(len(stage.validates_output), 1)
        self.assertEqual(stage.validates_output[0].path, "outputs/result.json")

    def test_validates_output_not_list_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: validate
    description: d
    agent:
      role: reviewer
    validates_output: "not-a-list"
""")
        self.assertIn("validates_output", str(ctx.exception))


# ---------------------------------------------------------------------------
# _parse_executor — error paths
# ---------------------------------------------------------------------------


class TestParseExecutorErrors(unittest.TestCase):
    def test_invalid_executor_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: gather
    description: d
    executor: robot
    agent:
      role: researcher
""")
        self.assertIn("executor", str(ctx.exception))

    def test_worker_queue_without_script_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: gather
    description: d
    executor: worker_queue
    agent:
      role: researcher
""")
        self.assertIn("script", str(ctx.exception))

    def test_worker_queue_with_script_parses(self) -> None:
        defn = _parse("""\
  - name: s
    kind: gather
    description: d
    executor: worker_queue
    script: ./bin/worker run
    agent:
      role: researcher
""")
        self.assertEqual(defn.stages[0].executor, "worker_queue")

    def test_inline_executor_without_agent_parses(self) -> None:
        defn = _parse("""\
  - name: s
    kind: gather
    description: d
    executor: inline
    script: ./bin/run.sh
""")
        self.assertEqual(defn.stages[0].executor, "inline")


# ---------------------------------------------------------------------------
# _parse_stage — sub_workflow validation
# ---------------------------------------------------------------------------


class TestParseStageSubWorkflow(unittest.TestCase):
    def test_sub_workflow_kind_without_path_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: sub-workflow
    description: d
    agent:
      role: researcher
""")
        self.assertIn("sub_workflow", str(ctx.exception))

    def test_sub_workflow_path_on_wrong_kind_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            _parse("""\
  - name: s
    kind: gather
    description: d
    sub_workflow: workflows/other.yaml
    agent:
      role: researcher
""")
        self.assertIn("sub_workflow", str(ctx.exception))

    def test_valid_sub_workflow_parses(self) -> None:
        defn = _parse("""\
  - name: s
    kind: sub-workflow
    description: d
    sub_workflow: workflows/sub.yaml
    agent:
      role: researcher
""")
        self.assertEqual(defn.stages[0].sub_workflow, "workflows/sub.yaml")


# ---------------------------------------------------------------------------
# _parse_fan_out — error paths
# ---------------------------------------------------------------------------


class TestParseFanOutErrors(unittest.TestCase):
    def test_fan_out_errors_raise(self) -> None:
        cases = (
            (
                "not_dict",
                """\
  - name: s
    kind: gather
    description: d
    agent:
      role: researcher
    fan_out: "not a dict"
""",
                "fan_out",
            ),
            (
                "missing_source",
                """\
  - name: s
    kind: gather
    description: d
    agent:
      role: researcher
    fan_out:
      field: items
      key: name
""",
                "source",
            ),
            (
                "invalid_mode",
                """\
  - name: s
    kind: gather
    description: d
    agent:
      role: researcher
    fan_out:
      source: outputs/data.json
      field: items
      key: name
      mode: turbo
""",
                "mode",
            ),
        )
        _assert_parse_error_cases(self, cases)


# ---------------------------------------------------------------------------
# parse_workflow_str — top-level validation errors
# ---------------------------------------------------------------------------


class TestParseWorkflowStrErrors(unittest.TestCase):
    def test_invalid_yaml_raises_parse_error(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            parse_workflow_str("{invalid yaml {{{{")
        self.assertIn("invalid YAML", str(ctx.exception))

    def test_yaml_not_mapping_raises_parse_error(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            parse_workflow_str("- just a list\n")
        self.assertIn("mapping", str(ctx.exception))

    def test_missing_required_key_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            parse_workflow_str("name: wf\nversion: '0.1'\n")
        self.assertIn("missing required key", str(ctx.exception))

    def test_stages_empty_list_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            parse_workflow_str("""\
name: wf
version: "0.1"
description: d
trigger:
  source: manual
stages: []
""")
        self.assertIn("stages", str(ctx.exception))

    def test_include_not_list_raises(self) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            parse_workflow_str("""\
name: wf
version: "0.1"
description: d
trigger:
  source: manual
include: "not-a-list"
stages:
  - name: g
    kind: gather
    description: d
    agent:
      role: researcher
""")
        self.assertIn("include", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
