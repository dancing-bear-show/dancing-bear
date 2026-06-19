"""Workflow engine CLI.

Subcommands for parsing, compiling, running, and inspecting workflow
definitions and their execution state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from workflow.cli_helpers import check_workflow_path, format_workflow_not_found
from workflow.compiler import resolve_params, validate_dag_contracts
from workflow.include import extract_include_entries, parse_fragment, resolve_fragment_path
from workflow.models import StageStatus
from workflow.parser import WorkflowParseError, parse_workflow

if TYPE_CHECKING:
    from workflow.models import WorkflowDefinition, WorkflowManifest

_PATH_HELP = "Path to workflow YAML file"


def _add_format_argument(
    parser: argparse.ArgumentParser,
    *,
    formats: list[str] | None = None,
    default: str = "table",
) -> None:
    choices = formats or ["table", "json", "yaml"]
    parser.add_argument(
        "--format", "-f",
        choices=choices,
        default=default,
        help=f"Output format (default: {default})",
    )


def _emit_one(data: dict, *, fmt: str = "table") -> None:
    """Print a single dict in the requested format."""
    if fmt == "json":
        print(json.dumps(data, indent=2, default=str))
    elif fmt == "yaml":
        try:
            import yaml
            print(yaml.dump(data, default_flow_style=False).rstrip())
        except ImportError:
            print(json.dumps(data, indent=2, default=str))
    else:
        for k, v in data.items():
            print(f"{k}: {v}")


def _emit_rows(rows: list[dict], *, fmt: str = "table", headers: list[str] | None = None) -> None:
    """Print a list of dicts in the requested format."""
    if not rows:
        return
    if fmt == "json":
        print(json.dumps(rows, indent=2, default=str))
    elif fmt == "yaml":
        try:
            import yaml
            print(yaml.dump(rows, default_flow_style=False).rstrip())
        except ImportError:
            print(json.dumps(rows, indent=2, default=str))
    else:
        keys = headers or list(rows[0].keys())
        widths = {k: max(len(str(k)), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}
        header = "  ".join(str(k).ljust(widths[k]) for k in keys)
        print(header)
        print("-" * len(header))
        for row in rows:
            print("  ".join(str(row.get(k, "")).ljust(widths[k]) for k in keys))


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser and register all subcommands."""
    parser = argparse.ArgumentParser(prog="workflow", description="Workflow engine CLI.")
    sub = parser.add_subparsers(dest="subcommand")

    p_parse = sub.add_parser("parse", help="Parse a workflow YAML and display its structure")
    p_parse.add_argument("path", help=_PATH_HELP)
    _add_format_argument(p_parse, default="table")

    p_compile = sub.add_parser("compile", help="Parse + compile, showing the execution plan")
    p_compile.add_argument("path", help=_PATH_HELP)
    p_compile.add_argument(
        "--no-compile-cache",
        action="store_true",
        dest="no_cache",
        help="Bypass the sha256-keyed compile cache and re-compile from YAML",
    )
    _add_format_argument(p_compile, default="table")

    p_run = sub.add_parser("run", help="Parse + compile + execute a workflow")
    p_run.add_argument("path", help=_PATH_HELP)
    p_run.add_argument("--execute", action="store_true", help="Actually run the workflow (default is dry-run)")
    p_run.add_argument("--workspace", help="Override workspace base directory")
    p_run.add_argument("--params", action="append", default=[], metavar="key=value",
                       help="Trigger parameter overrides (repeatable)")
    p_run.add_argument("--run-id", help="Custom run ID")
    _add_format_argument(p_run, default="table")

    p_lint = sub.add_parser("lint", help="Validate workflow YAML structure without running it")
    p_lint.add_argument("file", help="Path to workflow YAML file")
    p_lint.add_argument(
        "--strict", action="store_true",
        help="Treat warnings as errors (exit non-zero if any warnings exist)",
    )
    p_lint.add_argument(
        "--check-commands", action="store_true", dest="check_commands",
        help="Validate ./bin/<cli> <subcommand> patterns by probing each binary",
    )
    _add_format_argument(p_lint, default="yaml")

    p_list = sub.add_parser("list", help="List available workflow definitions")
    _add_format_argument(p_list, default="table")

    p_status = sub.add_parser("status", help="Show status of a workflow run")
    p_status.add_argument("workspace_dir", help="Workspace directory of the run")
    _add_format_argument(p_status, default="table")

    p_init = sub.add_parser(
        "init-workspace",
        help="Create workspace dir, write manifest.json + plan.json, print workspace path",
    )
    p_init.add_argument("path", help=_PATH_HELP)
    p_init.add_argument("--run-id", dest="run_id", default="", help="Custom run ID (auto-generated if omitted)")
    p_init.add_argument("--base-dir", dest="base_dir", default="", help="Base directory for workspace")
    p_init.add_argument("--params", action="append", default=[], metavar="key=value",
                        help="Trigger parameter overrides (repeatable)")

    p_resume = sub.add_parser(
        "resume",
        help="Show which stages need re-running (exit 0 if all done, exit 2 if stages remain)",
    )
    p_resume.add_argument("workspace_dir", help="Workspace directory of the run to resume")
    _add_format_argument(p_resume, default="table")

    p_vf = sub.add_parser(
        "validate-fragment",
        help="Validate a workflow fragment YAML (must have top-level 'fragment: true' key)",
    )
    p_vf.add_argument("file", help="Path to fragment YAML file")
    p_vf.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    _add_format_argument(p_vf, formats=["json", "yaml", "table"], default="yaml")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Workflow CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.subcommand:
        print(
            "Usage: workflow {parse,compile,run,lint,list,status,init-workspace,resume,validate-fragment} [options]",
            file=sys.stderr,
        )
        return 1

    dispatch = {
        "parse": _cmd_parse, "compile": _cmd_compile, "run": _cmd_run,
        "lint": _cmd_lint, "list": _cmd_list, "status": _cmd_status,
        "init-workspace": _cmd_init_workspace, "resume": _cmd_resume,
        "validate-fragment": _cmd_validate_fragment,
    }
    try:
        return dispatch[args.subcommand](args)
    except Exception as exc:  # noqa: BLE001 # nosec B110 - top-level CLI error handler
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _load_definition(path: str) -> WorkflowDefinition:
    """Parse a workflow YAML, raising SystemExit on failure."""
    try:
        return parse_workflow(path)
    except WorkflowParseError as exc:
        print(f"Parse error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _load_manifest(
    path: str,
    trigger_params: dict[str, str] | None = None,
) -> tuple[WorkflowDefinition, WorkflowManifest]:
    """Parse + compile a workflow, raising SystemExit on failure."""
    from workflow.compiler import WorkflowCompileError, compile_workflow
    defn = _load_definition(path)
    try:
        return defn, compile_workflow(defn, trigger_params=trigger_params)
    except WorkflowCompileError as exc:
        print(f"Compile error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _cmd_parse(args: argparse.Namespace) -> int:
    """Parse a workflow YAML and display its structure."""
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
        _emit_rows(stages, fmt=args.format, headers=["name", "kind", "agent_role", "depends_on", "required"])
    else:
        _emit_one({**summary, "stages": stages}, fmt=args.format)
    return 0


def _fragment_bytes(
    yaml_bytes: bytes,
    yaml_path: Path,
    _visited: frozenset[str] | None = None,
) -> bytes:
    """Return concatenated bytes of all fragment files referenced via include:."""
    visited = _visited if _visited is not None else frozenset()
    parts: list[bytes] = []
    for inc in extract_include_entries(yaml_bytes):
        if not isinstance(inc, dict) or "path" not in inc:
            continue
        p = resolve_fragment_path(str(inc["path"]), yaml_path)
        p_key = str(p.resolve())
        if p_key in visited:
            continue
        try:
            frag_content = p.read_bytes()
        except OSError:
            continue
        parts.append(frag_content)
        parts.append(_fragment_bytes(frag_content, p, _visited=visited | {p_key}))
    return b"".join(parts)


def _compile_cache_path(yaml_bytes: bytes, project_root: str, params: list[str], yaml_path: Path | None = None) -> Path:
    """Return the temp-dir cache file path keyed by YAML content, fragments, root, and params."""
    import tempfile
    frag_bytes = _fragment_bytes(yaml_bytes, yaml_path or Path.cwd())
    key_material = f"{project_root}:{':'.join(sorted(params))}:".encode() + yaml_bytes + frag_bytes
    sha = hashlib.sha256(key_material).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"workflow-compile-{sha}.json"


def _render_compile_output(payload: dict, fmt: str) -> None:
    """Render compile output in the requested format."""
    _excluded = ("groups", "resolutions", "contract_warnings_detail")
    summary = {k: v for k, v in payload.items() if k not in _excluded}
    groups_raw = payload.get("groups", [])
    resolutions_raw = payload.get("resolutions", [])
    warnings_raw = payload.get("contract_warnings_detail", [])
    groups: list[dict] = groups_raw if isinstance(groups_raw, list) else []
    resolutions: list[dict] = resolutions_raw if isinstance(resolutions_raw, list) else []
    warnings: list[dict] = [
        w for w in (warnings_raw if isinstance(warnings_raw, list) else [])
        if isinstance(w, dict) and w.get("message")
    ]
    for w in warnings:
        print(f"contract warning: {w['message']}", file=sys.stderr)
    if fmt == "table":
        _emit_one(summary, fmt=fmt)
        _emit_rows(groups, fmt=fmt, headers=["group", "stages", "parallelism"])
        _emit_rows(resolutions, fmt=fmt,
                   headers=["stage", "template_resolved", "guide_resolved", "cli_commands"])
        if warnings:
            _emit_rows(warnings, fmt=fmt, headers=["stage", "upstream", "message"])
    else:
        _emit_one(payload, fmt=fmt)


def _try_read_cached_compile(cache_path: Path) -> dict | None:
    """Return the cached compile payload, or None if missing/invalid."""
    if not cache_path.exists():
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return cached if isinstance(cached, dict) else None


def _write_once(path: Path, content: bytes) -> None:
    """Write *content* to *path* only if it does not already exist."""
    import os
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, content)
        finally:
            os.close(fd)
    except OSError:
        pass  # nosec B110 - cache write failure is non-fatal


def _build_compile_payload(path: str) -> dict:
    """Load + compile the workflow and build the cache payload dict."""
    defn, manifest = _load_manifest(path)
    max_par = max((len(g) for g in manifest.parallel_groups), default=0)

    contract_warnings = validate_dag_contracts(defn)

    summary = {
        "name": defn.name, "total_stages": len(manifest.resolved_stages),
        "total_groups": len(manifest.parallel_groups),
        "max_parallelism": max_par, "compiled_at": manifest.compiled_at,
        "contract_warnings": len(contract_warnings),
    }
    groups = [{"group": i, "stages": ", ".join(g), "parallelism": len(g)}
              for i, g in enumerate(manifest.parallel_groups)]
    resolutions = [{
        "stage": name, "template_resolved": r.template_content is not None,
        "guide_resolved": r.guide_content is not None, "cli_commands": len(r.cli_commands),
    } for name, r in manifest.resolved_stages.items()]
    warnings = [{"stage": w.stage, "upstream": w.upstream, "message": w.message}
                for w in contract_warnings]
    return {**summary, "groups": groups, "resolutions": resolutions, "contract_warnings_detail": warnings}


def _cmd_compile(args: argparse.Namespace) -> int:
    """Parse + compile, showing the execution plan."""
    if not check_workflow_path(args.path):
        return 1
    yaml_path = Path(args.path)
    try:
        yaml_bytes = yaml_path.read_bytes()
    except OSError as exc:
        print(f"Error reading {args.path}: {exc}", file=sys.stderr)
        return 1

    cache_path = _compile_cache_path(yaml_bytes, str(Path.cwd()), getattr(args, "params", []) or [], yaml_path)
    if not args.no_cache:
        cached = _try_read_cached_compile(cache_path)
        if cached is not None:
            _render_compile_output(cached, args.format)
            return 0

    payload = _build_compile_payload(args.path)
    _write_once(cache_path, (json.dumps(payload) + "\n").encode())

    _render_compile_output(payload, args.format)
    return 0


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
    try:
        defn_only = parse_workflow(path)
    except WorkflowParseError as exc:
        raise SystemExit(f"workflow: parse error: {exc}") from exc
    trigger_defaults = defn_only.trigger.params if defn_only.trigger else {}
    work_dir = str(Path.cwd() / "out")
    built_in_params = {"work_dir": work_dir}
    return {**built_in_params, **trigger_defaults, **cli_params}


def _resolve_base_dir(
    override: str | None,
    defn: WorkflowDefinition,
    params: dict[str, str],
) -> str:
    """Resolve the workspace base directory."""
    if override:
        return override
    if defn.workspace_dir:
        resolved = resolve_params(defn.workspace_dir, params) if params else defn.workspace_dir
        return str(Path(resolved).parent)
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


def _cmd_run(args: argparse.Namespace) -> int:
    """Parse + compile + execute a workflow."""
    from workflow.orchestrator import WorkflowOrchestrator
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
            manifest=manifest, workspace_dir=workspace, run_id=args.run_id,
            dry_run=dry_run, trigger_params=resolved_params or None,
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
    _emit_rows(stage_rows, fmt=args.format, headers=["stage", "status", "duration_ms", "errors"])
    if dry_run or result.status in (StageStatus.success, StageStatus.awaiting_human):
        return 0
    print(
        f"Workflow did not complete successfully: status={result.status.value}",
        file=sys.stderr,
    )
    return 2


def _cmd_lint(args: argparse.Namespace) -> int:
    """Validate workflow YAML structure without executing the workflow."""
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
        except Exception:  # noqa: BLE001 # nosec B110 - best-effort listing
            rows.append({"file": rel, "name": "?", "version": "?",
                         "description": "(parse error)", "stages": 0})

    if not rows:
        print("No workflow YAML files found in workflows/.", file=sys.stderr)
        return 1
    _emit_rows(rows, fmt=args.format, headers=["file", "name", "version", "description", "stages"])
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
    _emit_rows(rows, fmt=args.format, headers=["index", "stage", "status", "duration_ms", "errors"])
    return 0


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


def _cmd_init_workspace(args: argparse.Namespace) -> int:
    """Create workspace dir, write manifest.json + plan.json, and print workspace path."""
    from workflow.persistence import init_workspace, write_manifest
    from workflow._fileutil import atomic_write_json

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


def _generate_run_id(workflow_name: str) -> str:
    """Generate a run ID from workflow name, current date, and a short random suffix."""
    import random
    import string
    from workflow._timeutil import iso_now

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

    _emit_rows(rows, fmt=args.format, headers=["stage", "status", "needs_run", "reason"])
    return 2 if has_pending else 0
