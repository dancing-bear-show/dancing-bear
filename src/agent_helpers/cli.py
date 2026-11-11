"""Agent helpers CLI: structured, single-purpose checks for agent sessions.

Result commands print one JSON object and exit 0; read the verdict from the
body (``status``/``overall``/``passed``/``valid``). Exit 2 means a usage
error, exit 1 an unreadable input for ``summarize-findings``.
"""

from __future__ import annotations

import sys
from dataclasses import asdict
from functools import lru_cache

from core.assistant import BaseAssistant
from core.cli_errors import ExitCode
from core.cli_framework import CLIApp
from core.cli_output import emit_one, emit_rows

from . import findings as _findings
from . import git_ops as _git_ops
from . import patch as _patch
from . import validate as _validate
from .checks import TOOL_CHOICES, run_check
from .meta import META
from .repo import resolve_repo_root

assistant = BaseAssistant(META.app_id, META.agentic_fallback)

app = CLIApp(
    "agent-helpers",
    "Structured checks for agent sessions (JSON in the body, exit 0)",
    add_common_args=False,
)


@lru_cache(maxsize=1)
def _lazy_agentic():
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


def _split_csv(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _usage_error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return ExitCode.USAGE


@app.command("validate-imports", help="Import a module and verify named symbols exist")
@app.argument("--import-order", help="Comma-separated modules to import in sequence (circular check)")
@app.argument("--symbols", help="Comma-separated symbols to check within --module")
@app.argument("--module", help="Module path to import")
def cmd_validate_imports(args) -> int:
    if args.import_order:
        emit_one(_validate.validate_import_order(_split_csv(args.import_order)))
        return ExitCode.SUCCESS
    if not args.module:
        return _usage_error("one of --module or --import-order is required")
    symbols = _split_csv(args.symbols)
    if not symbols:
        return _usage_error("--symbols is required with --module")
    emit_one(_validate.validate_symbols(args.module, symbols))
    return ExitCode.SUCCESS


@app.command("validate-ast", help="Check __all__ completeness or function nesting depth")
@app.argument("--complexity", action="store_true", help="Report max nesting depth of --function")
@app.argument("--function", help="Top-level function name")
@app.argument("--all-exported", action="store_true", help="Verify every __all__ name is defined")
@app.argument("--file", required=True, help="Python source file")
def cmd_validate_ast(args) -> int:
    if args.complexity and not args.function:
        return _usage_error("--complexity requires --function")
    if not args.all_exported and not args.function:
        return _usage_error("one of --all-exported or --function is required")
    emit_one(_validate.validate_ast(args.file, all_exported=args.all_exported, function=args.function))
    return ExitCode.SUCCESS


@app.command("validate-json", help="Parse a JSON file; check top-level keys and a list length")
@app.argument("--count", help="Top-level key whose list length to report")
@app.argument("--keys", help="Comma-separated top-level keys that must exist")
@app.argument("--file", required=True, help="JSON file")
def cmd_validate_json(args) -> int:
    emit_one(_validate.validate_json(args.file, args.keys, args.count))
    return ExitCode.SUCCESS


@app.command("summarize-findings", help="Count a findings JSON array grouped by a field")
@app.argument("--format", choices=("json", "table", "csv"), default="json", help="Output format")
@app.argument("--group-by", default="severity", help="Field to group by (default: severity)")
@app.argument("--input", required=True, help="JSON file holding an array of objects")
def cmd_summarize_findings(args) -> int:
    try:
        items = _findings.load_findings(args.input)
    except _findings.FindingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return ExitCode.ERROR
    counts = _findings.count_by(items, args.group_by)
    if args.format == "json":
        emit_one({"total": len(items), f"by_{args.group_by}": counts})
        return ExitCode.SUCCESS
    rows = [{"group": key, "count": n} for key, n in counts.items()]
    emit_rows(rows, args.format, headers=["group", "count"])
    return ExitCode.SUCCESS


@app.command("analyze-patch", help="Extract imports, added functions, __all__, or a dispatch map from a diff")
@app.argument("--extract", required=True, choices=_patch.EXTRACT_CHOICES, help="What to extract")
@app.argument("--patch", required=True, help="Unified diff file")
def cmd_analyze_patch(args) -> int:
    emit_one(_patch.analyze_patch(args.patch, args.extract))
    return ExitCode.SUCCESS


@app.command("git-ops", help="Run git checkout/worktree operations from the repo root")
@app.argument("--then-checkout", help="Branch to check out after worktree-remove")
@app.argument("--path", help="Worktree path (worktree-add/remove)")
@app.argument("--fetch", action="store_true", help="Fetch origin before checkout")
@app.argument("--branch", help="Branch (checkout, worktree-add)")
@app.argument("--op", required=True, choices=_git_ops.OP_CHOICES, help="Operation")
def cmd_git_ops(args) -> int:
    repo_root, error = resolve_repo_root()
    if error:
        emit_one({"op": args.op, "branch": args.branch, "path": args.path, "status": "error", "output": error})
        return ExitCode.SUCCESS
    if args.op == "checkout":
        result = _git_ops.op_checkout(repo_root, args.branch, args.fetch)
    elif args.op == "worktree-add":
        result = _git_ops.op_worktree_add(repo_root, args.path, args.branch)
    elif args.op == "worktree-remove":
        result = _git_ops.op_worktree_remove(repo_root, args.path, args.then_checkout)
    else:
        result = _git_ops.op_worktree_list(repo_root)
    emit_one(result)
    return ExitCode.SUCCESS


@app.command("run-tests", help="Run make test/lint/typecheck-changed from the repo root")
@app.argument("--paths", nargs="*", default=[], help="test only: dirs/files to run via unittest discover")
@app.argument("--tool", choices=TOOL_CHOICES, default="test", help="Gate to run (default: test)")
def cmd_run_tests(args) -> int:
    repo_root, error = resolve_repo_root()
    if error:
        emit_one({"tool": args.tool, "paths": args.paths, "exit_code": 1, "passed": False, "error": error})
        return ExitCode.SUCCESS
    if args.paths and args.tool != "test":
        return _usage_error("--paths applies only to --tool test")
    emit_one(asdict(run_check(args.tool, repo_root, list(args.paths))))
    return ExitCode.SUCCESS


def main(argv: list[str] | None = None) -> int:
    """Entry point for the agent helpers CLI."""
    return app.run_with_assistant(
        assistant,
        emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact),
        argv=argv,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
