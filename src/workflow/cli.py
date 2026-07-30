"""Workflow engine CLI — thin shim.

``build_parser`` and ``main`` live here; command handlers and cache logic
are in ``cli_dispatch`` and ``cli_compile``.  Everything that was previously
defined here is still importable from this module for backwards compatibility.
"""

from __future__ import annotations

import argparse
import json
import sys

# ---------------------------------------------------------------------------
# Re-exports from sibling modules (backwards-compat shim)
# ---------------------------------------------------------------------------

from workflow.cli_compile import (  # noqa: F401
    _build_compile_payload,
    _compile_cache_path,
    _fragment_bytes,
    _render_compile_output,
    _try_read_cached_compile,
    _write_once,
    _cmd_compile,
)
from workflow.cli_dispatch import (  # noqa: F401
    _build_plan_json,
    _build_resolved_params,
    _build_stage_row,
    _cmd_init_workspace,
    _cmd_lint,
    _cmd_list,
    _cmd_parse,
    _cmd_resume,
    _cmd_run,
    _cmd_status,
    _cmd_validate_fragment,
    _confirm_execution,
    _generate_run_id,
    _load_definition,
    _load_manifest,
    _parse_params,
    _resolve_base_dir,
    _stage_names_from_manifest,
    _stage_names_from_plan,
    _TERMINAL_SUCCESS,
)

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
            print(yaml.safe_dump(data, default_flow_style=False).rstrip())
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
