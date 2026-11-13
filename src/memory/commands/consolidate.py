"""CLI subcommand: plan and apply zero-loss multi-store consolidation.

Archives rather than deletes. TOCTOU-safe via re-stat before any mutation.
Exit codes: 0 success, 1 validation error, 3 apply RuntimeError (TOCTOU abort).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.cli_output import emit_rows
from memory.commands._common import DRY_RUN_ARG, ArgSpec, format_arg
from memory.consolidate import (
    ConsolidationPlan,
    apply_plan,
    plan_consolidation,
)
from memory.discovery import discover_stores

_CONSOLIDATE_HEADERS = ["path", "decision"]


def _plan_to_rows(plan: ConsolidationPlan) -> list[dict[str, str]]:
    """Flatten ConsolidationPlan into decision table rows."""
    rows: list[dict[str, str]] = []
    for path in plan.identical:
        rows.append({"path": path, "decision": "identical"})
    for path in plan.to_copy:
        rows.append({"path": path, "decision": "to-copy"})
    for loser, winner in plan.conflicts:
        rows.append({"path": f"{loser} <-> {winner}", "decision": "conflict"})
    for path in plan.to_archive:
        rows.append({"path": path, "decision": "to-archive-store"})
    return rows


ARGUMENTS: list[ArgSpec] = [
    format_arg(["table", "json", "csv"], "table"),
    DRY_RUN_ARG,
    (("--on-divergence",), {"choices": ["keep-newest", "keep-both", "prompt"], "default": "keep-newest", "help": "Same filename, different content"}),
    (("--archive-dest",), {"default": None, "help": "Archive root (default: <data-home>/memory/archive)"}),
]


def run(args: argparse.Namespace) -> int:
    """Plan (and unless --dry-run, apply) zero-loss multi-store consolidation."""
    stores = discover_stores()
    if not stores:
        emit_rows([], args.format, empty_msg="No stores discovered", structured_empty=True)
        return 0

    plan = plan_consolidation(stores, on_divergence=args.on_divergence)
    rows = _plan_to_rows(plan)
    emit_rows(rows, args.format, headers=_CONSOLIDATE_HEADERS, structured_empty=True)

    if args.dry_run:
        return 0

    archive_dest: Path | None = Path(args.archive_dest) if args.archive_dest else None
    try:
        result = apply_plan(plan, archive_dest=archive_dest, dry_run=False)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3

    for warning in result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    return 0
