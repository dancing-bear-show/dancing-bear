"""Desk assistant CLI using CLIApp framework."""

import os
from typing import List, Optional

from core.assistant import BaseAssistant
from core.cli_framework import CLIApp

from . import __version__
from .pipeline import (
    ApplyProcessor,
    ApplyRequest,
    ApplyResultProducer,
    PlanProcessor,
    PlanRequest,
    ReportProducer,
    ScanProcessor,
    ScanRequest,
)


def _paths_default() -> List[str]:
    return [os.path.expanduser("~/Downloads"), os.path.expanduser("~/Desktop")]


assistant = BaseAssistant(
    "desk",
    "agentic: desk\npurpose: Scan, plan, and tidy macOS folders",
)

app = CLIApp(
    "desk-assistant",
    "Keep your macOS filesystem tidy: scan, plan, and apply rules.",
    version=__version__,
    add_common_args=False,
)


def _emit_agentic(fmt: str, compact: bool) -> int:
    try:
        # agentic.py is in outer desk package
        from desk.agentic import emit_agentic_context
        return emit_agentic_context(fmt, compact)
    except ImportError:
        print("agentic: desk\npurpose: Scan, plan, and tidy macOS folders")
        return 0


# scan command
@app.command("scan", help="Scan for large, stale, and duplicate files")
@app.argument("--paths", nargs="+", default=_paths_default(), help="Paths to scan (default: ~/Downloads ~/Desktop)")
@app.argument("--min-size", default="50MB", help="Report files >= this size (e.g. 50MB, 1G)")
@app.argument("--older-than", default=None, help="Report files older than this (e.g. 30d, 12h)")
@app.argument("--duplicates", action="store_true", help="Include duplicate detection (size+hash)")
@app.argument("--top-dirs", type=int, default=10, help="Show top N directories by size")
@app.argument("--out", default=None, help="Write report to file (yaml/json). Defaults to stdout.")
@app.argument("--debug", action="store_true", help="Enable verbose debug logging")
def cmd_scan(args) -> int:
    """Scan for large, stale, and duplicate files."""
    request = ScanRequest(
        paths=args.paths,
        min_size=args.min_size,
        older_than=args.older_than,
        include_duplicates=args.duplicates,
        top_dirs=args.top_dirs,
        debug=args.debug,
    )
    report = ScanProcessor().process(request)
    ReportProducer(args.out).produce(report)
    return 0


# plan command
@app.command("plan", help="Create a move/trash plan from config rules")
@app.argument("--config", required=True, help="Rules config in YAML (see: rules export)")
@app.argument("--out", default=None, help="Write plan to file (yaml/json). Defaults to stdout.")
@app.argument("--debug", action="store_true", help="Enable verbose debug logging")
def cmd_plan(args) -> int:
    """Create a move/trash plan from config rules."""
    request = PlanRequest(config_path=args.config)
    plan = PlanProcessor().process(request)
    ReportProducer(args.out).produce(plan)
    return 0


# apply command
@app.command("apply", help="Apply a previously generated plan")
@app.argument("--plan", required=True, help="Plan file (yaml/json)")
@app.argument("--dry-run", action="store_true", help="Print actions only")
@app.argument("--debug", action="store_true", help="Enable verbose debug logging")
def cmd_apply(args) -> int:
    """Apply a previously generated plan."""
    request = ApplyRequest(plan_path=args.plan, dry_run=args.dry_run)
    result = ApplyProcessor().process(request)
    ApplyResultProducer().produce(result)
    return 0


# rules group with export subcommand
rules_group = app.group("rules", help="Manage rule configs")


@rules_group.command("export", help="Write a starter rules.yaml")
@rules_group.argument("--out", required=True, help="Path to write YAML config")
@rules_group.argument("--debug", action="store_true", help="Enable verbose debug logging")
def cmd_rules_export(args) -> int:
    """Write a starter rules.yaml."""
    starter = _starter_rules_yaml()
    out_path = os.path.expanduser(args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(starter)
    print(f"Wrote starter rules to {out_path}")
    return 0


def _starter_rules_yaml() -> str:
    return """# desk-assistant rules configuration
# Human-editable YAML. Define match conditions and actions.
# Tips:
# - Use explicit paths and extensions.
# - Prefer targeted rules over broad patterns.

version: 1

rules:
  - name: "Move DMGs from Downloads to Archives/DMGs"
    match:
      paths: ["~/Downloads"]
      extensions: [".dmg"]
      older_than: "7d"  # optional
    action:
      move_to: "~/Downloads/Archives/DMGs"

  - name: "Move large videos to Movies"
    match:
      extensions: [".mp4", ".mov", ".mkv"]
      size_gte: "500MB"
    action:
      move_to: "~/Movies"

  - name: "Move archives to Archives"
    match:
      extensions: [".zip", ".tar", ".gz", ".tgz", ".7z"]
      size_gte: "50MB"  # optional
    action:
      move_to: "~/Archives"
"""


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the Desk Assistant CLI."""
    parser = app.build_parser()
    assistant.add_agentic_flags(parser)

    args = parser.parse_args(argv)

    agentic_result = assistant.maybe_emit_agentic(args, emit_func=_emit_agentic)
    if agentic_result is not None:
        return int(agentic_result)

    cmd_func = getattr(args, "_cmd_func", None)
    if not cmd_func:
        parser.print_help()
        return 0

    return int(cmd_func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
