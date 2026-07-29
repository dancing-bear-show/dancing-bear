"""Tests for workflow.parser — core parse/validation logic."""

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


if __name__ == "__main__":
    unittest.main()
