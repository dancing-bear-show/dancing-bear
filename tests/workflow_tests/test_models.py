"""Unit tests for workflow.models.

Covers enums, frozen-dataclass enforcement, default values, and field semantics
for every public class in the data model.  No mocking is required — all types
are pure-Python dataclasses or enums.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from workflow.models import (
    AgentSpec,
    DomainRule,
    OutputMode,
    OutputSpec,
    StageKind,
    StageSpec,
    StageStatus,
    TriggerSpec,
    ValidationSpec,
    WorkflowRun,
)
from tests.workflow_tests.helpers.factories import (
    TEST_FINISHED_AT,
    TEST_STARTED_AT,
    make_agent_spec,
    make_domain_rule,
    make_output_spec,
    make_resolved_stage,
    make_stage_result,
    make_stage_spec,
    make_trigger_spec,
    make_validation_spec,
    make_workflow_definition,
    make_workflow_manifest,
)

# ---------------------------------------------------------------------------
# Enum membership and string-value contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "member, expected_value",
    [
        (StageKind.gather, "gather"),
        (StageKind.propose, "propose"),
        (StageKind.execute, "execute"),
        (StageKind.validate, "validate"),
        (StageKind.publish, "publish"),
        (StageKind.sub_workflow, "sub-workflow"),
    ],
)
def test_stage_kind_values(member: StageKind, expected_value: str) -> None:
    assert member == expected_value
    assert isinstance(member, str)


@pytest.mark.parametrize(
    "member, expected_value",
    [
        (StageStatus.pending, "pending"),
        (StageStatus.running, "running"),
        (StageStatus.success, "success"),
        (StageStatus.failed, "failed"),
        (StageStatus.skipped, "skipped"),
        (StageStatus.awaiting_human, "awaiting_human"),
    ],
)
def test_stage_status_values(member: StageStatus, expected_value: str) -> None:
    assert member == expected_value
    assert isinstance(member, str)


@pytest.mark.parametrize(
    "member, expected_value",
    [
        (OutputMode.invoke, "invoke"),
        (OutputMode.generate, "generate"),
        (OutputMode.template, "template"),
    ],
)
def test_output_mode_values(member: OutputMode, expected_value: str) -> None:
    assert member == expected_value
    assert isinstance(member, str)


# ---------------------------------------------------------------------------
# Frozen enforcement — one representative test per frozen dataclass
# ---------------------------------------------------------------------------


def test_agent_spec_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        spec = make_agent_spec()
        spec.role = "changed"  # type: ignore[misc]


def test_output_spec_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        spec = make_output_spec()
        spec.name = "changed"  # type: ignore[misc]


def test_domain_rule_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        rule = make_domain_rule()
        rule.id = "changed"  # type: ignore[misc]


def test_validation_spec_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        spec = make_validation_spec()
        spec.strategy = "changed"  # type: ignore[misc]


def test_stage_spec_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        spec = make_stage_spec()
        spec.name = "changed"  # type: ignore[misc]


def test_trigger_spec_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        spec = make_trigger_spec()
        spec.source = "changed"  # type: ignore[misc]


def test_workflow_definition_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        wf = make_workflow_definition()
        wf.name = "changed"  # type: ignore[misc]


def test_stage_result_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        result = make_stage_result()
        result.stage_name = "changed"  # type: ignore[misc]


def test_resolved_stage_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        resolved = make_resolved_stage()
        resolved.index = 99  # type: ignore[misc]


def test_workflow_manifest_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        manifest = make_workflow_manifest()
        manifest.manifest_version = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AgentSpec
# ---------------------------------------------------------------------------


def test_agent_spec_required_fields() -> None:
    spec = AgentSpec(role="code-writer")
    assert spec.role == "code-writer"
    assert spec.model is None
    assert spec.tools == ()
    assert spec.access == "read-only"


def test_agent_spec_all_fields() -> None:
    spec = AgentSpec(
        role="reviewer",
        model="sonnet",
        tools=("Read", "Grep"),
        access="read-write",
    )
    assert spec.role == "reviewer"
    assert spec.model == "sonnet"
    assert spec.tools == ("Read", "Grep")
    assert spec.access == "read-write"


def test_agent_spec_tools_is_tuple() -> None:
    spec = make_agent_spec(tools=("Bash", "Edit"))
    assert isinstance(spec.tools, tuple)


# ---------------------------------------------------------------------------
# OutputSpec
# ---------------------------------------------------------------------------


def test_output_spec_defaults() -> None:
    spec = OutputSpec(name="out", mode=OutputMode.generate)
    assert spec.description == ""
    assert spec.skill is None
    assert spec.input_mapping == {}
    assert spec.template_ref is None
    assert spec.writing_guide_ref is None
    assert spec.example_ref is None
    assert spec.schema is None
    assert spec.when is None


def test_output_spec_invoke_mode() -> None:
    spec = OutputSpec(
        name="cli-out",
        mode=OutputMode.invoke,
        skill="/bin/github pr-view",
        input_mapping={"pr_id": "--pr"},
    )
    assert spec.mode == OutputMode.invoke
    assert spec.skill == "/bin/github pr-view"
    assert spec.input_mapping == {"pr_id": "--pr"}


def test_output_spec_template_mode() -> None:
    spec = OutputSpec(
        name="report",
        mode=OutputMode.template,
        template_ref="templates/postmortem/TEMPLATE.md",
        writing_guide_ref="templates/postmortem/WRITING_GUIDE.md",
        example_ref="templates/postmortem/EXAMPLE.md",
    )
    assert spec.mode == OutputMode.template
    assert spec.template_ref == "templates/postmortem/TEMPLATE.md"
    assert spec.writing_guide_ref == "templates/postmortem/WRITING_GUIDE.md"
    assert spec.example_ref == "templates/postmortem/EXAMPLE.md"


def test_output_spec_generate_mode_with_schema() -> None:
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
    spec = OutputSpec(name="structured", mode=OutputMode.generate, schema=schema)
    assert spec.mode == OutputMode.generate
    assert spec.schema == schema


# ---------------------------------------------------------------------------
# DomainRule
# ---------------------------------------------------------------------------


def test_domain_rule_defaults() -> None:
    rule = DomainRule(id="DR-001", description="Accuracy rule")
    assert rule.severity == "minor"
    assert rule.category == "accuracy"
    assert rule.source_cmd is None


def test_domain_rule_all_fields() -> None:
    rule = DomainRule(
        id="DR-002",
        description="Critical rule",
        severity="critical",
        category="consistency",
        source_cmd="./bin/mail-assistant filters list",
    )
    assert rule.severity == "critical"
    assert rule.category == "consistency"
    assert rule.source_cmd == "./bin/mail-assistant filters list"


# ---------------------------------------------------------------------------
# ValidationSpec
# ---------------------------------------------------------------------------


def test_validation_spec_defaults() -> None:
    spec = ValidationSpec(strategy="fact_check")
    assert spec.criteria == ()
    assert spec.domain_rules == ()
    assert spec.max_revisions == 2


def test_validation_spec_with_domain_rules() -> None:
    rule = make_domain_rule(id="DR-003", severity="critical")
    spec = ValidationSpec(
        strategy="adversarial",
        criteria=("No hallucinated numbers",),
        domain_rules=(rule,),
        max_revisions=3,
    )
    assert spec.strategy == "adversarial"
    assert len(spec.domain_rules) == 1
    assert spec.domain_rules[0].id == "DR-003"
    assert spec.max_revisions == 3


# ---------------------------------------------------------------------------
# StageSpec
# ---------------------------------------------------------------------------


def test_stage_spec_defaults() -> None:
    spec = StageSpec(
        name="gather-data",
        kind=StageKind.gather,
        description="Gathers data",
        agent=make_agent_spec(),
    )
    assert spec.depends_on == ()
    assert spec.outputs == ()
    assert spec.validation is None
    assert spec.human_gate is False
    assert spec.required is True
    assert spec.reads_from == ()
    assert spec.writes_to == ()
    assert spec.sub_workflow == ""


def test_stage_spec_depends_on() -> None:
    spec = make_stage_spec(depends_on=("stage-a", "stage-b"))
    assert spec.depends_on == ("stage-a", "stage-b")


def test_stage_spec_human_gate() -> None:
    spec = make_stage_spec(human_gate=True)
    assert spec.human_gate is True


def test_stage_spec_reads_writes() -> None:
    spec = make_stage_spec(
        reads_from=("gather-stage",),
        writes_to=("report.md", "summary.json"),
    )
    assert spec.reads_from == ("gather-stage",)
    assert spec.writes_to == ("report.md", "summary.json")


def test_stage_spec_with_validation() -> None:
    validation = make_validation_spec(strategy="cross_unit")
    spec = make_stage_spec(validation=validation)
    assert spec.validation is not None
    assert spec.validation.strategy == "cross_unit"


# ---------------------------------------------------------------------------
# TriggerSpec
# ---------------------------------------------------------------------------


def test_trigger_spec_defaults() -> None:
    spec = TriggerSpec(source="zoom")
    assert spec.params == {}


def test_trigger_spec_with_params() -> None:
    spec = TriggerSpec(source="manual", params={"incident_id": "INC-123"})
    assert spec.source == "manual"
    assert spec.params["incident_id"] == "INC-123"


# ---------------------------------------------------------------------------
# WorkflowDefinition
# ---------------------------------------------------------------------------


def test_workflow_definition_defaults() -> None:
    wf = make_workflow_definition()
    assert wf.workspace_dir is None
    assert wf.metadata == {}


def test_workflow_definition_stages_is_tuple() -> None:
    stage_a = make_stage_spec(name="stage-a")
    stage_b = make_stage_spec(name="stage-b", kind=StageKind.validate)
    wf = make_workflow_definition(stages=(stage_a, stage_b))
    assert isinstance(wf.stages, tuple)
    assert len(wf.stages) == 2


def test_workflow_definition_multiple_stages_order() -> None:
    stages = tuple(make_stage_spec(name=f"stage-{i}") for i in range(3))
    wf = make_workflow_definition(stages=stages)
    assert wf.stages[0].name == "stage-0"
    assert wf.stages[2].name == "stage-2"


def test_workflow_definition_metadata() -> None:
    wf = make_workflow_definition(metadata={"owner": "platform", "ticket": "WF-42"})
    assert wf.metadata["owner"] == "platform"


# ---------------------------------------------------------------------------
# StageResult
# ---------------------------------------------------------------------------


def test_stage_result_defaults() -> None:
    result = make_stage_result()
    assert result.data == {}
    assert result.errors == []
    assert result.output_files == []
    assert result.input_stages == []
    assert result.metadata == {}


def test_stage_result_status_enum_round_trip() -> None:
    result = make_stage_result(status=StageStatus.success)
    # StageStatus inherits str — equality with the raw string must hold.
    assert result.status == "success"
    assert result.status is StageStatus.success


def test_stage_result_failed_status() -> None:
    result = make_stage_result(status=StageStatus.failed, errors=["timeout"])
    assert result.status == StageStatus.failed
    assert "timeout" in result.errors


def test_stage_result_timestamps() -> None:
    result = make_stage_result()
    assert result.started_at == TEST_STARTED_AT
    assert result.finished_at == TEST_FINISHED_AT
    assert result.duration_ms == 60000


# ---------------------------------------------------------------------------
# ResolvedStage
# ---------------------------------------------------------------------------


def test_resolved_stage_defaults() -> None:
    resolved = make_resolved_stage()
    assert resolved.cli_commands == ()
    assert resolved.prompt is None
    assert resolved.template_content is None
    assert resolved.guide_content is None


def test_resolved_stage_with_prompt() -> None:
    resolved = make_resolved_stage(prompt="Gather all mail filters.")
    assert resolved.prompt == "Gather all mail filters."


def test_resolved_stage_spec_reference() -> None:
    stage = make_stage_spec(name="custom-stage", kind=StageKind.publish)
    resolved = make_resolved_stage(spec=stage, index=3)
    assert resolved.spec.name == "custom-stage"
    assert resolved.spec.kind == StageKind.publish
    assert resolved.index == 3


# ---------------------------------------------------------------------------
# WorkflowManifest
# ---------------------------------------------------------------------------


def test_workflow_manifest_defaults() -> None:
    manifest = make_workflow_manifest()
    assert manifest.resolved_stages == {}
    assert manifest.compiled_at == ""
    assert manifest.manifest_version == 1


def test_workflow_manifest_parallel_groups_structure() -> None:
    manifest = make_workflow_manifest(
        parallel_groups=(("stage-a",), ("stage-b", "stage-c"))
    )
    assert isinstance(manifest.parallel_groups, tuple)
    assert manifest.parallel_groups[0] == ("stage-a",)
    assert manifest.parallel_groups[1] == ("stage-b", "stage-c")


def test_workflow_manifest_with_resolved_stages() -> None:
    resolved = make_resolved_stage(spec=make_stage_spec(name="gather"))
    manifest = make_workflow_manifest(resolved_stages={"gather": resolved})
    assert "gather" in manifest.resolved_stages
    assert manifest.resolved_stages["gather"].spec.name == "gather"


# ---------------------------------------------------------------------------
# WorkflowRun
# ---------------------------------------------------------------------------


def test_workflow_run_default_status_is_pending() -> None:
    run = WorkflowRun(
        manifest=make_workflow_manifest(),
        workspace_dir="/tmp/runs/test-run",
        run_id="run-abc-123",
        started_at=TEST_STARTED_AT,
    )
    assert run.status == StageStatus.pending
    assert run.status == "pending"


def test_workflow_run_stage_results_default_empty() -> None:
    run = WorkflowRun(
        manifest=make_workflow_manifest(),
        workspace_dir="/tmp/runs/test-run",
        run_id="run-abc-123",
        started_at=TEST_STARTED_AT,
    )
    assert run.stage_results == {}


def test_workflow_run_frozen() -> None:
    run = WorkflowRun(
        manifest=make_workflow_manifest(),
        workspace_dir="/tmp/runs/test-run",
        run_id="run-abc-123",
        started_at=TEST_STARTED_AT,
    )
    with pytest.raises(FrozenInstanceError):
        run.run_id = "changed"  # type: ignore[misc]
