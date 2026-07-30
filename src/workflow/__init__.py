"""Workflow engine — structured multi-stage execution with validation."""

from __future__ import annotations

from workflow.compiler import WorkflowCompileError, compile_workflow
from workflow.dispatchers import (
    CompositeDispatcher,
    LocalDispatcher,
    SkillDispatcher,
    StageDispatcher,
)
from workflow.dispatch import (
    KNOWN_ROLES,
    build_agent_prompt,
    build_dispatch_instruction,
    build_group_dispatch,
)
from workflow.models import (
    AgentAccess,
    AgentSpec,
    DomainRule,
    FanOutSpec,
    ManifestRef,
    OutputMode,
    OutputSpec,
    ResolvedStage,
    RuleCategory,
    RuleSeverity,
    StageKind,
    StageResult,
    StageSpec,
    StageStatus,
    TriggerSpec,
    ValidationSpec,
    ValidationStrategy,
    WorkflowDefinition,
    WorkflowManifest,
    WorkflowRun,
    make_stage_result,
)
from workflow.orchestrator import WorkflowExecutionError, WorkflowOrchestrator
from workflow.parser import WorkflowParseError, parse_workflow, parse_workflow_str

__all__ = [
    "AgentAccess",
    "AgentSpec",
    "CompositeDispatcher",
    "KNOWN_ROLES",
    "LocalDispatcher",
    "ManifestRef",
    "RuleCategory",
    "RuleSeverity",
    "SkillDispatcher",
    "StageDispatcher",
    "ValidationStrategy",
    "build_agent_prompt",
    "build_dispatch_instruction",
    "build_group_dispatch",
    "DomainRule",
    "FanOutSpec",
    "OutputMode",
    "OutputSpec",
    "ResolvedStage",
    "StageKind",
    "StageResult",
    "StageSpec",
    "StageStatus",
    "TriggerSpec",
    "ValidationSpec",
    "WorkflowCompileError",
    "WorkflowDefinition",
    "WorkflowExecutionError",
    "WorkflowManifest",
    "WorkflowOrchestrator",
    "WorkflowParseError",
    "WorkflowRun",
    "compile_workflow",
    "make_stage_result",
    "parse_workflow",
    "parse_workflow_str",
]
