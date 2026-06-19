"""Tests for workflow.parser — YAML loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow.models import OutputMode, StageKind
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


class TestParseFromString:
    """parse_workflow_str() with minimal valid YAML."""

    def test_returns_workflow_definition(self) -> None:
        wf = parse_workflow_str(_minimal_yaml())
        assert wf.name == "minimal"

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
        assert isinstance(wf.version, str)

    def test_custom_source_in_error_messages(self) -> None:
        bad_yaml = "name: only-name\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        with pytest.raises(WorkflowParseError, match="my-source"):
            parse_workflow_str(bad_yaml, source="my-source")


class TestDefaults:
    """Minimal YAML verifies default field values."""

    def setup_method(self) -> None:
        self.wf = parse_workflow_str(_minimal_yaml())
        self.stage = self.wf.stages[0]

    def test_stage_depends_on_empty(self) -> None:
        assert self.stage.depends_on == ()

    def test_stage_reads_from_empty(self) -> None:
        assert self.stage.reads_from == ()

    def test_stage_validation_none(self) -> None:
        assert self.stage.validation is None

    def test_stage_human_gate_false(self) -> None:
        assert self.stage.human_gate is False

    def test_stage_required_true(self) -> None:
        assert self.stage.required is True

    def test_workspace_dir_none(self) -> None:
        assert self.wf.workspace_dir is None

    def test_metadata_empty(self) -> None:
        assert self.wf.metadata == {}


# ---------------------------------------------------------------------------
# Validation errors — parametrized
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "yaml_str,match",
    [
        # Missing required top-level key: name
        pytest.param(
            "version: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n",
            "missing required key 'name'",
            id="missing-name",
        ),
        # Missing stages key entirely
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n",
            "missing required key 'stages'",
            id="missing-stages-key",
        ),
        # Duplicate stage names
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
            "  - name: dup\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
            "  - name: dup\n    kind: gather\n    description: d\n    agent:\n      role: r\n",
            "duplicate stage name 'dup'",
            id="duplicate-stage-names",
        ),
        # Dangling depends_on
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
            "  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n    depends_on: [ghost]\n",
            "depends_on unknown stage 'ghost'",
            id="dangling-depends-on",
        ),
        # Dangling reads_from
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
            "  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n    reads_from: [ghost]\n",
            "reads_from unknown stage 'ghost'",
            id="dangling-reads-from",
        ),
        # Cycle A→B→C→A
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
            "  - name: a\n    kind: gather\n    description: d\n    agent:\n      role: r\n    depends_on: [c]\n"
            "  - name: b\n    kind: gather\n    description: d\n    agent:\n      role: r\n    depends_on: [a]\n"
            "  - name: c\n    kind: gather\n    description: d\n    agent:\n      role: r\n    depends_on: [b]\n",
            "cycle",
            id="cycle-abc",
        ),
        # Self-dependency
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
            "  - name: self\n    kind: gather\n    description: d\n    agent:\n      role: r\n    depends_on: [self]\n",
            "cycle",
            id="self-dependency",
        ),
        # Invalid stage kind
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
            "  - name: s\n    kind: bogus\n    description: d\n    agent:\n      role: r\n",
            "invalid kind 'bogus'",
            id="invalid-stage-kind",
        ),
        # Invalid output mode
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
            "  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
            "    outputs:\n      - name: o\n        mode: bogus\n",
            "invalid mode 'bogus'",
            id="invalid-output-mode",
        ),
        # Invalid validation strategy
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages:\n"
            "  - name: s\n    kind: validate\n    description: d\n    agent:\n      role: r\n"
            "    validation:\n      strategy: bogus\n",
            "invalid strategy 'bogus'",
            id="invalid-validation-strategy",
        ),
    ],
)
def test_validation_errors(yaml_str: str, match: str) -> None:
    with pytest.raises(WorkflowParseError, match=match):
        parse_workflow_str(yaml_str)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_stages_list_raises(self) -> None:
        """stages: [] is rejected — must be a non-empty list."""
        yaml_str = "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\nstages: []\n"
        with pytest.raises(WorkflowParseError, match="non-empty"):
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
        assert isinstance(wf.version, str)
        assert wf.version == "1.0"

    def test_minimal_stage_all_defaults(self) -> None:
        """A stage with only the four required fields gets all defaults."""
        wf = parse_workflow_str(_minimal_yaml())
        stage = wf.stages[0]
        assert stage.kind == StageKind.gather
        assert stage.depends_on == ()
        assert stage.outputs == ()
        assert stage.validation is None
        assert stage.human_gate is False
        assert stage.required is True
        assert stage.reads_from == ()
        assert stage.writes_to == ()

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(WorkflowParseError, match="file not found"):
            parse_workflow(tmp_path / "nonexistent.yaml")


# ---------------------------------------------------------------------------
# reads_from ordering validation
# ---------------------------------------------------------------------------


class TestReadsFromOrdering:
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
        assert wf.stages[1].reads_from == ("gather",)

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
        with pytest.raises(WorkflowParseError, match="reads_from 'gather-b'.*not a transitive dependency"):
            parse_workflow_str(yaml_str)


# ---------------------------------------------------------------------------
# Malformed sub-structure parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "yaml_str,match",
    [
        # trigger not a mapping
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger: a-string\n"
            "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n",
            "trigger.*mapping",
            id="trigger-not-a-dict",
        ),
        # trigger missing 'source'
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  params: {}\n"
            "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n",
            "trigger missing required key 'source'",
            id="trigger-missing-source",
        ),
        # agent not a mapping
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
            "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent: not-a-dict\n",
            "agent.*mapping",
            id="agent-not-a-dict",
        ),
        # agent missing 'role'
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
            "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      model: foo\n",
            "agent missing required key 'role'",
            id="agent-missing-role",
        ),
        # output entry not a mapping
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
            "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
            "    outputs:\n      - just-a-string\n",
            "output entry must be a mapping",
            id="output-not-a-dict",
        ),
        # output missing 'name'
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
            "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
            "    outputs:\n      - mode: generate\n",
            "output missing required key 'name'",
            id="output-missing-name",
        ),
        # output missing 'mode'
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
            "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
            "    outputs:\n      - name: out\n",
            "output 'out' missing required key 'mode'",
            id="output-missing-mode",
        ),
        # validation not a mapping
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
            "stages:\n  - name: s\n    kind: validate\n    description: d\n    agent:\n      role: r\n"
            "    validation: a-string\n",
            "validation.*mapping",
            id="validation-not-a-dict",
        ),
        # validation missing 'strategy'
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
            "stages:\n  - name: s\n    kind: validate\n    description: d\n    agent:\n      role: r\n"
            "    validation:\n      criteria: [some criterion]\n",
            "validation missing required key 'strategy'",
            id="validation-missing-strategy",
        ),
        # stage not a mapping
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
            "stages:\n  - just-a-string\n",
            "stage entry must be a mapping",
            id="stage-not-a-dict",
        ),
        # stage missing 'name'
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
            "stages:\n  - kind: gather\n    description: d\n    agent:\n      role: r\n",
            "stage missing required key 'name'",
            id="stage-missing-name",
        ),
        # stage missing 'kind'
        pytest.param(
            "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
            "stages:\n  - name: s\n    description: d\n    agent:\n      role: r\n",
            "stage missing required key 'kind'",
            id="stage-missing-kind",
        ),
    ],
)
def test_malformed_sub_structures(yaml_str: str, match: str) -> None:
    """Malformed sub-structures raise WorkflowParseError."""
    with pytest.raises(WorkflowParseError, match=match):
        parse_workflow_str(yaml_str)


def test_non_mapping_top_level_raises() -> None:
    """A YAML string that is not a mapping at top level raises WorkflowParseError."""
    with pytest.raises(WorkflowParseError, match="expected a YAML mapping"):
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


def test_fan_out_default_mode_is_agent() -> None:
    defn = parse_workflow_str(_fan_out_two_stage_yaml())
    fan_stage = next(s for s in defn.stages if s.name == "fan-stage")
    assert fan_stage.fan_out is not None
    assert fan_stage.fan_out.mode == "agent"


def test_fan_out_worker_queue_mode() -> None:
    extra = "      mode: worker_queue\n      script: ./bin/mail-assistant filters apply --team {team}\n"
    defn = parse_workflow_str(_fan_out_two_stage_yaml(extra))
    fan_stage = next(s for s in defn.stages if s.name == "fan-stage")
    assert fan_stage.fan_out is not None
    assert fan_stage.fan_out.mode == "worker_queue"
    assert "{team}" in fan_stage.fan_out.script


def test_fan_out_script_defaults_empty() -> None:
    defn = parse_workflow_str(_fan_out_two_stage_yaml())
    fan_stage = next(s for s in defn.stages if s.name == "fan-stage")
    assert fan_stage.fan_out is not None
    assert fan_stage.fan_out.script == ""


def test_fan_out_invalid_mode_raises() -> None:
    extra = "      mode: batch\n"
    with pytest.raises(WorkflowParseError, match="invalid mode 'batch'"):
        parse_workflow_str(_fan_out_two_stage_yaml(extra))


@pytest.mark.parametrize(
    "fan_out_yaml,match",
    [
        pytest.param(
            "    fan_out:\n      field: items\n      key: id\n",
            "fan_out missing required key 'source'",
            id="fan-out-missing-source",
        ),
        pytest.param(
            "    fan_out:\n      source: gather-stage\n      key: id\n",
            "fan_out missing required key 'field'",
            id="fan-out-missing-field",
        ),
        pytest.param(
            "    fan_out:\n      source: gather-stage\n      field: items\n",
            "fan_out missing required key 'key'",
            id="fan-out-missing-key",
        ),
    ],
)
def test_fan_out_missing_required_keys(fan_out_yaml: str, match: str) -> None:
    yaml_str = (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
        + fan_out_yaml
    )
    with pytest.raises(WorkflowParseError, match=match):
        parse_workflow_str(yaml_str)


def test_fan_out_not_a_mapping_raises() -> None:
    yaml_str = (
        "name: n\nversion: '1'\ndescription: d\ntrigger:\n  source: x\n"
        "stages:\n  - name: s\n    kind: gather\n    description: d\n    agent:\n      role: r\n"
        "    fan_out: a-string\n"
    )
    with pytest.raises(WorkflowParseError, match="fan_out must be a mapping"):
        parse_workflow_str(yaml_str)


# ---------------------------------------------------------------------------
# executor tests
# ---------------------------------------------------------------------------


def test_executor_inline_parses_correctly() -> None:
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
    assert wf.stages[0].executor == "inline"


def test_executor_inline_agent_block_optional() -> None:
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
    assert wf.stages[0].executor == "inline"
    assert wf.stages[0].agent.role == "inline"


def test_executor_agent_default() -> None:
    wf = parse_workflow_str(_minimal_yaml())
    assert wf.stages[0].executor == "agent"


def test_executor_invalid_value_raises() -> None:
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
    with pytest.raises(WorkflowParseError, match="invalid executor 'lambda'"):
        parse_workflow_str(yaml_str)


# ---------------------------------------------------------------------------
# sub_workflow field validation
# ---------------------------------------------------------------------------


def test_parse_stage_sub_workflow_kind_missing_path() -> None:
    from workflow.parser import _parse_stage

    stage_data: dict[str, object] = {
        "name": "my-sub",
        "kind": "sub-workflow",
        "description": "test",
        "agent": {"role": "researcher", "model": "sonnet", "tools": [], "access": "read-only"},
    }
    with pytest.raises(WorkflowParseError, match="missing or empty 'sub_workflow' path"):
        _parse_stage(stage_data, source="test.yaml")


def test_parse_stage_sub_workflow_happy_path() -> None:
    from workflow.parser import _parse_stage

    stage_data: dict[str, object] = {
        "name": "my-sub",
        "kind": "sub-workflow",
        "description": "Delegates to a child workflow",
        "agent": {"role": "researcher", "model": "sonnet", "tools": [], "access": "read-only"},
        "sub_workflow": "workflows/sub.yaml",
    }
    stage = _parse_stage(stage_data, source="test.yaml")
    assert stage.sub_workflow == "workflows/sub.yaml"
    assert stage.kind == StageKind.sub_workflow


def test_validate_dag_shared_dependency_does_not_raise() -> None:
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
    assert len(wf.stages) == 4
