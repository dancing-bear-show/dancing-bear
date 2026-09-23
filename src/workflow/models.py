"""Data model for the Agentic Workflow Engine.

Defines the complete type hierarchy for declaring, compiling, and executing
agent-orchestrated workflows. Author-facing specs (WorkflowDefinition and
its children) describe *what* to do; engine-internal types (WorkflowManifest,
ResolvedStage, StageResult, WorkflowRun) track *how* it runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    # Enums
    "StageKind",
    "StageStatus",
    "OutputMode",
    "AgentAccess",
    "RuleSeverity",
    "RuleCategory",
    "ValidationStrategy",
    # Author-facing specs
    "AgentSpec",
    "FanOutMode",
    "FanOutSpec",
    "IncludeSpec",
    "OutputCheck",
    "OutputSpec",
    "DomainRule",
    "ValidationSpec",
    "StageSpec",
    "TriggerSpec",
    "WorkflowDefinition",
    # Engine-internal types
    "ManifestRef",
    "ResolvedStage",
    "WorkflowManifest",
    "StageResult",
    "StageResultExtras",
    "WorkflowRun",
    "make_stage_result",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StageKind(str, Enum):
    """Advisory label for a workflow stage's purpose."""

    gather = "gather"  # noqa
    propose = "propose"  # noqa
    execute = "execute"  # noqa
    validate = "validate"  # noqa
    publish = "publish"  # noqa
    sub_workflow = "sub-workflow"  # noqa - inline sub-workflow — orchestrator invokes /workflow skill directly


class StageStatus(str, Enum):
    """Execution status for a workflow stage."""

    pending = "pending"
    running = "running"  # noqa
    success = "success"  # noqa
    failed = "failed"  # noqa
    skipped = "skipped"  # noqa
    awaiting_human = "awaiting_human"  # noqa


class OutputMode(str, Enum):
    """How an output is produced."""

    invoke = "invoke"  # noqa - CLI call with structured input
    generate = "generate"  # noqa - agent-written content
    template = "template"  # noqa - fill template + writing guide


class AgentAccess(str, Enum):
    """Access level for an agent."""

    read_only = "read-only"
    read_write = "read-write"  # noqa


class RuleSeverity(str, Enum):
    """Severity level for a domain rule."""

    critical = "critical"  # noqa
    minor = "minor"
    info = "info"  # noqa


class RuleCategory(str, Enum):
    """Category for a domain rule."""

    accuracy = "accuracy"
    consistency = "consistency"  # noqa
    completeness = "completeness"  # noqa
    style = "style"  # noqa
    cross_reference = "cross_reference"  # noqa
    terraform = "terraform"  # noqa
    pagerduty = "pagerduty"  # noqa
    metrics = "metrics"  # noqa
    incidents = "incidents"  # noqa


class ValidationStrategy(str, Enum):
    """Validation dispatch strategy."""

    unit = "unit"  # noqa
    cross_unit = "cross_unit"  # noqa
    adversarial = "adversarial"  # noqa
    fact_check = "fact_check"  # noqa
    deliverable = "deliverable"  # noqa


# ---------------------------------------------------------------------------
# Author-facing dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentSpec:
    """Specifies which agent runs a stage."""

    role: str  # noqa - agent type: researcher, code-writer, doc-writer, reviewer, etc.
    model: str | None = None  # noqa - sonnet, opus, haiku, or None (inherit)
    tools: tuple[str, ...] = ()  # noqa - allowed tools (empty = all)
    access: AgentAccess = AgentAccess.read_only  # noqa
    # Whether `access:` was written in the YAML, as opposed to defaulting above.
    # The two are indistinguishable from `access` alone, and the linter needs the
    # difference: a stage that DECLARED read-only is making a claim worth checking,
    # while one that said nothing is not. Without this, a check on the default
    # fires on every minimal stage in the tree.
    access_declared: bool = False  # noqa
    # "worktree" runs the agent in its own git worktree so parallel writers do
    # not interleave edits in a shared tree. None inherits the caller's tree.
    # Surfaced in the dispatch payload so the orchestrator passes it to Agent().
    isolation: str | None = None  # noqa


@dataclass(frozen=True)
class OutputSpec:
    """Declares one output artifact from a stage."""

    name: str  # output identifier
    mode: OutputMode  # noqa
    description: str = ""  # noqa
    # For invoke mode:
    skill: str | None = None  # noqa - skill name or CLI path
    input_mapping: dict[str, str] = field(default_factory=dict)  # noqa - digest field -> skill param
    # For template mode:
    template_ref: str | None = None  # noqa - path to TEMPLATE.md
    writing_guide_ref: str | None = None  # noqa - path to WRITING_GUIDE.md
    example_ref: str | None = None  # noqa - path to EXAMPLE.md
    # For generate mode:
    schema: dict[str, Any] | None = None  # noqa - expected output structure
    # Conditional:
    when: str | None = None  # noqa - natural-language condition


@dataclass(frozen=True)
class DomainRule:
    """An encoded failure pattern for validation."""

    id: str  # noqa
    description: str  # noqa
    severity: RuleSeverity = RuleSeverity.minor  # noqa
    category: RuleCategory = RuleCategory.accuracy  # noqa
    source_cmd: str | None = None  # noqa - CLI command to verify


@dataclass(frozen=True)
class ValidationSpec:
    """Declares validation strategy and criteria for a stage."""

    strategy: ValidationStrategy  # noqa
    criteria: tuple[str, ...] = ()  # noqa - natural-language validation criteria
    domain_rules: tuple[DomainRule, ...] = ()  # noqa
    max_revisions: int = 2  # noqa


@dataclass(frozen=True)
class IncludeSpec:
    """Declares a fragment inclusion that is expanded at parse time.

    All stages from the referenced fragment YAML are inlined into the parent
    workflow's stage list with names prefixed by ``prefix``. The first
    fragment stage's ``depends_on`` and ``reads_from`` are overridden by
    the values declared here, which link the fragment into the parent DAG.
    All intra-fragment references are also rewritten with the prefix.
    """

    path: str  # noqa - relative path to fragment YAML (resolved from cwd first, then workflow file's directory)
    prefix: str  # noqa - prepended to stage names: f"{prefix}-{stage.name}"
    depends_on: tuple[str, ...] = ()  # noqa - overrides the first fragment stage's depends_on
    reads_from: tuple[str, ...] = ()  # overrides the first fragment stage's reads_from
    params: dict[str, str] = field(default_factory=dict)  # noqa - reserved for future use


class FanOutMode:
    """Valid values for :attr:`FanOutSpec.mode`.

    Kept as string constants (not an ``Enum``) so YAML author-facing mode
    names survive round-tripping through ``str``-typed configs unchanged.
    """

    AGENT: str = "agent"  # noqa
    WORKER_QUEUE: str = "worker_queue"  # noqa

    # Tuple form is convenient for parser validation (`mode in FanOutMode.ALL`).
    ALL: tuple[str, ...] = ("agent", "worker_queue")  # noqa


@dataclass(frozen=True)
class OutputCheck:
    """Declares an inline schema contract for one of a stage's output files.

    The workflow orchestrator evaluates these checks after the stage completes
    and before the agent is reaped, allowing a correction prompt to be sent
    while the agent is still open.

    Supported check names
    ----------------------
    - ``is_json``                 — file is valid JSON
    - ``is_dict``                 — top-level value is a dict
    - ``is_list``                 — top-level value is a list
    - ``has_key:<k>``             — top-level dict has key ``k``
    - ``values_have_key:<k>``     — every value in the top-level dict has key ``k``
    - ``list_items_have_key:<k>`` — every item in the top-level list has key ``k``
    - ``non_empty``               — list or dict has at least 1 item

    Unknown check names are accepted (forward-compat) but logged as warnings.
    """

    path: str  # noqa - workspace-relative path, e.g. "outputs/filter-plan.json"
    checks: list[str]  # noqa - ordered list of check names


@dataclass(frozen=True)
class FanOutSpec:
    """Declares fan-out: expand one stage into N parallel stages at compile time.

    The compiler reads the output of ``source`` stage, iterates over the
    list at ``field``, and creates one stage per item using ``key`` as the
    per-item identifier substituted into the stage description and output
    filenames via ``{fan_out.key}`` placeholders.

    Execution modes
    ---------------
    ``mode="agent"`` (default)
        The existing behavior: the workflow skill spawns N full agents, one
        per fan-out item, and waits for all of them to complete.

    ``mode="worker_queue"``
        Headless, CLI-only fan-out.  ``{key}`` inside ``script`` is replaced
        with the per-item value at runtime.
    """

    source: str  # noqa - stage name whose output contains the list
    field: str  # JSON field path to the array (e.g., "services")
    key: str  # noqa - field within each array item to use as the per-item param
    mode: str = "agent"  # noqa - "agent" (default) | "worker_queue"
    script: str = ""  # noqa - shell command template for worker_queue mode; {key} substituted
    output_schema: str = ""  # noqa - optional JSON schema path to validate each job's output file


@dataclass(frozen=True)
class StageSpec:
    """Declares one unit of work in the workflow DAG.

    Execution model
    ---------------
    ``executor="agent"`` (default)
        The stage runs through the existing dispatcher routing — invoke-only
        stages execute locally, anything requiring generation/templating goes
        to the agent skill dispatcher.

    ``executor="inline"``
        The Claude ``/workflow`` skill orchestrator runs the stage directly
        in its own session — no agent is spawned. The Python dispatcher
        raises ``NotImplementedError`` for inline stages.
    """

    name: str  # unique within workflow
    kind: StageKind  # noqa
    description: str  # noqa
    agent: AgentSpec  # noqa
    depends_on: tuple[str, ...] = ()  # noqa - stage names this depends on
    outputs: tuple[OutputSpec, ...] = ()  # noqa
    validation: ValidationSpec | None = None  # noqa
    human_gate: bool = False  # noqa - pause for human review after this stage
    required: bool = True  # noqa
    reads_from: tuple[str, ...] = ()  # stage names whose output files this reads
    writes_to: tuple[str, ...] = ()  # output filenames this stage produces
    fan_out: FanOutSpec | None = None  # noqa - expand into parallel stages per item
    executor: str = "agent"  # noqa - "agent" (default) | "inline" | "local" | "skill"
    script: str = ""  # noqa - shell command template (unused in dancing-bear; retained for YAML compat)
    when: str | None = None  # noqa - Optional skip condition — see orchestrator._eval_when()
    sub_workflow: str = ""  # noqa - path to sub-workflow YAML when kind=sub-workflow
    validates_output: list[OutputCheck] = field(default_factory=list)  # noqa - inline output contract checks


@dataclass(frozen=True)
class TriggerSpec:
    """Declares what initiates a workflow."""

    source: str  # noqa - manual, schedule, webhook, etc.
    params: dict[str, str] = field(default_factory=dict)  # noqa


@dataclass(frozen=True)
class WorkflowDefinition:
    """Top-level author-facing workflow declaration."""

    name: str
    version: str  # noqa
    description: str  # noqa
    trigger: TriggerSpec  # noqa
    stages: tuple[StageSpec, ...]  # noqa
    workspace_dir: str | None = None  # noqa - override output directory pattern
    metadata: dict[str, Any] = field(default_factory=dict)
    includes: tuple[IncludeSpec, ...] = ()  # noqa - parsed from include: list; stages are inlined at parse time


# ---------------------------------------------------------------------------
# Engine-internal dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedStage:
    """A stage with all references resolved and prompts constructed."""

    spec: StageSpec
    index: int  # execution order index
    cli_commands: tuple[str, ...] = ()  # noqa - resolved CLI commands for invoke outputs
    prompt: str | None = None  # noqa - constructed agent prompt
    template_content: str | None = None  # noqa - loaded template text
    guide_content: str | None = None  # noqa - loaded writing guide text


@dataclass(frozen=True)
class ManifestRef:
    """Lightweight reference for persisting and resuming a workflow manifest.

    Instead of serializing the full object graph, stores the YAML path
    so the manifest can be re-parsed and re-compiled on resume.
    """

    yaml_path: str  # noqa
    workspace_dir: str  # noqa
    run_id: str  # noqa
    compiled_at: str  # noqa
    trigger_params: dict[str, str] = field(default_factory=dict)  # noqa
    manifest_version: int = 1  # noqa


@dataclass(frozen=True)
class WorkflowManifest:
    """Compiled workflow ready for execution."""

    definition: WorkflowDefinition  # noqa
    parallel_groups: tuple[tuple[str, ...], ...]  # noqa - BFS-leveled groups of stage names
    resolved_stages: dict[str, ResolvedStage] = field(default_factory=dict)  # noqa
    compiled_at: str = ""  # noqa - ISO 8601
    manifest_version: int = 1  # noqa


@dataclass(frozen=True)
class StageResult:
    """Execution result envelope for a single stage."""

    stage_name: str  # noqa
    stage_index: int  # noqa
    status: StageStatus
    started_at: str  # ISO 8601 UTC
    finished_at: str  # ISO 8601 UTC
    duration_ms: int
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)  # noqa
    input_stages: list[str] = field(default_factory=list)  # noqa
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StageResultExtras:
    """Optional data, errors, and metadata carried in a StageResult.

    Groups the three optional output fields of make_stage_result so
    the function signature stays at or below five parameters.
    """

    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def make_stage_result(
    stage: ResolvedStage,
    started_at: str,
    status: StageStatus,
    extras: StageResultExtras | None = None,
) -> StageResult:
    """Build a StageResult with computed timing from ISO timestamps."""
    from core.date_utils import iso_now, parse_iso_utc_strict

    _extras = extras if extras is not None else StageResultExtras()
    finished_at = iso_now()
    start_dt = parse_iso_utc_strict(started_at)
    end_dt = parse_iso_utc_strict(finished_at)
    duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
    return StageResult(
        stage_name=stage.spec.name,
        stage_index=stage.index,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        data=_extras.data,
        errors=_extras.errors,
        output_files=list(stage.spec.writes_to),
        input_stages=list(stage.spec.reads_from),
        metadata=_extras.metadata,
    )


@dataclass(frozen=True)
class WorkflowRun:
    """Tracks the state of a workflow execution."""

    manifest: WorkflowManifest  # noqa
    workspace_dir: str  # noqa
    run_id: str  # noqa
    started_at: str  # ISO 8601 UTC
    status: StageStatus = StageStatus.pending
    stage_results: dict[str, StageResult] = field(default_factory=dict)  # noqa
