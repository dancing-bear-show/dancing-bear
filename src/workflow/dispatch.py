"""Dispatch module — builds agent dispatch instructions from workflow stages.

Bridges the Python engine to Claude Code's agent system by translating
ResolvedStage data into structured dispatch dicts that the workflow skill
reads to spawn the right agent with the right prompt.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .models import ResolvedStage, StageKind, ValidationSpec

logger = logging.getLogger(__name__)

KNOWN_ROLES: frozenset[str] = frozenset({
    "researcher",
    "code-writer",
    "doc-writer",
    "reviewer",
    "tester",
    "ci-fixer",
    "unit-validator",
    "cross-unit-validator",
    "fact-checker",
    "critic",
    "haiku-reviewer",
    "workflow-author",
    "thread-fixer",
    "code-writer-opus",
    "tester-opus",
    "Explore",
    "Plan",
})

_RESULT_FMT = (
    '{{"stage_name": "{name}", "stage_index": {index}, "status": "success",\n'
    '  "started_at": "<ISO8601>", "finished_at": "<ISO8601>",\n'
    '  "duration_ms": <ms>, "output_files": [<files written>],\n'
    '  "data": {{<summary>}}, "errors": []}}'
)

# Rendered after the JSON example, outside the code fence. The example itself
# must stay copy-pasteable JSON, so the choice of status is explained here
# rather than inline — an agent that copies an annotated example verbatim
# writes an unparsable stage result and breaks orchestration.
_STATUS_NOTE = (
    'Set `"status"` to `"success"` or `"failed"` — report what actually '
    "happened. Use `\"failed\"` if a command you were told to run exited "
    "non-zero, a required output could not be written, or you could not "
    "complete the stage as specified, and list the reasons as strings in "
    '`"errors"`. Downstream stages are skipped only when a required stage '
    'reports `"failed"`, so reporting `"success"` on failed work lets later '
    "stages act on it."
)

_FINDINGS_EXAMPLE = json.dumps(
    [{"id": "F-001", "status": "PASS|FAIL|WARN", "claim": "...",
      "expected": "...", "actual": "...", "fix": "..."}],
    indent=2,
)

_ISOLATED_ROOT = "<your-cwd>"


# -- Helpers ------------------------------------------------------------------

def _ws(workspace_dir: str | Path) -> str:
    return str(Path(workspace_dir).resolve())


def _is_isolated(stage: ResolvedStage) -> bool:
    """True if this stage's agent runs in its own git worktree."""
    agent = stage.spec.agent
    return bool(agent and agent.isolation)


def _read_paths(stage: ResolvedStage, ws: str) -> list[str]:
    """Paths the agent reads its upstream inputs from.

    An isolated agent is directed to its own ``inputs/`` rather than the shared
    workspace: the orchestrator copies upstream artifacts in before signalling
    proceed, so a ``{ws}/...`` read here would either prompt or reach outside
    the worktree, breaking the isolation boundary in the input direction the
    same way an unguarded write breaks it in the output direction.
    """
    if not stage.spec.reads_from:
        return []
    if _is_isolated(stage):
        # The orchestrator mirrors each upstream stage's declared writes_to
        # under inputs/, preserving relative paths. Do NOT name a single
        # synthetic <name>.json per dependency: a stage may declare several
        # outputs of different types (design.md AND design.json), and naming
        # one would tell the agent to read a file that does not exist while
        # silently omitting the rest.
        return [
            "<your-cwd>/inputs/ — every output of these upstream stages, "
            "copied in before you start, at the same relative path the "
            "upstream stage declared (e.g. an upstream `outputs/design.md` "
            f"arrives as `<your-cwd>/inputs/outputs/design.md`): "
            f"{', '.join(stage.spec.reads_from)}",
            "<your-cwd>/inputs/stages/ — each upstream stage's result JSON",
        ]
    paths = [f"{ws}/stages/*-{name}.json" for name in stage.spec.reads_from]
    paths.append(f"{ws}/outputs/")
    return paths


_WORKSPACE_SUBDIRS = ("outputs/", "validation/", "stages/", "dispatch/")


def _write_paths(stage: ResolvedStage, ws: str) -> list[str]:
    """Absolute output paths for the agent's prompt.

    An isolated agent cannot write the shared workspace, so it is directed to
    the same relative layout under its OWN cwd; the orchestrator copies those
    files back. Pointing an isolated agent at ``{ws}/...`` produces a prompt it
    cannot satisfy while the orchestrator waits on files that never appear.
    """
    root = _ISOLATED_ROOT if _is_isolated(stage) else ws
    paths: list[str] = []
    for f in stage.spec.writes_to:
        if any(f.startswith(prefix) for prefix in _WORKSPACE_SUBDIRS):
            paths.append(f"{root}/{f}")
        else:
            paths.append(f"{root}/outputs/{f}")
    return paths


def _completion(stage: ResolvedStage, ws: str) -> str:
    root = _ISOLATED_ROOT if _is_isolated(stage) else ws
    result_path = f"{root}/stages/{stage.index:03d}-{stage.spec.name}.json"
    isolated_note = (
        "\n\nYou are running in your OWN git worktree. Write every path above "
        "as an absolute path under your own cwd — NOT under the shared "
        "workspace, and never as a bare relative path (that resolves against "
        "the orchestrator's cwd, outside your worktree). The orchestrator "
        "copies your outputs/ and stages/ files back after you finish."
        if _is_isolated(stage)
        else ""
    )
    return (
        "## Completion\n"
        f"When done, write your stage result to: {result_path}{isolated_note}\n\n"
        f"Use this structure:\n```json\n"
        f"{_RESULT_FMT.format(name=stage.spec.name, index=stage.index)}\n```\n\n"
        f"{_STATUS_NOTE}"
    )


def _section(heading: str, items: list[str]) -> list[str]:
    """Build a markdown section with bulleted items."""
    return [f"## {heading}"] + [f"- {i}" for i in items] + [""]


def _header(stage: ResolvedStage, workflow_name: str, verb: str = "executing") -> list[str]:
    return [
        f"You are {verb} stage '{stage.spec.name}' in workflow '{workflow_name}'.",
        "",
        (
            "**Data provenance rule**: Use ONLY data from workspace files and CLI command "
            "outputs. Do not cite numbers, counts, or facts from your prompt context or "
            "prior knowledge. Every claim in your output must trace to a file you read or "
            "a command you ran. If data is unavailable, say so \u2014 do not fill gaps with "
            "assumptions."
        ),
        "",
        (
            "**No external side effects**: Write ONLY to your own worktree cwd "
            "(you are running isolated; the orchestrator copies your files back). "
            "Only stages with kind=publish are authorized to create external resources."
            if _is_isolated(stage)
            else "**No external side effects**: Write ONLY to the workspace directory. "
            "Only stages with kind=publish are authorized to create external resources."
        ),
        "",
        "**CLI quick reference** (do NOT use --help, use these exact patterns):",
        "- `./bin/mail-assistant filters list -- --format json`",
        "- `./bin/mail-assistant filters apply -- --dry-run --format json`",
        "- `./bin/calendar-assistant events list -- --format json`",
        "- `./bin/schedule-assistant plan -- --format yaml`",
        "",
        "## Task",
        stage.spec.description,
        "",
    ]


# -- Per-kind prompt builders -------------------------------------------------

def _gather(stage: ResolvedStage, wf: str, ws: str) -> str:
    lines = _header(stage, wf)
    write_root = _ISOLATED_ROOT if _is_isolated(stage) else ws
    lines += ["## Workspace", f"Write all output to: {write_root}/outputs/", ""]
    if stage.cli_commands:
        lines += _section("CLI Commands\nRun these commands and capture their output", [f"`{c}`" for c in stage.cli_commands])
    wp = _write_paths(stage, ws)
    if wp:
        lines += _section("Output Files\nWrite results to", wp)
        lines += [
            (
                "Write structured JSON data to the JSON file. "
                "Write a human-readable markdown summary to the .md file."
            ),
            "",
        ]
    lines.append(_completion(stage, ws))
    return "\n".join(lines)


def _action(stage: ResolvedStage, wf: str, ws: str, input_verb: str = "Read prior stage outputs from") -> str:
    """Shared builder for propose, execute, and publish stages."""
    lines = _header(stage, wf)
    rp = _read_paths(stage, ws)
    if rp:
        lines += _section(f"Input Data\n{input_verb}", rp)
    if stage.cli_commands:
        lines += _section("CLI Commands\nRun these commands", [f"`{c}`" for c in stage.cli_commands])
    if stage.template_content:
        lines += ["## Template", "---", stage.template_content, "---", ""]
    if stage.guide_content:
        lines += ["## Writing Guide", "---", stage.guide_content, "---", ""]
    wp = _write_paths(stage, ws)
    if wp:
        lines += _section("Output Files\nWrite results to", wp)
    lines.append(_completion(stage, ws))
    return "\n".join(lines)


def _domain_rules_section(spec: ValidationSpec) -> list[str]:
    """Build the Domain Rules section lines from a validation spec."""
    rules: list[str] = []
    for r in spec.domain_rules:
        entry = f"[{r.severity}] {r.id}: {r.description}"
        if r.source_cmd:
            entry += f"\n  Verify with: `{r.source_cmd}`"
        rules.append(entry)
    return _section("Domain Rules", rules)


def _validate_output_lines(stage: ResolvedStage, ws: str, wp: list[str]) -> list[str]:
    """Return the Output section lines for a validate stage."""
    if wp:
        return _section("Output\nWrite results to", wp)
    # Same isolated-root rule as _write_paths: a validate stage with no
    # explicit writes_to must not be sent to the shared workspace, or the
    # parent waits for files outside the agent's worktree.
    val_root = _ISOLATED_ROOT if _is_isolated(stage) else ws
    return [
        "## Output",
        f"Write findings to: {val_root}/validation/{stage.spec.name}-findings.json",
        f"Write summary to: {val_root}/validation/{stage.spec.name}-summary.md",
        "",
    ]


def _validate(stage: ResolvedStage, wf: str, ws: str) -> str:
    spec = stage.spec.validation
    raw_strategy = spec.strategy if spec else None
    strategy = getattr(raw_strategy, "value", raw_strategy) or "unknown"
    lines = [
        f"You are validating outputs from workflow '{wf}'.",
        "", f"## Strategy: {strategy}", "",
    ]
    if spec and spec.criteria:
        lines += _section("Criteria", list(spec.criteria))
    if spec and spec.domain_rules:
        lines += _domain_rules_section(spec)
    rp = _read_paths(stage, ws)
    if rp:
        lines += _section("Target Data\nRead outputs from", rp)
    lines += [
        "## Instructions",
        "1. Extract every verifiable claim from the target outputs",
        "2. For each claim, check it against the source data or run the verification command",
        "3. Classify each finding as PASS, FAIL, or WARN",
        "4. Return findings as a JSON array", "",
        "## Findings Format", f"```json\n{_FINDINGS_EXAMPLE}\n```", "",
    ]
    wp = _write_paths(stage, ws)
    lines += _validate_output_lines(stage, ws, wp)
    lines.append(_completion(stage, ws))
    return "\n".join(lines)


# -- Public API ---------------------------------------------------------------

_KIND_VERBS: dict[StageKind, str] = {
    StageKind.propose: "Read and summarize prior stage outputs from",
    StageKind.publish: "Read artifacts to publish from",
}


def build_agent_prompt(
    stage: ResolvedStage,
    workflow_name: str,
    workspace_dir: str | Path,
) -> str:
    """Build a complete agent prompt for a stage.

    Constructs the prompt based on stage kind:
    - gather: CLI commands to run, output files to write
    - propose: Prior data to summarize, proposal format
    - execute: Template/guide content OR generation instructions
    - validate: Criteria, domain rules, target data, findings format
    - publish: CLI commands for publishing
    """
    ws = _ws(workspace_dir)
    kind = stage.spec.kind

    if kind == StageKind.gather:
        return _gather(stage, workflow_name, ws)
    if kind == StageKind.validate:
        return _validate(stage, workflow_name, ws)
    verb = _KIND_VERBS.get(kind, "Read prior stage outputs from")
    return _action(stage, workflow_name, ws, input_verb=verb)


def build_dispatch_instruction(
    stage: ResolvedStage,
    workflow_name: str,
    workspace_dir: str | Path,
) -> dict[str, Any]:
    """Build a complete dispatch instruction for the skill to consume.

    Returns a dict with agent_type, prompt, workspace info, and metadata
    that the workflow skill uses to spawn the correct agent.
    """
    ws = _ws(workspace_dir)
    role = stage.spec.agent.role
    if role not in KNOWN_ROLES:
        logger.warning("Unknown agent role '%s' for stage '%s'", role, stage.spec.name)
    agent_type = role
    is_val = stage.spec.kind == StageKind.validate
    val_strategy = stage.spec.validation.strategy if is_val and stage.spec.validation else None

    return {
        "agent_type": agent_type,
        "agent_name": stage.spec.name,
        "stage_name": stage.spec.name,
        "stage_index": stage.index,
        "workflow_name": workflow_name,
        "model": stage.spec.agent.model,
        "isolation": stage.spec.agent.isolation,
        "prompt": build_agent_prompt(stage, workflow_name, workspace_dir),
        "workspace_dir": ws,
        "writes_to": list(stage.spec.writes_to),
        "reads_from": list(stage.spec.reads_from),
        "is_validation": is_val,
        "validation_strategy": getattr(val_strategy, "value", val_strategy) if val_strategy else None,
        "kind": stage.spec.kind.value,
        "sub_workflow": stage.spec.sub_workflow or None,
    }


def build_group_dispatch(
    group: tuple[str, ...],
    resolved_stages: dict[str, ResolvedStage],
    workflow_name: str,
    workspace_dir: str | Path,
) -> list[dict[str, Any]]:
    """Build dispatch instructions for an entire parallel group.

    Returns a list of dispatch dicts, one per stage in the group.
    """
    instructions: list[dict[str, Any]] = []
    for stage_name in group:
        stage = resolved_stages.get(stage_name)
        if stage is None:
            logger.warning("Stage '%s' not found in resolved stages, skipping", stage_name)
            continue
        instructions.append(
            build_dispatch_instruction(stage, workflow_name, workspace_dir)
        )
    return instructions
