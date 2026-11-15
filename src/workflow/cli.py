"""Workflow engine CLI — thin shim.

The ``app`` (CLIApp) wiring and ``main`` live here; command handlers and cache
logic are in ``cli_dispatch`` and ``cli_compile``.  Only the ``_cmd_*`` handlers
this module actually dispatches to are imported — import anything else from the
module that defines it.

Built on ``core.cli_framework.CLIApp``, matching the pattern used by the other
domain CLIs (mail, calendar, schedule, resume, phone, whatsapp, desk, wifi,
maker, apple_music).

Engine-specific verb conventions: this domain uses ``run`` (not ``apply``) and
``lint`` (not ``verify``) to match workflow engine terminology.  These names
are part of the public CLI surface and are an intentional naming deviation
from the general assistant convention documented in DESIGN_CRITERIA.md — this
is purely a naming choice, not a framework deviation.
"""

from __future__ import annotations

import argparse
import sys
from functools import lru_cache
from typing import Any

from core.assistant import BaseAssistant
from core.cli_errors import ExitCode
from core.cli_framework import CLIApp
from core.cli_output import emit_one, emit_rows
from workflow.meta import META

from workflow.cli_compile import _cmd_compile
from workflow.cli_dispatch import (
    _cmd_check_params,
    _cmd_init_workspace,
    _cmd_lint,
    _cmd_list,
    _cmd_parse,
    _cmd_resume,
    _cmd_run,
    _cmd_status,
    _cmd_validate_fragment,
)
from workflow.cli_dispatch_review import (
    _cmd_aggregate_fix_results,
    _cmd_check_fix_index,
    _cmd_check_paths,
    _cmd_check_thread_ids,
    _cmd_check_unlisted,
    _cmd_count_blocking,
    _cmd_count_sweep,
    _cmd_merge_fix_results,
    _cmd_parse_overview,
    _cmd_review_rounds,
    _cmd_select_concerns,
    _cmd_snapshot_dirty,
    _cmd_sweep_record_check,
    _cmd_sweep_record_waive,
    _cmd_sweep_record_write,
    _cmd_thread_fingerprints,
)
from workflow.cli_fleet import (
    FILTER_ALL,
    FILTER_CHOICES,
    MARK_CHOICES,
    _cmd_fleet_mark,
    _cmd_fleet_report,
    _cmd_fleet_reset,
    _cmd_fleet_run,
    _cmd_fleet_status,
)
from workflow.cli_lifecycle import _cmd_seed_pr_lifecycle, _cmd_set_state
from workflow.models import StageStatus
from workflow.set_state import DEFAULT_PR_FRAGMENT

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

assistant = BaseAssistant(META.app_id, META.agentic_fallback)


@lru_cache(maxsize=1)
def _lazy_agentic():
    from .agentic import emit_agentic_context
    return emit_agentic_context


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
@app.argument(
    "--params", action="append", default=[], metavar="key=value",
    help="Trigger parameter overrides (repeatable) — affects when/will_run",
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


@app.command(
    "parse-overview",
    help="Parse Copilot ccr-overview-v2 review bodies into structured findings",
)
@app.argument("threads_json", help="Path to threads.json from the pr-review-threads fragment")
@app.argument("--pr", dest="pr_number", default="", help="PR number, recorded in the output")
@app.argument("--out", dest="out_path", default="", help="Write JSON here (default: stdout)")
def cmd_parse_overview(args: argparse.Namespace) -> int:
    return _cmd_parse_overview(args)


@app.command(
    "check-paths",
    help="Exit non-zero if any path escapes the repo or is protected (.git, .github, .claude, .envrc)",
)
@app.argument("paths", nargs="+", help="Repo-relative paths to check")
def cmd_check_paths(args: argparse.Namespace) -> int:
    return _cmd_check_paths(args)


@app.command(
    "select-concerns",
    help="Select concern guides for given file paths and optional task type",
)
@app.argument("--paths", nargs="*", default=[], metavar="PATH", help="File paths to evaluate")
@app.argument("--paths-file", dest="paths_file", default="", help="Newline-delimited file of paths (- for stdin)")
@app.argument("--task-type", dest="task_type", default="", help="Task type: a task_type_rules key in concerns/selection.yaml")
@app.argument("--format", "-f", choices=["text", "json"], default="text", help="Output format (default: text)")
def cmd_select_concerns(args: argparse.Namespace) -> int:
    return _cmd_select_concerns(args)


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
    "set-state",
    help="Write a stage-result marker for a stage finished outside the orchestrator",
)
@app.argument("workspace_dir", help="Workspace directory of the run")
@app.argument("stage_name", help="Stage name to mark; must be in the run's plan")
@app.argument(
    "--status", default="success", choices=[s.value for s in StageStatus],
    help="Status to record (default: success)",
)
@app.argument("--data", default="", metavar="JSON", help="JSON object stored as the result's data")
@app.argument(
    "--stage-index", dest="stage_index", type=int, default=None, metavar="N",
    help="Marker index (default: max existing + 1, so it outranks older markers)",
)
@app.argument("--note", default=None, help="Free text stored in metadata.note")
@app.argument("--format", "-f", **_format_kwargs(formats=["json", "yaml", "table"], default="table"))
def cmd_set_state(args: argparse.Namespace) -> int:
    return _cmd_set_state(args)


@app.command(
    "seed-pr-lifecycle",
    help="Mark every stage of an included PR fragment success for one PR",
)
@app.argument("workspace_dir", help="Workspace directory of the run")
@app.argument("prefix", help="Include prefix of the fragment's stages (e.g. 'pr' for pr-open-pr)")
@app.argument("--pr", dest="pr_number", type=int, required=True, help="PR number")
@app.argument("--url", default=None, help="PR URL, stored on the open-pr stage")
@app.argument("--note", default=None, help="Free text stored in metadata.note on every stage")
@app.argument(
    "--fragment", default="", metavar="PATH",
    help=f"Fragment whose stages to seed (default: {DEFAULT_PR_FRAGMENT})",
)
@app.argument("--format", "-f", **_format_kwargs(formats=["json", "csv", "table"], default="table"))
def cmd_seed_pr_lifecycle(args: argparse.Namespace) -> int:
    return _cmd_seed_pr_lifecycle(args)


@app.command(
    "validate-fragment",
    help="Validate a workflow fragment YAML (must have top-level 'fragment: true' key)",
)
@app.argument("file", help="Path to fragment YAML file")
@app.argument("--strict", action="store_true", help="Treat warnings as errors")
@app.argument("--format", "-f", **_format_kwargs(formats=["json", "yaml", "table"], default="yaml"))
def cmd_validate_fragment(args: argparse.Namespace) -> int:
    return _cmd_validate_fragment(args)


@app.command(
    "check-params",
    help="Validate params read from a workspace JSON file (exit 0 pass, 1 fail)",
)
@app.argument("file", help="Path to manifest.json (or another engine/stage JSON file)")
@app.argument(
    "--check", action="append", default=[], required=True, metavar="name=regex",
    help="Param name and full-match regex it must satisfy (repeatable)",
)
@app.argument(
    "--top-level", action="store_true",
    help="Read params from the document root instead of its 'trigger_params' key",
)
@app.argument(
    "--print", dest="print_param", default=None, metavar="name",
    help="Also write this param's value to stdout, only if every --check passed "
         "(the name must be one of them)",
)
def cmd_check_params(args: argparse.Namespace) -> int:
    return _cmd_check_params(args)


@app.command(
    "check-fix-index",
    help="Fail unless every fix-index.json id is unique and every file_id unique and filename-safe",
)
@app.argument("file", help="Path to fix-index.json")
def cmd_check_fix_index(args: argparse.Namespace) -> int:
    return _cmd_check_fix_index(args)


@app.command(
    "thread-fingerprints",
    help="Print each threads.json entry's database_id and body fingerprint as JSON",
)
@app.argument("file", help="Path to threads.json")
def cmd_thread_fingerprints(args: argparse.Namespace) -> int:
    return _cmd_thread_fingerprints(args)


@app.command(
    "check-thread-ids",
    help="Id-coherence gate: triage.json thread ids vs threads.json (exit 0 pass, 1 halt)",
)
@app.argument("threads", help="Path to threads.json (the fetch)")
@app.argument("triage", help="Path to triage.json")
@app.argument(
    "--repair", action="store_true",
    help="Rewrite triage.json with the fetch's coordinates when only coordinates differ",
)
def cmd_check_thread_ids(args: argparse.Namespace) -> int:
    return _cmd_check_thread_ids(args)


@app.command(
    "aggregate-fix-results",
    help="Merge fixes/<file_id>.json into fix-results.json, verifying each result's identity",
)
@app.argument("index", help="Path to fix-index.json")
@app.argument("fixes_dir", help="Directory holding <file_id>.json result files")
@app.argument("out", help="Path to write fix-results.json")
def cmd_aggregate_fix_results(args: argparse.Namespace) -> int:
    return _cmd_aggregate_fix_results(args)


@app.command(
    "snapshot-dirty",
    help="Record the checkout's dirty/untracked paths and content hashes as JSON",
)
@app.argument("out", help="Path to write the snapshot JSON")
def cmd_snapshot_dirty(args: argparse.Namespace) -> int:
    return _cmd_snapshot_dirty(args)


@app.command(
    "check-unlisted",
    help="Exit 1 if a path changed since the snapshot is missing from fix-results files_changed",
)
@app.argument("baseline", help="Snapshot JSON from snapshot-dirty")
@app.argument("fix_results", help="Path to fix-results.json")
def cmd_check_unlisted(args: argparse.Namespace) -> int:
    return _cmd_check_unlisted(args)


@app.command(
    "review-rounds",
    help="Fetch PR bot-review-round data and write per-PR JSON + summary",
)
@app.argument(
    "--prs",
    default=None,
    help="Comma-separated PR numbers; never thread-filtered unless --min-threads is given",
)
@app.argument(
    "--recent",
    type=int,
    default=None,
    metavar="N",
    help="The N most recent PRs by number, any state (1-200)",
)
@app.argument(
    "--out-dir",
    dest="out_dir",
    required=True,
    help="Directory to write pr<N>.json and summary.json",
)
@app.argument(
    "--min-threads",
    dest="min_threads",
    type=int,
    default=None,
    metavar="N",
    help="Drop PRs with fewer than N threads from summary.json (default: 15 with --recent, 0 with --prs)",
)
def cmd_review_rounds(args: argparse.Namespace) -> int:
    return _cmd_review_rounds(args)


@app.command(
    "count-sweep",
    help="Count lines matching a regex under repo-relative paths, no shell; prints {hits, files}",
)
@app.argument("--pattern", required=True, help="Python regex; never passed to a shell")
@app.argument(
    "--path",
    dest="paths",
    action="append",
    default=[],
    required=True,
    help="Repo-relative file or directory (repeatable); check-paths rules plus [A-Za-z0-9_][A-Za-z0-9._/-]*",
)
@app.argument("--root", default=None, help="Repo root or a dir inside it; paths are relative to it (default: repo root)")
def cmd_count_sweep(args: argparse.Namespace) -> int:
    return _cmd_count_sweep(args)


@app.command(
    "count-blocking",
    help="Derive the blocking-finding count from sweep-findings.json; exit 2 on malformed input",
)
@app.argument("findings", help="Path to sweep-findings.json")
def cmd_count_blocking(args: argparse.Namespace) -> int:
    return _cmd_count_blocking(args)


@app.command(
    "merge-fix-results",
    help="Merge fix-results.json and refix-results.json into a combined file",
)
@app.argument("fix_results", help="Path to fix-results.json (primary fixer output)")
@app.argument("refix_results", help="Path to refix-results.json (regression-sweep fixer output)")
@app.argument("out", help="Path to write the merged JSON output")
def cmd_merge_fix_results(args: argparse.Namespace) -> int:
    return _cmd_merge_fix_results(args)


sweep_record_group = app.group(
    "sweep-record", help="Per-commit evidence that the concern swarm ran (or was waived)",
)
_HEAD_HELP = "Full 40-hex commit id"


@sweep_record_group.command("write", help="Record a swarm run on HEAD (exit 0 written, 2 refused)")
@app.argument("--head", required=True, help=_HEAD_HELP + "; must equal HEAD")
@app.argument("--workspace", required=True, help="Swarm workspace dir holding outputs/")
def cmd_sweep_record_write(args: argparse.Namespace) -> int:
    return _cmd_sweep_record_write(args)


@sweep_record_group.command("waive", help="Record a waived sweep (exit 0 written, 2 refused)")
@app.argument("--head", required=True, help=_HEAD_HELP)
@app.argument("--reason", required=True, help="Why the sweep was skipped (non-empty)")
def cmd_sweep_record_waive(args: argparse.Namespace) -> int:
    return _cmd_sweep_record_waive(args)


@sweep_record_group.command("check", help="Print record mode (exit 0 found, 1 none, 2 bad sha)")
@app.argument("--head", required=True, help=_HEAD_HELP)
def cmd_sweep_record_check(args: argparse.Namespace) -> int:
    return _cmd_sweep_record_check(args)


def _batch_size(raw: str) -> int:
    """argparse type: integer >= 0 (0 = every pending/failed item)."""
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer, got {raw!r}") from exc
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {value}")
    return value


fleet_group = app.group(
    "fleet", help="Track one workflow across many items in resumable batches (ledger-backed)",
)
_FLEET_FORMATS = ["table", "json", "csv"]


@fleet_group.command("run", help="Add items to the ledger; init a workspace per item in the next batch")
@app.argument("path", help=_PATH_HELP)
@app.argument("--fan-over", required=True, metavar="SOURCE", help="Items: items:a,b,c or file:<path> (one per line)")
@app.argument(
    "--fan-param", action="append", default=[], metavar="key=...{item}...",
    help="Per-item param; {item} is substituted (repeatable)",
)
@app.argument("--param", action="append", default=[], metavar="key=value", help="Param for every item (repeatable)")
@app.argument("--batch-size", type=_batch_size, default=10, metavar="N", help="Items per batch; 0 = all (default: 10)")
@app.argument("--force-items", default="", metavar="a,b", help="Reset these items to pending first")
@app.argument("--base-dir", default="", help="Base directory for item workspaces")
@app.argument("--dry-run", action="store_true", help="Show the batch; write nothing")
@app.argument("--format", "-f", **_format_kwargs(formats=_FLEET_FORMATS, default="table"))
def cmd_fleet_run(args: argparse.Namespace) -> int:
    return _cmd_fleet_run(args)


@fleet_group.command("status", help="Show fleet progress and per-item status")
@app.argument("path", help=_PATH_HELP)
@app.argument("--filter", default=FILTER_ALL, choices=FILTER_CHOICES, help="Only items with this status")
@app.argument("--format", "-f", **_format_kwargs(formats=_FLEET_FORMATS, default="table"))
def cmd_fleet_status(args: argparse.Namespace) -> int:
    return _cmd_fleet_status(args)


@fleet_group.command("reset", help="Return items to pending (next run starts them fresh)")
@app.argument("path", help=_PATH_HELP)
@app.argument("--filter", default=None, choices=FILTER_CHOICES, help="Reset every item with this status")
@app.argument("--items", default="", metavar="a,b", help="Reset these items")
def cmd_fleet_reset(args: argparse.Namespace) -> int:
    return _cmd_fleet_reset(args)


@fleet_group.command("report", help="Per-item stage progress from each workspace, plus status totals")
@app.argument("path", help=_PATH_HELP)
@app.argument("--filter", default=FILTER_ALL, choices=FILTER_CHOICES, help="Only items with this status")
@app.argument("--format", "-f", **_format_kwargs(formats=_FLEET_FORMATS, default="table"))
def cmd_fleet_report(args: argparse.Namespace) -> int:
    return _cmd_fleet_report(args)


@fleet_group.command("mark", help="Record an item's outcome (done refused while stages remain)")
@app.argument("path", help=_PATH_HELP)
@app.argument("item", help="Item name")
@app.argument("status", choices=MARK_CHOICES, help="New status")
@app.argument("--workspace", default=None, help="Item's run workspace (default: the ledger's)")
@app.argument("--error", default=None, metavar="MSG", help="Error message, for failed")
@app.argument("--force", action="store_true", help="Mark done even if the workspace has stages left")
def cmd_fleet_mark(args: argparse.Namespace) -> int:
    return _cmd_fleet_mark(args)


def _no_command_usage() -> int:
    """Preserve the legacy no-subcommand behavior (one-line usage to
    stderr, ExitCode.USAGE) rather than CLIApp's default (full --help),
    since this is a public CLI surface.  The name list is derived from the
    registered commands so a new subcommand cannot be left out."""
    names = [name for name, cmd in app._commands.items() if cmd.parent is None]
    names.extend(app._groups)
    print(f"Usage: workflow {{{','.join(names)}}} [options]", file=sys.stderr)
    return ExitCode.USAGE


def main(argv: list[str] | None = None) -> int:
    """Workflow CLI entry point."""
    return app.run_with_assistant(
        assistant,
        emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact),
        argv=argv,
        on_no_command=_no_command_usage,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
