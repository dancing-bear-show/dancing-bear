"""Compile a WorkflowDefinition into an executable WorkflowManifest.

Performs BFS topological sort to compute parallel groups, resolves template
references, builds full CLI commands from input_mapping, and substitutes
trigger params.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path

from core.cli_errors import CLIError, ExitCode
from core.fileutil import safe_read_text
from core.date_utils import iso_now
from workflow.models import (
    OutputMode,
    ResolvedStage,
    StageSpec,
    WorkflowDefinition,
    WorkflowManifest,
)

__all__ = [
    "WorkflowCompileError",
    "ContractWarning",
    "compile_workflow",
    "validate_dag_contracts",
]

logger = logging.getLogger(__name__)

# CLIs that do not use the -- separator before flags.
_NO_SEPARATOR_CLIS = frozenset({"docs", "llm"})

# Accepted when: expression forms.
_WHEN_PATTERN = re.compile(
    r'"(\{[^}]+\}|[^"]*?)"\s+(does not contain|contains)\s+"[^"]*?"'
)


class WorkflowCompileError(CLIError):
    """Raised when workflow compilation fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.ERROR)


@dataclass(frozen=True)
class ContractWarning:
    """A DAG contract violation found during static analysis."""

    stage: str  # stage that declares reads_from
    upstream: str  # the upstream stage being read
    message: str  # human-readable description


def validate_dag_contracts(definition: WorkflowDefinition) -> list[ContractWarning]:
    """Check reads_from/writes_to contracts across the DAG.

    For each stage S that names upstream stage U in ``reads_from``:
    - Warn if U has no ``writes_to`` entries declared.
    - Raise WorkflowCompileError if U does not exist in the manifest.

    Returns:
        List of :class:`ContractWarning` instances (may be empty).

    Raises:
        WorkflowCompileError: If ``reads_from`` references a stage that does not exist.
    """
    stage_map: dict[str, StageSpec] = {s.name: s for s in definition.stages}
    contract_warnings: list[ContractWarning] = []

    for stage in definition.stages:
        for upstream_name in stage.reads_from:
            if upstream_name not in stage_map:
                raise WorkflowCompileError(
                    f"Stage '{stage.name}' reads_from unknown stage '{upstream_name}'"
                )
            upstream = stage_map[upstream_name]
            if not upstream.writes_to:
                contract_warnings.append(
                    ContractWarning(
                        stage=stage.name,
                        upstream=upstream_name,
                        message=(
                            f"stage '{stage.name}' reads_from '{upstream_name}' "
                            f"but '{upstream_name}' declares no writes_to outputs"
                        ),
                    )
                )

    return contract_warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_workflow(
    definition: WorkflowDefinition,
    *,
    project_root: str | Path | None = None,
    trigger_params: dict[str, str] | None = None,
) -> WorkflowManifest:
    """Compile a workflow definition into an executable manifest.

    Args:
        definition: Validated workflow definition.
        project_root: Root directory for resolving template refs.
            Defaults to current working directory.
        trigger_params: Parameter values from the trigger.
            Substituted into CLI commands at compile time.

    Returns:
        WorkflowManifest with parallel_groups computed and stages resolved.

    Raises:
        WorkflowCompileError: On resolution failures.
    """
    root = Path(project_root) if project_root else Path.cwd()
    params = {**(definition.trigger.params or {}), **(trigger_params or {})}
    stage_map: dict[str, StageSpec] = {s.name: s for s in definition.stages}

    parallel_groups = _compute_parallel_groups(definition.stages)

    resolved: dict[str, ResolvedStage] = {}
    index = 0
    for group in parallel_groups:
        for name in group:
            spec = stage_map[name]
            resolved[name] = _resolve_stage(spec, index, root, params)
            index += 1

    logger.debug(
        "Compiled workflow %s: %d stages in %d groups",
        definition.name,
        len(resolved),
        len(parallel_groups),
    )

    return WorkflowManifest(
        definition=definition,
        parallel_groups=parallel_groups,
        resolved_stages=resolved,
        compiled_at=iso_now(),
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_dependency_graph(
    stages: tuple[StageSpec, ...],
) -> tuple[set[str], dict[str, StageSpec], dict[str, set[str]], dict[str, int]]:
    """Build dependency graph structures from stage specs."""
    stage_names = {s.name for s in stages}
    spec_map = {s.name: s for s in stages}
    deps: dict[str, set[str]] = {}
    in_degree: dict[str, int] = {}

    for spec in stages:
        for dep in spec.depends_on:
            if dep not in stage_names:
                raise WorkflowCompileError(
                    f"Stage '{spec.name}' depends on unknown stage '{dep}'"
                )
        deps[spec.name] = set(spec.depends_on)
        in_degree[spec.name] = len(spec.depends_on)

    return stage_names, spec_map, deps, in_degree


def _bfs_level(
    current_level: list[str],
    spec_map: dict[str, StageSpec],
) -> tuple[list[str], list[str]]:
    """Split a sorted BFS level into normal and human-gated stages."""
    normal: list[str] = []
    gated: list[str] = []
    for name in current_level:
        if spec_map[name].human_gate:
            gated.append(name)
        else:
            normal.append(name)
    return normal, gated


def _drain_level(queue: deque[str], assigned: dict[str, int], level: int) -> list[str]:
    """Pop every stage currently queued, assigning it to level. Returns them sorted."""
    current_level: list[str] = []
    while queue:
        name = queue.popleft()
        assigned[name] = level
        current_level.append(name)
    current_level.sort()
    return current_level


def _next_ready_queue(
    stages: tuple[StageSpec, ...],
    deps: dict[str, set[str]],
    assigned: dict[str, int],
) -> deque[str]:
    """Return stages whose dependencies are all assigned but are not yet themselves."""
    return deque(
        spec.name
        for spec in stages
        if spec.name not in assigned and all(d in assigned for d in deps[spec.name])
    )


def _groups_for_level(current_level: list[str], spec_map: dict[str, StageSpec]) -> list[tuple[str, ...]]:
    """Split one BFS level into its normal group plus one group per human-gated stage."""
    normal, gated = _bfs_level(current_level, spec_map)
    groups: list[tuple[str, ...]] = []
    if normal:
        groups.append(tuple(normal))
    groups.extend((g,) for g in gated)
    return groups


def _compute_parallel_groups(
    stages: tuple[StageSpec, ...],
) -> tuple[tuple[str, ...], ...]:
    """BFS topological sort with leveling. Returns groups of stage names.

    Stages with ``human_gate=True`` are isolated into their own group so
    execution can pause without blocking sibling stages.

    Raises:
        WorkflowCompileError: If the dependency graph contains a cycle or
            references an unknown stage.
    """
    stage_names, spec_map, deps, in_degree = _build_dependency_graph(stages)

    assigned: dict[str, int] = {}
    queue: deque[str] = deque(
        name for name in stage_names if in_degree[name] == 0
    )

    level = 0
    groups: list[tuple[str, ...]] = []

    while queue:
        current_level = _drain_level(queue, assigned, level)
        groups.extend(_groups_for_level(current_level, spec_map))
        queue = _next_ready_queue(stages, deps, assigned)
        level += 1

    if len(assigned) != len(stage_names):
        unresolved = stage_names - set(assigned)
        raise WorkflowCompileError(
            f"Cyclic dependency detected involving stages: "
            f"{', '.join(sorted(unresolved))}"
        )

    return tuple(groups)


def _load_referenced_file(
    ref: str,
    project_root: Path,
    stage_name: str,
    kind: str,
) -> str:
    """Load a stage-referenced file (template or writing guide)."""
    path = project_root / ref
    content = safe_read_text(path)
    if content is None:
        raise WorkflowCompileError(
            f"Stage '{stage_name}': {kind} not found at {path}"
        )
    return content


def _collect_stage_outputs(
    spec: StageSpec,
    project_root: Path,
    params: dict[str, str],
) -> tuple[str | None, str | None, list[str]]:
    """Walk ``spec.outputs`` and return (template, guide, cli_commands)."""
    template_content: str | None = None
    guide_content: str | None = None
    cli_commands: list[str] = []

    for output in spec.outputs:
        if output.template_ref:
            template_content = _load_referenced_file(
                output.template_ref, project_root, spec.name, "template"
            )
        if output.writing_guide_ref:
            guide_content = _load_referenced_file(
                output.writing_guide_ref, project_root, spec.name, "writing guide"
            )
        if output.mode == OutputMode.invoke and output.skill:
            cmd = _build_cli_command(output.skill, output.input_mapping)
            cli_commands.append(resolve_params(cmd, params))

    return template_content, guide_content, cli_commands


def _validate_when(spec: StageSpec) -> None:
    """Validate the when: expression on a stage spec at compile time."""
    if spec.when is None:
        return
    if not _WHEN_PATTERN.fullmatch(spec.when.strip()):
        raise WorkflowCompileError(
            f"Stage '{spec.name}': unsupported 'when' expression {spec.when!r}"
            " — supported forms:"
            ' \'"{param}" contains "value"\''
            " and"
            ' \'"{param}" does not contain "value"\''
        )


def _resolve_stage(
    spec: StageSpec,
    index: int,
    project_root: Path,
    params: dict[str, str] | None = None,
) -> ResolvedStage:
    """Resolve a single stage — load templates, build CLI commands."""
    params = params or {}
    _validate_when(spec)
    template_content, guide_content, cli_commands = _collect_stage_outputs(
        spec, project_root, params
    )

    resolved_spec = (
        replace(spec, description=resolve_params(spec.description, params))
        if params and spec.description
        else spec
    )

    return ResolvedStage(
        spec=resolved_spec,
        index=index,
        cli_commands=tuple(cli_commands),
        template_content=template_content,
        guide_content=guide_content,
    )


def _build_cli_command(skill: str, mapping: dict[str, str]) -> str:
    """Build a CLI command from skill name and input mapping.

    Constructs: ``./bin/<skill> <subcommand> -- <flags>``
    Absolute or relative paths (starting with "/" or "./") are used as-is.
    """
    if skill.startswith("/") or skill.startswith("./"):
        parts = [skill]
    else:
        parts = [f"./bin/{skill}"]

    if sub := mapping.get("subcommand"):
        parts.append(sub)

    needs_separator = skill not in _NO_SEPARATOR_CLIS

    query = mapping.get("query", "")
    flags = mapping.get("flags", "")

    if needs_separator and (query or flags):
        parts.append("--")

    if query:
        parts.append(f"'{query}'")

    if flags:
        parts.append(flags)

    return " ".join(parts)


def resolve_params(template: str, params: dict[str, str]) -> str:
    """Resolve ``{param}`` placeholders in a string.

    Substitutes keys like ``{team}`` from trigger params.
    Unresolved placeholders are left as-is.
    """
    result = template
    for key, value in params.items():
        result = result.replace(f"{{{key}}}", value)
    return result

