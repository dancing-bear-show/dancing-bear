import argparse
import os
import sys
from typing import List, Optional

from personal_core.assistant import BaseAssistant

from . import __version__
from .pipeline import (
    ApplyProcessor,
    ApplyRequest,
    ApplyRequestConsumer,
    ApplyResultProducer,
    PlanProcessor,
    PlanRequest,
    PlanRequestConsumer,
    ReportProducer,
    ScanProcessor,
    ScanRequest,
    ScanRequestConsumer,
)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--debug", action="store_true", help="Enable verbose debug logging"
    )


def _paths_default() -> List[str]:
    return [os.path.expanduser("~/Downloads"), os.path.expanduser("~/Desktop")]


assistant = BaseAssistant(
    "desk_assistant",
    "agentic: desk_assistant\npurpose: Scan, plan, and tidy macOS folders",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="desk-assistant",
        description="Keep your macOS filesystem tidy: scan, plan, and apply rules.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    assistant.add_agentic_flags(parser)

    subparsers = parser.add_subparsers(dest="command", required=False)

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan for large, stale, and duplicate files")
    p_scan.add_argument(
        "--paths",
        nargs="+",
        default=_paths_default(),
        help="Paths to scan (default: ~/Downloads ~/Desktop)",
    )
    p_scan.add_argument(
        "--min-size",
        default="50MB",
        help="Report files >= this size (e.g. 50MB, 1G)",
    )
    p_scan.add_argument(
        "--older-than",
        default=None,
        help="Report files older than this (e.g. 30d, 12h)",
    )
    p_scan.add_argument(
        "--duplicates",
        action="store_true",
        help="Include duplicate detection (size+hash)",
    )
    p_scan.add_argument(
        "--top-dirs",
        type=int,
        default=10,
        help="Show top N directories by size",
    )
    p_scan.add_argument(
        "--out",
        default=None,
        help="Write report to file (yaml/json). Defaults to stdout.",
    )
    _add_common_args(p_scan)

    # plan
    p_plan = subparsers.add_parser("plan", help="Create a move/trash plan from config rules")
    p_plan.add_argument(
        "--config", required=True, help="Rules config in YAML (see: rules export)"
    )
    p_plan.add_argument(
        "--out",
        required=False,
        default=None,
        help="Write plan to file (yaml/json). Defaults to stdout.",
    )
    _add_common_args(p_plan)

    # apply
    p_apply = subparsers.add_parser("apply", help="Apply a previously generated plan")
    p_apply.add_argument("--plan", required=True, help="Plan file (yaml/json)")
    p_apply.add_argument("--dry-run", action="store_true", help="Print actions only")
    _add_common_args(p_apply)

    # rules export
    p_rules = subparsers.add_parser("rules", help="Manage rule configs")
    sp_rules = p_rules.add_subparsers(dest="rules_cmd", required=True)

    p_rules_export = sp_rules.add_parser("export", help="Write a starter rules.yaml")
    p_rules_export.add_argument("--out", required=True, help="Path to write YAML config")
    _add_common_args(p_rules_export)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    def _emit_agentic(fmt: str, compact: bool) -> int:
        from .agentic import emit_agentic_context

        return emit_agentic_context(fmt, compact)

    agentic_result = assistant.maybe_emit_agentic(args, emit_func=_emit_agentic)
    if agentic_result is not None:
        return

    if args.command == "scan":
        request = ScanRequest(
            paths=args.paths,
            min_size=args.min_size,
            older_than=args.older_than,
            include_duplicates=args.duplicates,
            top_dirs=args.top_dirs,
            debug=args.debug,
        )
        report = ScanProcessor().process(ScanRequestConsumer(request).consume())
        ReportProducer(args.out).produce(report)
        return

    if args.command == "plan":
        request = PlanRequest(config_path=args.config)
        plan = PlanProcessor().process(PlanRequestConsumer(request).consume())
        ReportProducer(args.out).produce(plan)
        return

    if args.command == "apply":
        request = ApplyRequest(plan_path=args.plan, dry_run=args.dry_run)
        result = ApplyProcessor().process(ApplyRequestConsumer(request).consume())
        ApplyResultProducer().produce(result)
        return

    if args.command == "rules" and args.rules_cmd == "export":
        starter = _starter_rules_yaml()
        out_path = os.path.expanduser(args.out)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(starter)
        print(f"Wrote starter rules to {out_path}")
        return

    parser.print_help()


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
