"""Dispatch subcommands for the workflow CLI.

Handles parse, run, lint, list, status, init-workspace, resume,
and validate-fragment command handlers, plus their shared helpers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from core.cli_errors import CLIError, ExitCode
from core.cli_output import emit_rows
from workflow.cli_helpers import check_workflow_path, format_workflow_not_found
from workflow.compiler import resolve_params
from workflow.include import parse_fragment
from workflow.models import StageStatus
from workflow.parser import WorkflowParseError, parse_workflow

if TYPE_CHECKING:
    from workflow.models import WorkflowDefinition, WorkflowManifest


# ---------------------------------------------------------------------------
# Shared load helpers
# ---------------------------------------------------------------------------


def _parse_workflow_safe(path: str) -> WorkflowDefinition:
    """Wrap parse_workflow with friendly CLIError on ImportError or parse failure.

    Shared by _load_definition and _build_resolved_params so the interpreter/
    remediation message is never duplicated and cannot be missed by a new call site.
    """
    try:
        return parse_workflow(path)
    except ImportError as exc:
        # An import failure (e.g. missing PyYAML) is an environment problem,
        # not a content error in the workflow file.
        raise CLIError(
            f"Missing dependency '{exc.name}' (interpreter: {sys.executable}). "
            "Run 'make venv' and use the repo .venv interpreter.",
            ExitCode.ERROR,
        ) from exc
    except WorkflowParseError as exc:
        raise CLIError(f"Parse error: {exc}", ExitCode.ERROR) from exc


def _load_definition(path: str) -> WorkflowDefinition:
    """Parse a workflow YAML, raising CLIError on failure."""
    return _parse_workflow_safe(path)


def _load_manifest(
    path: str,
    trigger_params: dict[str, str] | None = None,
) -> tuple[WorkflowDefinition, WorkflowManifest]:
    """Parse + compile a workflow, raising CLIError on failure."""
    from workflow.compiler import WorkflowCompileError, compile_workflow
    defn = _load_definition(path)
    try:
        return defn, compile_workflow(defn, trigger_params=trigger_params)
    except WorkflowCompileError as exc:
        raise CLIError(f"Compile error: {exc}", ExitCode.ERROR) from exc


# ---------------------------------------------------------------------------
# Param helpers
# ---------------------------------------------------------------------------


def _parse_params(raw: list[str]) -> tuple[dict[str, str], str | None]:
    """Parse key=value param strings. Returns (params_dict, error_message)."""
    params: dict[str, str] = {}
    for p in raw:
        if "=" not in p:
            return {}, f"Invalid param format (expected key=value): {p}"
        k, v = p.split("=", 1)
        params[k] = v
    return params, None


def _build_resolved_params(path: str, cli_params: dict[str, str]) -> dict[str, str]:
    """Merge trigger-default and CLI params in priority order."""
    defn_only = _parse_workflow_safe(path)
    trigger_defaults = defn_only.trigger.params if defn_only.trigger else {}
    work_dir = str(Path.cwd() / "out")
    built_in_params = {"work_dir": work_dir}
    return {**built_in_params, **trigger_defaults, **cli_params}


def _resolve_base_dir(
    override: str | None,
    defn: WorkflowDefinition,
    params: dict[str, str],
) -> str:
    """Resolve the workspace base directory.

    Expands ``~`` and environment variables in the resolved path so that
    YAML param defaults such as ``~/.local/share/dancing-bear/resume/foo``
    work without requiring an absolute path in the workflow file.
    """
    if override:
        return os.path.expandvars(os.path.expanduser(override))
    if defn.workspace_dir:
        resolved = resolve_params(defn.workspace_dir, params) if params else defn.workspace_dir
        expanded = os.path.expandvars(os.path.expanduser(resolved))
        return str(Path(expanded).parent)
    import tempfile
    return tempfile.gettempdir()


def _confirm_execution(name: str, stage_count: int) -> bool:
    """Prompt for confirmation when stdin is a TTY; skip when non-interactive."""
    print(f"About to execute workflow '{name}' with {stage_count} stages.", file=sys.stderr)
    if sys.stdin.isatty():
        print("This will run agent tasks. Proceed? [y/N] ", end="", flush=True, file=sys.stderr)
        return input().lower() in ("y", "yes")
    print("Non-interactive stdin detected; proceeding without confirmation.", file=sys.stderr)
    return True


# ---------------------------------------------------------------------------
# Run-ID and plan helpers
# ---------------------------------------------------------------------------


def _generate_run_id(workflow_name: str) -> str:
    """Generate a run ID from workflow name, current date, and a short random suffix."""
    import random
    import string
    from core.date_utils import iso_now

    date_part = iso_now()[:10].replace("-", "")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))  # nosec B311 - run ID is not security-sensitive  # noqa: S311
    return f"{workflow_name}-{date_part}-{suffix}"


_TERMINAL_SUCCESS = frozenset(["success"])


def _stage_names_from_plan(workspace: Path) -> list[str]:
    """Extract ordered stage names from plan.json, or return [] if unavailable."""
    plan_path = workspace / "plan.json"
    if not plan_path.is_file():
        return []
    try:
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        names: list[str] = []
        for group in plan_data.get("parallel_groups", []):
            names.extend(group.get("stages", []))
        return names
    except (json.JSONDecodeError, OSError):
        return []


def _stage_names_from_manifest(workspace: Path) -> list[str]:
    """Extract stage names from manifest.json parallel_groups."""
    manifest_path = workspace / "manifest.json"
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        names: list[str] = []
        for group in manifest_data.get("parallel_groups", []):
            if isinstance(group, list):
                names.extend(group)
        return names
    except (json.JSONDecodeError, OSError):
        return []


def _build_stage_row(name: str, status: StageStatus | None) -> dict[str, str]:
    """Build a resume table row for a single stage."""
    if status is None:
        return {"stage": name, "status": "-", "needs_run": "yes", "reason": "not yet attempted"}
    if status.value in _TERMINAL_SUCCESS:
        return {"stage": name, "status": status.value, "needs_run": "no", "reason": "already complete"}
    reason = "previous attempt failed" if status == StageStatus.failed else f"status={status.value}"
    return {"stage": name, "status": status.value, "needs_run": "yes", "reason": reason}


def _build_plan_json(
    workflow_name: str,
    run_id: str,
    manifest: WorkflowManifest,
) -> dict:
    """Build the plan.json payload from a compiled manifest."""
    stage_details: dict = {}
    for name, rs in manifest.resolved_stages.items():
        spec = rs.spec
        stage_details[name] = {
            "kind": spec.kind.value,
            "agent_role": spec.agent.role,
            "human_gate": spec.human_gate,
            "required": spec.required,
            "depends_on": list(spec.depends_on),
            "reads_from": list(spec.reads_from),
            "writes_to": list(spec.writes_to),
        }

    groups = [
        {"group": i, "stages": list(g), "parallelism": len(g)}
        for i, g in enumerate(manifest.parallel_groups)
    ]

    return {
        "workflow_name": workflow_name,
        "run_id": run_id,
        "total_stages": len(manifest.resolved_stages),
        "parallel_groups": groups,
        "stage_details": stage_details,
    }


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_parse(args: argparse.Namespace) -> int:
    """Parse a workflow YAML and display its structure."""
    from workflow.cli import _emit_one
    if not check_workflow_path(args.path):
        return 1
    defn = _load_definition(args.path)
    summary = {
        "name": defn.name, "version": defn.version, "description": defn.description,
        "trigger_source": defn.trigger.source, "stage_count": len(defn.stages),
    }
    stages = [{
        "name": s.name, "kind": s.kind.value, "agent_role": s.agent.role,
        "depends_on": ", ".join(s.depends_on) or "-", "required": s.required,
    } for s in defn.stages]
    if args.format == "table":
        _emit_one(summary, fmt=args.format)
        emit_rows(stages, fmt=args.format, headers=["name", "kind", "agent_role", "depends_on", "required"])
    else:
        _emit_one({**summary, "stages": stages}, fmt=args.format)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Parse + compile + execute a workflow."""
    from workflow.cli import _emit_one
    from workflow.orchestrator import OrchestratorConfig, WorkflowOrchestrator
    if not check_workflow_path(args.path):
        return 1
    dry_run = not args.execute

    params, err = _parse_params(args.params)
    if err:
        print(err, file=sys.stderr)
        return 1

    resolved_params = _build_resolved_params(args.path, params)
    defn, manifest = _load_manifest(args.path, trigger_params=resolved_params or None)

    workspace = _resolve_base_dir(args.workspace, defn, resolved_params)

    if not dry_run and not _confirm_execution(defn.name, len(defn.stages)):
        print("Aborted.", file=sys.stderr)
        return 1

    # If --workspace points to an existing workspace (has manifest.json), use it
    # directly so we don't nest a new sub-directory inside it.
    existing_manifest = Path(workspace) / "manifest.json"
    if args.workspace and existing_manifest.exists():
        orchestrator = WorkflowOrchestrator.resume(
            manifest=manifest, workspace_dir=workspace,
            trigger_params=resolved_params or None,
        )
    else:
        orchestrator = WorkflowOrchestrator(
            OrchestratorConfig(
                manifest=manifest,
                workspace_dir=workspace,
                run_id=args.run_id,
                dry_run=dry_run,
                trigger_params=resolved_params or {},
            )
        )
    result = orchestrator.run()
    _emit_one({
        "run_id": result.run_id, "status": result.status.value,
        "workspace": result.workspace_dir, "started_at": result.started_at,
        "dry_run": dry_run, "stages_completed": len(result.stage_results),
        "stages_total": len(defn.stages),
    }, fmt=args.format)
    stage_rows = [{
        "stage": name, "status": sr.status.value,
        "duration_ms": sr.duration_ms, "errors": "; ".join(sr.errors) or "-",
    } for name, sr in result.stage_results.items()]
    emit_rows(stage_rows, fmt=args.format, headers=["stage", "status", "duration_ms", "errors"])
    if dry_run or result.status in (StageStatus.success, StageStatus.awaiting_human):
        return 0
    print(
        f"Workflow did not complete successfully: status={result.status.value}",
        file=sys.stderr,
    )
    return 2


def _cmd_lint(args: argparse.Namespace) -> int:
    """Validate workflow YAML structure without executing the workflow."""
    from workflow.cli import _emit_one
    from workflow.linter import lint_workflow

    if not Path(args.file).is_file():
        print(format_workflow_not_found(args.file), file=sys.stderr)
        return 1
    result = lint_workflow(args.file, check_commands=getattr(args, "check_commands", False))

    if args.strict and result.warnings:
        from workflow.linter import LintError
        for w in result.warnings:
            result.errors.append(LintError(stage=w.stage, field=w.field, message=w.message))
        result.warnings.clear()
        result.valid = False

    data = result.as_dict()
    _emit_one(data, fmt=args.format)
    return 0 if result.valid else 1


def _cmd_validate_fragment(args: argparse.Namespace) -> int:
    """Validate a fragment YAML (must have top-level 'fragment: true' key)."""
    from workflow.cli import _emit_one
    path = Path(args.file)
    if not path.exists():
        result: dict = {
            "file": str(path),
            "valid": False,
            "error": f"fragment file not found: {path}",
        }
        _emit_one(result, fmt=args.format)
        return 1

    try:
        stages = parse_fragment(path)
    except WorkflowParseError as exc:
        result = {
            "file": str(path),
            "valid": False,
            "error": str(exc),
        }
        _emit_one(result, fmt=args.format)
        return 1

    stage_names = {s.name for s in stages}
    dangling = [
        dep
        for s in stages
        for dep in s.depends_on
        if dep not in stage_names
    ]

    is_valid = not (args.strict and dangling)
    result = {
        "file": str(path),
        "valid": is_valid,
        "stage_count": len(stages),
        "stages": [s.name for s in stages],
        "warnings": dangling,
    }
    _emit_one(result, fmt=args.format)
    return 0 if is_valid else 1


def _cmd_list(args: argparse.Namespace) -> int:
    """List available workflow definitions from workflows/ directory."""
    from workflow.cli_helpers import _EXCLUDED_SUBDIRS

    workflows_dir = Path.cwd() / "workflows"
    if not workflows_dir.is_dir():
        print("No workflows/ directory found in current directory.", file=sys.stderr)
        return 1

    rows = []
    for path in sorted(
        p
        for p in workflows_dir.rglob("*.yaml")
        if not _EXCLUDED_SUBDIRS.intersection(p.relative_to(workflows_dir).parts[:-1])
    ):
        rel = str(path.relative_to(Path.cwd()))
        try:
            defn = parse_workflow(path)
            rows.append({"file": rel, "name": defn.name, "version": defn.version,
                         "description": defn.description, "stages": len(defn.stages)})
        except ImportError as exc:
            # An import failure is an environment problem (e.g. missing PyYAML),
            # not a property of this file.  Surface it once as a hard error so
            # it can't be silently swallowed across all 40+ rows in the table.
            raise CLIError(
                f"Missing dependency '{exc.name}' (interpreter: {sys.executable}). "
                "Run 'make venv' and use the repo .venv interpreter.",
                ExitCode.ERROR,
            ) from exc
        except Exception:  # noqa: BLE001 # nosec B110 - per-file parse resilience: skip malformed YAML and continue listing
            rows.append({"file": rel, "name": "?", "version": "?",
                         "description": "(parse error)", "stages": 0})

    if not rows:
        print("No workflow YAML files found in workflows/.", file=sys.stderr)
        return 1
    emit_rows(rows, fmt=args.format, headers=["file", "name", "version", "description", "stages"])
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Show status of a workflow run from its workspace directory."""
    from workflow.persistence import list_stage_results
    workspace = Path(args.workspace_dir)
    if not workspace.is_dir():
        print(
            format_workflow_not_found(args.workspace_dir, label="workspace"),
            file=sys.stderr,
        )
        return 1

    results = list_stage_results(workspace)
    if not results:
        print(f"No stage results found in {workspace}.", file=sys.stderr)
        return 1
    rows = [{
        "index": sr.stage_index, "stage": sr.stage_name, "status": sr.status.value,
        "duration_ms": sr.duration_ms, "errors": "; ".join(sr.errors) or "-",
    } for sr in results]
    emit_rows(rows, fmt=args.format, headers=["index", "stage", "status", "duration_ms", "errors"])
    return 0


def _cmd_init_workspace(args: argparse.Namespace) -> int:
    """Create workspace dir, write manifest.json + plan.json, and print workspace path."""
    from workflow.persistence import init_workspace, write_manifest
    from core.fileutil import atomic_write_json

    if not check_workflow_path(args.path):
        return 1

    params, err = _parse_params(args.params)
    if err:
        print(err, file=sys.stderr)
        return 1

    resolved_params = _build_resolved_params(args.path, params)
    defn, manifest = _load_manifest(args.path, trigger_params=resolved_params or None)

    run_id = args.run_id or _generate_run_id(defn.name)
    base_dir = _resolve_base_dir(args.base_dir or None, defn, resolved_params)

    workspace = init_workspace(defn.name, run_id, base_dir=base_dir)

    write_manifest(
        workspace,
        manifest,
        yaml_path=str(Path(args.path).resolve()),
        run_id=run_id,
        trigger_params=resolved_params or None,
    )

    plan = _build_plan_json(defn.name, run_id, manifest)
    atomic_write_json(workspace / "plan.json", plan)

    print(str(workspace))
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    """Show which stages need re-running in a workspace."""
    from workflow.persistence import list_stage_results, read_manifest
    workspace = Path(args.workspace_dir)
    if not workspace.is_dir():
        print(
            format_workflow_not_found(args.workspace_dir, label="workspace"),
            file=sys.stderr,
        )
        return 1

    if read_manifest(workspace) is None:
        print(f"No manifest.json found in {workspace}.", file=sys.stderr)
        return 1

    stage_names = _stage_names_from_plan(workspace) or _stage_names_from_manifest(workspace)

    existing: dict[str, StageStatus] = {
        sr.stage_name: sr.status for sr in list_stage_results(workspace)
    }

    if not stage_names:
        stage_names = sorted(existing.keys())

    rows = [_build_stage_row(name, existing.get(name)) for name in stage_names]
    has_pending = any(r["needs_run"] == "yes" for r in rows)

    emit_rows(rows, fmt=args.format, headers=["stage", "status", "needs_run", "reason"])
    return 2 if has_pending else 0
