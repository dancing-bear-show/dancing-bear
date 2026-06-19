"""YAML loading and validation for workflow definitions.

Loads a YAML file (or string), validates structural constraints, and
constructs a fully typed ``WorkflowDefinition``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from .models import (
    AgentAccess,
    AgentSpec,
    DomainRule,
    FanOutMode,
    FanOutSpec,
    OutputCheck,
    OutputMode,
    OutputSpec,
    RuleCategory,
    RuleSeverity,
    StageKind,
    StageSpec,
    TriggerSpec,
    ValidationSpec,
    ValidationStrategy,
    WorkflowDefinition,
)
from .include import (
    parse_fragment,  # re-exported for backward compat — keep in __all__
    _parse_include,
    _expand_includes,
)

__all__ = [
    "WorkflowParseError",
    "parse_workflow",
    "parse_workflow_str",
    "parse_fragment",
]

logger = logging.getLogger(__name__)

_REQUIRED_TOP_KEYS = ("name", "version", "description", "trigger", "stages")


class WorkflowParseError(Exception):
    """Raised when a workflow definition fails validation."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_workflow(path: str | Path) -> WorkflowDefinition:
    """Load and validate a workflow definition from a YAML file.

    Raises ``WorkflowParseError`` on invalid input.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise WorkflowParseError(f"file not found: {p}") from None
    except OSError as exc:
        raise WorkflowParseError(f"cannot read {p}: {exc}") from exc
    return parse_workflow_str(text, source=str(p))


def parse_workflow_str(content: str, source: str = "<string>") -> WorkflowDefinition:
    """Parse a workflow definition from a YAML string.

    Useful for testing. *source* is used in error messages.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise WorkflowParseError(f"{source}: invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise WorkflowParseError(f"{source}: expected a YAML mapping at top level")

    for key in _REQUIRED_TOP_KEYS:
        if key not in data:
            raise WorkflowParseError(f"{source}: missing required key '{key}'")

    trigger = _parse_trigger(data["trigger"], source)
    raw_stages = data["stages"]
    if not isinstance(raw_stages, list) or len(raw_stages) == 0:
        raise WorkflowParseError(f"{source}: 'stages' must be a non-empty list")

    stages = tuple(_parse_stage(s, source) for s in raw_stages)

    raw_includes = data.get("include") or []
    if not isinstance(raw_includes, list):
        raise WorkflowParseError(f"{source}: 'include' must be a list, got {type(raw_includes).__name__}")
    includes = tuple(_parse_include(inc, source) for inc in raw_includes)
    if includes:
        source_path = Path(source) if source != "<string>" else None
        stages = _expand_includes(stages, includes, source_path, source)

    _validate_unique_names(stages, source)
    _validate_refs(stages, source)
    _validate_dag(stages, source)
    _validate_reads_from_ordering(stages, source)

    return WorkflowDefinition(
        name=data["name"],
        version=str(data["version"]),
        description=data["description"],
        trigger=trigger,
        stages=stages,
        workspace_dir=data.get("workspace_dir"),
        metadata=data.get("metadata") or {},
        includes=includes,
    )


# ---------------------------------------------------------------------------
# Component parsers
# ---------------------------------------------------------------------------


def _parse_trigger(data: dict[str, Any], source: str) -> TriggerSpec:
    if not isinstance(data, dict):
        raise WorkflowParseError(f"{source}: 'trigger' must be a mapping")
    if "source" not in data:
        raise WorkflowParseError(f"{source}: trigger missing required key 'source'")
    params = data.get("params") or {}
    if not isinstance(params, dict):
        raise WorkflowParseError(f"{source}: trigger 'params' must be a mapping, got {type(params).__name__}")
    return TriggerSpec(
        source=data["source"],
        params={str(k): str(v) for k, v in params.items()},
    )


def _parse_agent(data: dict[str, Any], source: str) -> AgentSpec:
    if not isinstance(data, dict):
        raise WorkflowParseError(f"{source}: 'agent' must be a mapping")
    if "role" not in data:
        raise WorkflowParseError(f"{source}: agent missing required key 'role'")
    tools = data.get("tools") or []
    if tools and not isinstance(tools, (list, tuple)):
        raise WorkflowParseError(f"{source}: agent 'tools' must be a list, got {type(tools).__name__}")
    access_str = data.get("access", AgentAccess.read_only.value)
    try:
        access = AgentAccess(access_str)
    except ValueError:
        valid = ", ".join(a.value for a in AgentAccess)
        raise WorkflowParseError(
            f"{source}: agent has invalid access '{access_str}' (valid: {valid})"
        ) from None
    return AgentSpec(
        role=data["role"],
        model=data.get("model"),
        tools=tuple(str(t) for t in tools),
        access=access,
    )


def _parse_output(data: dict[str, Any], source: str) -> OutputSpec:
    if not isinstance(data, dict):
        raise WorkflowParseError(f"{source}: output entry must be a mapping")
    if "name" not in data:
        raise WorkflowParseError(f"{source}: output missing required key 'name'")
    if "mode" not in data:
        raise WorkflowParseError(f"{source}: output '{data['name']}' missing required key 'mode'")

    mode_str = data["mode"]
    try:
        mode = OutputMode(mode_str)
    except ValueError:
        valid = ", ".join(m.value for m in OutputMode)
        raise WorkflowParseError(
            f"{source}: output '{data['name']}' has invalid mode '{mode_str}' "
            f"(valid: {valid})"
        ) from None

    input_mapping = data.get("input_mapping") or {}
    if input_mapping and not isinstance(input_mapping, dict):
        raise WorkflowParseError(
            f"{source}: output '{data['name']}' 'input_mapping' must be a mapping, got {type(input_mapping).__name__}"
        )
    return OutputSpec(
        name=data["name"],
        mode=mode,
        description=data.get("description", ""),
        skill=data.get("skill"),
        input_mapping=dict(input_mapping),
        template_ref=data.get("template_ref"),
        writing_guide_ref=data.get("writing_guide_ref"),
        example_ref=data.get("example_ref"),
        schema=data.get("schema"),
        when=data.get("when"),
    )


def _parse_domain_rule(data: dict[str, Any], source: str) -> DomainRule:
    if not isinstance(data, dict):
        raise WorkflowParseError(f"{source}: domain_rule entry must be a mapping")
    for key in ("id", "description"):
        if key not in data:
            raise WorkflowParseError(f"{source}: domain_rule missing required key '{key}'")
    severity_str = data.get("severity", "minor")
    try:
        severity = RuleSeverity(severity_str)
    except ValueError:
        valid = ", ".join(s.value for s in RuleSeverity)
        raise WorkflowParseError(
            f"{source}: domain_rule '{data['id']}' has invalid severity "
            f"'{severity_str}' (valid: {valid})"
        ) from None
    category_str = data.get("category", "accuracy")
    try:
        category = RuleCategory(category_str)
    except ValueError:
        valid = ", ".join(c.value for c in RuleCategory)
        raise WorkflowParseError(
            f"{source}: domain_rule '{data['id']}' has invalid category "
            f"'{category_str}' (valid: {valid})"
        ) from None
    return DomainRule(
        id=data["id"],
        description=data["description"],
        severity=severity,
        category=category,
        source_cmd=data.get("source_cmd"),
    )


def _parse_validation(data: dict[str, Any], source: str) -> ValidationSpec:
    if not isinstance(data, dict):
        raise WorkflowParseError(f"{source}: 'validation' must be a mapping")
    if "strategy" not in data:
        raise WorkflowParseError(f"{source}: validation missing required key 'strategy'")

    strategy_str = data["strategy"]
    try:
        strategy = ValidationStrategy(strategy_str)
    except ValueError:
        valid = ", ".join(s.value for s in ValidationStrategy)
        raise WorkflowParseError(
            f"{source}: validation has invalid strategy '{strategy_str}' "
            f"(valid: {valid})"
        ) from None

    raw_rules = data.get("domain_rules") or []
    domain_rules = tuple(_parse_domain_rule(r, source) for r in raw_rules)
    criteria = tuple(str(c) for c in (data.get("criteria") or []))

    return ValidationSpec(
        strategy=strategy,
        criteria=criteria,
        domain_rules=domain_rules,
        max_revisions=data.get("max_revisions", 2),
    )


def _parse_output_check(data: dict[str, Any], source: str, stage_name: str) -> OutputCheck:
    """Parse one validates_output entry from a stage block."""
    if not isinstance(data, dict):
        raise WorkflowParseError(
            f"{source}: stage '{stage_name}' validates_output entry must be a mapping"
        )
    if "path" not in data:
        raise WorkflowParseError(
            f"{source}: stage '{stage_name}' validates_output entry missing required key 'path'"
        )
    raw_checks = data.get("checks") or []
    if not isinstance(raw_checks, list):
        raise WorkflowParseError(
            f"{source}: stage '{stage_name}' validates_output 'checks' must be a list, "
            f"got {type(raw_checks).__name__}"
        )
    checks = [str(c) for c in raw_checks]
    _KNOWN_CHECK_PREFIXES = (
        "is_json",
        "is_dict",
        "is_list",
        "has_key:",
        "values_have_key:",
        "list_items_have_key:",
        "non_empty",
    )
    for check in checks:
        if not any(check == p or check.startswith(p) for p in _KNOWN_CHECK_PREFIXES):
            safe_check = check[:64] if len(check) <= 64 else f"{check[:61]}..."
            logger.warning(
                "%s: stage '%s' validates_output has unrecognised check name (len=%d, prefix=%r) — accepted for forward-compat, skipped at runtime",
                source,
                stage_name,
                len(check),
                safe_check,
            )
    raw_path = str(data["path"])
    if not raw_path or os.path.isabs(raw_path) or any(seg == ".." for seg in Path(raw_path).parts):
        raise WorkflowParseError(
            f"{source}: stage '{stage_name}' validates_output path must be a non-empty "
            f"workspace-relative path with no absolute components or '..' segments, got {raw_path!r}"
        )
    return OutputCheck(path=raw_path, checks=checks)


def _parse_fan_out(data: dict[str, Any], source: str, stage_name: str) -> FanOutSpec:
    if not isinstance(data, dict):
        raise WorkflowParseError(f"{source}: stage '{stage_name}' fan_out must be a mapping")
    for key in ("source", "field", "key"):
        if key not in data:
            raise WorkflowParseError(
                f"{source}: stage '{stage_name}' fan_out missing required key '{key}'"
            )
    mode = str(data.get("mode", FanOutMode.AGENT))
    if mode not in FanOutMode.ALL:
        raise WorkflowParseError(
            f"{source}: stage '{stage_name}' fan_out has invalid mode '{mode}' "
            f"(valid: {', '.join(FanOutMode.ALL)})"
        )
    return FanOutSpec(
        source=str(data["source"]),
        field=str(data["field"]),
        key=str(data["key"]),
        mode=mode,
        script=str(data.get("script") or ""),
        output_schema=str(data.get("output_schema") or ""),
    )


def _parse_executor(
    data: dict[str, Any], source: str, stage_name: str
) -> tuple[str, str]:
    """Parse and validate the executor + script pair from a stage block."""
    executor = str(data.get("executor", "agent"))
    if executor not in ("agent", "worker_queue", "inline"):
        raise WorkflowParseError(
            f"{source}: stage '{stage_name}' has invalid executor '{executor}' "
            f"(valid: agent, worker_queue, inline)"
        )
    script = str(data.get("script") or "")
    if executor == "worker_queue" and not script.strip():
        raise WorkflowParseError(
            f"{source}: stage '{stage_name}' has executor='worker_queue' but "
            f"missing/empty 'script'"
        )
    return executor, script


def _parse_stage(data: dict[str, Any], source: str) -> StageSpec:  # NOSONAR - sequential guard clauses
    if not isinstance(data, dict):
        raise WorkflowParseError(f"{source}: stage entry must be a mapping")
    for key in ("name", "kind", "description"):
        if key not in data:
            raise WorkflowParseError(f"{source}: stage missing required key '{key}'")

    executor, script = _parse_executor(data, source, str(data.get("name", "")))
    if executor != "inline" and "agent" not in data:
        raise WorkflowParseError(f"{source}: stage missing required key 'agent'")

    stage_name = data["name"]
    kind_str = data["kind"]
    try:
        kind = StageKind(kind_str)
    except ValueError:
        valid = ", ".join(k.value for k in StageKind)
        raise WorkflowParseError(
            f"{source}: stage '{stage_name}' has invalid kind '{kind_str}' "
            f"(valid: {valid})"
        ) from None

    if "agent" in data:
        agent = _parse_agent(data["agent"], source)
    else:
        agent = AgentSpec(role="inline")

    raw_outputs = data.get("outputs") or []
    outputs = tuple(_parse_output(o, source) for o in raw_outputs)

    validation = None
    if "validation" in data and data["validation"] is not None:
        validation = _parse_validation(data["validation"], source)

    fan_out = None
    if "fan_out" in data and data["fan_out"] is not None:
        fan_out = _parse_fan_out(data["fan_out"], source, stage_name)

    sub_workflow = str(data.get("sub_workflow") or "")
    if kind == StageKind.sub_workflow and not sub_workflow.strip():
        raise WorkflowParseError(
            f"{source}: stage '{stage_name}' has kind='sub-workflow' but "
            f"missing or empty 'sub_workflow' path"
        )
    if kind != StageKind.sub_workflow and sub_workflow.strip():
        raise WorkflowParseError(
            f"{source}: stage '{stage_name}' sets 'sub_workflow' but kind='{kind_str}' "
            f"(only allowed on kind='sub-workflow' stages)"
        )

    raw_validates_output = data.get("validates_output") or []
    if not isinstance(raw_validates_output, list):
        raise WorkflowParseError(
            f"{source}: stage '{stage_name}' 'validates_output' must be a list, "
            f"got {type(raw_validates_output).__name__}"
        )
    validates_output = [_parse_output_check(vc, source, stage_name) for vc in raw_validates_output]

    return StageSpec(
        name=stage_name,
        kind=kind,
        description=data["description"],
        agent=agent,
        depends_on=tuple(str(d) for d in (data.get("depends_on") or [])),
        outputs=outputs,
        validation=validation,
        human_gate=data.get("human_gate", False),
        required=data.get("required", True),
        reads_from=tuple(str(r) for r in (data.get("reads_from") or [])),
        writes_to=tuple(str(w) for w in (data.get("writes_to") or [])),
        fan_out=fan_out,
        executor=executor,
        script=script,
        when=data.get("when"),
        sub_workflow=sub_workflow,
        validates_output=validates_output,
    )


# ---------------------------------------------------------------------------
# Cross-stage validators
# ---------------------------------------------------------------------------


def _validate_unique_names(stages: tuple[StageSpec, ...], source: str) -> None:
    """Reject duplicate stage names."""
    seen: set[str] = set()
    for stage in stages:
        if stage.name in seen:
            raise WorkflowParseError(f"{source}: duplicate stage name '{stage.name}'")
        seen.add(stage.name)


def _validate_refs(stages: tuple[StageSpec, ...], source: str) -> None:
    """Ensure depends_on and reads_from reference existing stage names."""
    names = {s.name for s in stages}
    for stage in stages:
        for dep in stage.depends_on:
            if dep not in names:
                raise WorkflowParseError(
                    f"{source}: stage '{stage.name}' depends_on unknown stage '{dep}'"
                )
        for ref in stage.reads_from:
            if ref not in names:
                raise WorkflowParseError(
                    f"{source}: stage '{stage.name}' reads_from unknown stage '{ref}'"
                )


def _validate_dag(stages: tuple[StageSpec, ...], source: str) -> None:
    """Detect cycles in the dependency graph via iterative DFS."""
    adjacency: dict[str, list[str]] = {s.name: list(s.depends_on) for s in stages}
    state: dict[str, int] = dict.fromkeys(adjacency, 0)

    for start in adjacency:
        if state[start] == 2:
            continue
        _dfs_visit(start, adjacency, state, source)


def _dfs_visit(
    start: str,
    adjacency: dict[str, list[str]],
    state: dict[str, int],
    source: str,
) -> None:
    """Run iterative DFS from *start*, updating *state* in place."""
    stack: list[tuple[str, int]] = [(start, 0)]
    while stack:
        node, idx = stack.pop()
        if idx == 0:
            if state[node] == 1:
                raise WorkflowParseError(
                    f"{source}: dependency cycle detected involving stage '{node}'"
                )
            if state[node] == 2:
                continue
            state[node] = 1
        neighbors = adjacency.get(node, [])
        if idx < len(neighbors):
            stack.append((node, idx + 1))
            stack.append((neighbors[idx], 0))
        else:
            state[node] = 2


def _validate_reads_from_ordering(
    stages: tuple[StageSpec, ...], source: str
) -> None:
    """Validate that reads_from entries are transitively reachable via depends_on."""
    deps: dict[str, set[str]] = {s.name: set(s.depends_on) for s in stages}
    _cache: dict[str, set[str]] = {}

    def _transitive_deps(name: str) -> set[str]:
        if name in _cache:
            return _cache[name]
        visited: set[str] = set()
        stack = list(deps.get(name, set()))
        while stack:
            dep = stack.pop()
            if dep not in visited:
                visited.add(dep)
                stack.extend(deps.get(dep, set()) - visited)
        _cache[name] = visited
        return visited

    for spec in stages:
        if not spec.reads_from:
            continue
        reachable = _transitive_deps(spec.name)
        for rf in spec.reads_from:
            if rf not in reachable:
                raise WorkflowParseError(
                    f"{source}: stage '{spec.name}' reads_from '{rf}' but "
                    f"'{rf}' is not a transitive dependency (via depends_on). "
                    f"Add '{rf}' to the depends_on chain to ensure ordering."
                )
