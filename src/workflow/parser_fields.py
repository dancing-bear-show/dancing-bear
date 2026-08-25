"""Component field parsers for workflow YAML stage/agent/output/validation blocks."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from core.text_utils import truncate_text

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
)
from .parser_errors import WorkflowParseError

logger = logging.getLogger(__name__)


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


_VALID_ISOLATIONS = frozenset({"worktree"})
_KNOWN_AGENT_KEYS = frozenset({"role", "model", "tools", "access", "isolation"})


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
    isolation = data.get("isolation")
    if isolation is not None:
        # Check the type before set membership: an unhashable YAML value such as
        # `isolation: [worktree]` or `isolation: {}` would raise TypeError out of
        # the `in` test, surfacing as a traceback rather than a parse error.
        if not isinstance(isolation, str) or isolation not in _VALID_ISOLATIONS:
            valid = ", ".join(sorted(_VALID_ISOLATIONS))
            raise WorkflowParseError(
                f"{source}: agent has invalid isolation {isolation!r} (valid: {valid})"
            )
    # Reject unknown keys rather than dropping them. A silently ignored
    # 'isolation: worktree' let parallel code-writers interleave edits in one
    # tree while the workflow read as if they were isolated.
    unknown = set(data) - _KNOWN_AGENT_KEYS
    if unknown:
        known = ", ".join(sorted(_KNOWN_AGENT_KEYS))
        # sort by str: YAML permits non-string keys, so a block mixing `1:` and
        # `timeout:` would make a bare sorted() raise TypeError instead of the
        # parse error this branch promises.
        listed = sorted((str(k) for k in unknown))
        raise WorkflowParseError(
            f"{source}: agent has unknown key(s) {listed} (valid: {known})"
        )
    return AgentSpec(
        role=data["role"],
        model=data.get("model"),
        tools=tuple(str(t) for t in tools),
        access=access,
        isolation=isolation,
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
            safe_check = truncate_text(check, 64, "...")
            logger.warning(
                "%s: stage '%s' validates_output has unrecognised check name (len=%d, value=%r) — accepted for forward-compat, skipped at runtime",
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


def _check_sub_workflow_consistency(
    kind: StageKind, kind_str: str, sub_workflow: str, source: str, stage_name: str
) -> None:
    """Verify sub_workflow is set iff kind == sub_workflow."""
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
    _check_sub_workflow_consistency(kind, kind_str, sub_workflow, source, stage_name)

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
