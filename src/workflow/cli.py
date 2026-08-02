"""Workflow engine CLI — thin shim.

The ``app`` (CLIApp) wiring and ``main`` live here; command handlers and cache
logic are in ``cli_dispatch`` and ``cli_compile``.  The ``_cmd_*``/``_build_*``
helpers re-exported below remain importable from this module for backwards
compatibility; ``build_parser()`` and ``_add_format_argument()`` were removed
as part of the CLIApp migration (no code outside this module referenced them).

Built on ``core.cli_framework.CLIApp``, matching the pattern used by the other
domain CLIs (mail, calendar, schedule, resume, phone, whatsapp, desk, wifi,
maker, apple_music, metals).

Engine-specific verb conventions: this domain uses ``run`` (not ``apply``) and
``lint`` (not ``verify``) to match workflow engine terminology.  These names
are part of the public CLI surface and are an intentional naming deviation
from the general assistant convention documented in DESIGN_CRITERIA.md — this
is purely a naming choice, not a framework deviation.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from core.cli_errors import ExitCode
from core.cli_framework import CLIApp
from core.cli_output import emit_one, emit_rows

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


def _format_kwargs(
    *,
    formats: list[str] | None = None,
    default: str = "table",
) -> dict[str, Any]:
    """Build the shared kwargs for a per-command ``--format/-f`` argument.

    Each subcommand has its own choices/default, so this is spread into
    ``@app.argument("--format", "-f", **_format_kwargs(...))`` rather than
    mutating an ``argparse.ArgumentParser`` directly (CLIApp does not expose
    one until after ``@app.command`` registers the function).
    """
    choices = formats or ["table", "json", "yaml"]
    return {
        "choices": choices,
        "default": default,
        "help": f"Output format (default: {default})",
    }


def _emit_one(data: dict, *, fmt: str = "table") -> None:
    """Emit a single dict — delegates to core.cli_output.emit_one for json/jsonl;
    falls back to key: value text for table/yaml formats."""
    if fmt in ("json", "jsonl"):
        emit_one(data, fmt=fmt)
    elif fmt == "yaml":
        try:
            import yaml
            print(yaml.safe_dump(data, default_flow_style=False).rstrip())
        except ImportError:
            emit_one(data, fmt="json")
    else:
        for k, v in data.items():
            print(f"{k}: {v}")


def _emit_rows(
    rows: list[dict],
    *,
    fmt: str = "table",
    headers: list[str] | None = None,
) -> None:
    """Emit a list of dicts — delegates to core.cli_output.emit_rows."""
    emit_rows(rows, fmt=fmt, headers=headers)


app = CLIApp("workflow", "Workflow engine CLI.", add_common_args=False)


@app.command("parse", help="Parse a workflow YAML and display its structure")
@app.argument("path", help=_PATH_HELP)
@app.argument("--format", "-f", **_format_kwargs(default="table"))
def cmd_parse(args: argparse.Namespace) -> int:
    return _cmd_parse(args)


@app.command("compile", help="Parse + compile, showing the execution plan")
@app.argument("path", help=_PATH_HELP)
@app.argument(
    "--no-compile-cache",
    action="store_true",
    dest="no_cache",
    help="Bypass the sha256-keyed compile cache and re-compile from YAML",
)
@app.argument("--format", "-f", **_format_kwargs(default="table"))
def cmd_compile(args: argparse.Namespace) -> int:
    return _cmd_compile(args)


@app.command("run", help="Parse + compile + execute a workflow")
@app.argument("path", help=_PATH_HELP)
@app.argument("--execute", action="store_true", help="Actually run the workflow (default is dry-run)")
@app.argument("--workspace", help="Override workspace base directory")
@app.argument(
    "--params", action="append", default=[], metavar="key=value",
    help="Trigger parameter overrides (repeatable)",
)
@app.argument("--run-id", help="Custom run ID")
@app.argument("--format", "-f", **_format_kwargs(default="table"))
def cmd_run(args: argparse.Namespace) -> int:
    return _cmd_run(args)


@app.command("lint", help="Validate workflow YAML structure without running it")
@app.argument("file", help="Path to workflow YAML file")
@app.argument(
    "--strict", action="store_true",
    help="Treat warnings as errors (exit non-zero if any warnings exist)",
)
@app.argument(
    "--check-commands", action="store_true", dest="check_commands",
    help="Validate ./bin/<cli> <subcommand> patterns by probing each binary",
)
@app.argument("--format", "-f", **_format_kwargs(default="yaml"))
def cmd_lint(args: argparse.Namespace) -> int:
    return _cmd_lint(args)


@app.command("list", help="List available workflow definitions")
@app.argument("--format", "-f", **_format_kwargs(default="table"))
def cmd_list(args: argparse.Namespace) -> int:
    return _cmd_list(args)


@app.command("status", help="Show status of a workflow run")
@app.argument("workspace_dir", help="Workspace directory of the run")
@app.argument("--format", "-f", **_format_kwargs(default="table"))
def cmd_status(args: argparse.Namespace) -> int:
    return _cmd_status(args)


@app.command(
    "init-workspace",
    help="Create workspace dir, write manifest.json + plan.json, print workspace path",
)
@app.argument("path", help=_PATH_HELP)
@app.argument("--run-id", dest="run_id", default="", help="Custom run ID (auto-generated if omitted)")
@app.argument("--base-dir", dest="base_dir", default="", help="Base directory for workspace")
@app.argument(
    "--params", action="append", default=[], metavar="key=value",
    help="Trigger parameter overrides (repeatable)",
)
def cmd_init_workspace(args: argparse.Namespace) -> int:
    return _cmd_init_workspace(args)


@app.command(
    "resume",
    help="Show which stages need re-running (exit 0 if all done, exit 2 if stages remain)",
)
@app.argument("workspace_dir", help="Workspace directory of the run to resume")
@app.argument("--format", "-f", **_format_kwargs(default="table"))
def cmd_resume(args: argparse.Namespace) -> int:
    return _cmd_resume(args)


@app.command(
    "validate-fragment",
    help="Validate a workflow fragment YAML (must have top-level 'fragment: true' key)",
)
@app.argument("file", help="Path to fragment YAML file")
@app.argument("--strict", action="store_true", help="Treat warnings as errors")
@app.argument("--format", "-f", **_format_kwargs(formats=["json", "yaml", "table"], default="yaml"))
def cmd_validate_fragment(args: argparse.Namespace) -> int:
    return _cmd_validate_fragment(args)


def _no_command_usage() -> int:
    """Preserve the legacy no-subcommand behavior (one-line usage to
    stderr, ExitCode.USAGE) rather than CLIApp's default (full --help),
    since this is a public CLI surface."""
    print(
        "Usage: workflow {parse,compile,run,lint,list,status,init-workspace,resume,validate-fragment} [options]",
        file=sys.stderr,
    )
    return ExitCode.USAGE


def main(argv: list[str] | None = None) -> int:
    """Workflow CLI entry point."""
    return app.run(argv, on_no_command=_no_command_usage)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
