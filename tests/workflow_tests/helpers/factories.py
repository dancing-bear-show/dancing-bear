"""Test factories for workflow dataclasses.

Provides ``make_*`` functions that build workflow model instances with sensible
defaults. Pass keyword overrides to adjust individual fields without constructing
the full object manually.

Usage:
    from tests.workflow_tests.helpers.factories import make_workflow_definition, make_stage_spec

    wf = make_workflow_definition(name="my-workflow")
    stage = make_stage_spec(kind=StageKind.validate, human_gate=True)
"""

from __future__ import annotations

from workflow.models import (
    AgentAccess,
    AgentSpec,
    DomainRule,
    OutputMode,
    OutputSpec,
    ResolvedStage,
    StageKind,
    StageResult,
    StageSpec,
    StageStatus,
    TriggerSpec,
    ValidationSpec,
    ValidationStrategy,
    WorkflowDefinition,
    WorkflowManifest,
)


# ---------------------------------------------------------------------------
# Author-facing spec factories
# ---------------------------------------------------------------------------


def make_agent_spec(**overrides: object) -> AgentSpec:
    """Create an AgentSpec with sensible defaults."""
    defaults: dict[str, object] = {
        "role": "researcher",
        "model": None,
        "tools": (),
        "access": AgentAccess.read_only,
    }
    defaults.update(overrides)
    return AgentSpec(**defaults)  # type: ignore[arg-type]


def make_output_spec(**overrides: object) -> OutputSpec:
    """Create an OutputSpec with sensible defaults."""
    defaults: dict[str, object] = {
        "name": "test-output",
        "mode": OutputMode.generate,
        "description": "Test output",
    }
    defaults.update(overrides)
    return OutputSpec(**defaults)  # type: ignore[arg-type]


def make_domain_rule(**overrides: object) -> DomainRule:
    """Create a DomainRule with sensible defaults."""
    defaults: dict[str, object] = {
        "id": "test-rule-001",
        "description": "Test domain rule",
    }
    defaults.update(overrides)
    return DomainRule(**defaults)  # type: ignore[arg-type]


def make_validation_spec(**overrides: object) -> ValidationSpec:
    """Create a ValidationSpec with sensible defaults."""
    defaults: dict[str, object] = {"strategy": ValidationStrategy.unit}
    defaults.update(overrides)
    return ValidationSpec(**defaults)  # type: ignore[arg-type]


def make_stage_spec(**overrides: object) -> StageSpec:
    """Create a StageSpec with sensible defaults."""
    defaults: dict[str, object] = {
        "name": "test-stage",
        "kind": StageKind.gather,
        "description": "Test stage",
        "agent": make_agent_spec(),
    }
    defaults.update(overrides)
    return StageSpec(**defaults)  # type: ignore[arg-type]


def make_trigger_spec(**overrides: object) -> TriggerSpec:
    """Create a TriggerSpec with sensible defaults."""
    defaults: dict[str, object] = {"source": "manual"}
    defaults.update(overrides)
    return TriggerSpec(**defaults)  # type: ignore[arg-type]


def make_workflow_definition(**overrides: object) -> WorkflowDefinition:
    """Create a WorkflowDefinition with sensible defaults."""
    defaults: dict[str, object] = {
        "name": "test-workflow",
        "version": "0.1.0",
        "description": "Test workflow",
        "trigger": make_trigger_spec(),
        "stages": (make_stage_spec(),),
    }
    defaults.update(overrides)
    return WorkflowDefinition(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Engine-internal factories
# ---------------------------------------------------------------------------

# Stable ISO 8601 timestamps used across all engine-internal factories.
TEST_STARTED_AT = "2026-04-01T00:00:00Z"
TEST_FINISHED_AT = "2026-04-01T00:01:00Z"


def make_stage_result(**overrides: object) -> StageResult:
    """Create a StageResult with sensible defaults."""
    defaults: dict[str, object] = {
        "stage_name": "test-stage",
        "stage_index": 0,
        "status": StageStatus.success,
        "started_at": TEST_STARTED_AT,
        "finished_at": TEST_FINISHED_AT,
        "duration_ms": 60000,
    }
    defaults.update(overrides)
    return StageResult(**defaults)  # type: ignore[arg-type]


def make_resolved_stage(**overrides: object) -> ResolvedStage:
    """Create a ResolvedStage with sensible defaults."""
    defaults: dict[str, object] = {
        "spec": make_stage_spec(),
        "index": 0,
    }
    defaults.update(overrides)
    return ResolvedStage(**defaults)  # type: ignore[arg-type]


def make_workflow_manifest(**overrides: object) -> WorkflowManifest:
    """Create a WorkflowManifest with sensible defaults."""
    defaults: dict[str, object] = {
        "definition": make_workflow_definition(),
        "parallel_groups": (("test-stage",),),
    }
    defaults.update(overrides)
    return WorkflowManifest(**defaults)  # type: ignore[arg-type]
