"""Handlers for ``workflow fleet``: run / status / reset / report / mark.

Ledger logic lives in :mod:`workflow.fleet`; this module wires it to argparse
and to the run-workspace helpers shared with ``init-workspace`` and ``resume``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from core.cli_errors import CLIError, ExitCode
from core.cli_output import emit_rows
from core.date_utils import iso_now
from workflow.cli_dispatch import (
    _build_stage_row,
    _load_definition,
    _parse_params,
    create_run_workspace,
)
from workflow.cli_helpers import check_workflow_path
from workflow.cli_lifecycle import _planned_stages
from workflow.fleet import (
    FleetError,
    ItemRecord,
    ItemStatus,
    MARK_STATUSES,
    Ledger,
    enumerate_items,
    ledger_path,
    load_ledger,
    mark_fields,
    merge_items,
    require_ledger,
    reset_items,
    save_ledger,
    select_batch,
    substitute_item,
    update_item,
    workflow_slug,
)
from workflow.param_rules import UnsafePathError
from workflow.persistence import list_stage_results

FILTER_ALL = "all"
FILTER_CHOICES = [FILTER_ALL, *(s.value for s in ItemStatus)]
MARK_CHOICES = [s.value for s in MARK_STATUSES]

_STATUS_HEADERS = ["item", "status", "started", "completed", "workspace", "error"]
_REPORT_HEADERS = ["item", "status", "stages_done", "stages_total", "completed", "workspace", "error"]
_RUN_HEADERS = ["item", "status", "workspace", "params"]


def _slug_for(path: str) -> str | None:
    """Ledger slug for a workflow file, or None (message printed) if it is missing."""
    if not check_workflow_path(path):
        return None
    return workflow_slug(_load_definition(path).name)


def _short_ts(ts: str | None) -> str:
    return "-" if not ts else ts[:16].replace("T", " ")


def _matches(rec: ItemRecord, status_filter: str) -> bool:
    return status_filter == FILTER_ALL or rec.status.value == status_filter


def _progress_bar(done: int, total: int, width: int = 20) -> str:
    filled = int(width * done / total) if total else 0
    pct = done / total * 100 if total else 0.0
    return f"[{'#' * filled}{'.' * (width - filled)}] {done}/{total} ({pct:.1f}%)"


@dataclass(frozen=True)
class StageProgress:
    """How far one item's run workspace has got, judged as ``resume`` does."""

    done: int
    total: int

    @property
    def complete(self) -> bool:
        return self.done == self.total


def stage_progress(workspace: str | None) -> StageProgress | None:
    """Stage progress of a run workspace, or None if it has no plan to judge by."""
    if not workspace or not Path(workspace).is_dir():
        return None
    ws = Path(workspace)
    names = _planned_stages(ws)
    if not names:
        return None
    latest = {sr.stage_name: sr.status for sr in list_stage_results(ws)}
    rows = [_build_stage_row(name, latest.get(name)) for name in names]
    return StageProgress(sum(1 for r in rows if r["needs_run"] == "no"), len(rows))


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def _item_params(args: argparse.Namespace, item: str) -> dict[str, str]:
    params, err = _parse_params([*substitute_item(args.fan_param, item), *args.param])
    if err:
        raise FleetError(err)
    return params


def _reusable_workspace(rec: ItemRecord) -> Path | None:
    """A failed item's earlier workspace, kept so the retry resumes instead of restarting."""
    if rec.status != ItemStatus.failed or not rec.workspace:
        return None
    ws = Path(rec.workspace)
    return ws if (ws / "manifest.json").is_file() else None


def _start_item(args: argparse.Namespace, slug: str, item: str, rec: ItemRecord) -> dict[str, object]:
    """Create (or reuse) the item's workspace and mark it running; mark it failed on error."""
    params = _item_params(args, item)
    shown = " ".join(f"{k}={v}" for k, v in params.items())
    try:
        workspace = _reusable_workspace(rec) or create_run_workspace(
            args.path, params, base_dir=args.base_dir or None,
        )
    except (CLIError, UnsafePathError, OSError) as exc:
        update_item(slug, item, status=ItemStatus.failed.value, error=str(exc), completed_at=iso_now())
        return {"item": item, "status": "failed", "workspace": f"- ({exc})", "params": shown}
    update_item(
        slug, item, status=ItemStatus.running.value, workspace=str(workspace),
        started_at=iso_now(), completed_at=None, error=None,
    )
    return {"item": item, "status": "running", "workspace": str(workspace), "params": shown}


def _cmd_fleet_run(args: argparse.Namespace) -> int:
    """Merge items into the ledger and start the next batch (one workspace each)."""
    slug = _slug_for(args.path)
    if slug is None:
        return ExitCode.ERROR
    try:
        items = enumerate_items(args.fan_over)
        for item in items:  # reject a malformed --param/--fan-param before any write
            _item_params(args, item)
        ledger = load_ledger(slug) or Ledger(
            workflow=slug, workflow_path=args.path, fan_over=args.fan_over,
            created_at=iso_now(), last_updated=iso_now(),
        )
    except FleetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return ExitCode.ERROR
    added = merge_items(ledger, items)
    forced = reset_items(ledger, (x.strip() for x in (args.force_items or "").split(",")))
    batch = select_batch(ledger, args.batch_size)

    if args.dry_run:
        rows: list[dict[str, object]] = [
            {"item": i, "status": ledger.items[i].status.value, "workspace": "-",
             "params": " ".join(f"{k}={v}" for k, v in _item_params(args, i).items())}
            for i in batch
        ]
        print(f"dry-run: {added} new, {len(forced)} reset, {len(batch)} would start", file=sys.stderr)
        emit_rows(rows, fmt=args.format, headers=_RUN_HEADERS, empty_msg="Nothing to start.")
        return ExitCode.SUCCESS

    save_ledger(ledger)
    rows = [_start_item(args, slug, item, ledger.items[item]) for item in batch]
    emit_rows(rows, fmt=args.format, headers=_RUN_HEADERS, empty_msg="Nothing to start.")
    if rows:
        print(
            f"Run each workspace with the /workflow skill, then: ./bin/workflow fleet mark "
            f"{args.path} <item> done|failed",
            file=sys.stderr,
        )
    return ExitCode.ERROR if any(r["status"] == "failed" for r in rows) else ExitCode.SUCCESS


# ---------------------------------------------------------------------------
# status / reset / report / mark
# ---------------------------------------------------------------------------


def _load_for(args: argparse.Namespace) -> tuple[str, Ledger] | None:
    """Slug and ledger for args.path; prints the error and returns None if absent."""
    slug = _slug_for(args.path)
    if slug is None:
        return None
    try:
        return slug, require_ledger(slug)
    except FleetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return None


def _cmd_fleet_status(args: argparse.Namespace) -> int:
    """Progress line plus one row per item (optionally filtered by status)."""
    loaded = _load_for(args)
    if loaded is None:
        return ExitCode.ERROR
    slug, ledger = loaded
    if args.format == "table":
        print(f"workflow:  {slug}")
        print(f"ledger:    {ledger_path(slug)}")
        print(f"progress:  {_progress_bar(ledger.counts()[ItemStatus.done], len(ledger.items))}")
    rows: list[dict[str, object]] = [
        {
            "item": name, "status": rec.status.value, "started": _short_ts(rec.started_at),
            "completed": _short_ts(rec.completed_at), "workspace": rec.workspace or "-",
            "error": rec.error or "-",
        }
        for name, rec in sorted(ledger.items.items())
        if _matches(rec, args.filter)
    ]
    emit_rows(rows, fmt=args.format, headers=_STATUS_HEADERS, empty_msg=f"No items with status={args.filter}.")
    return ExitCode.SUCCESS


def _cmd_fleet_reset(args: argparse.Namespace) -> int:
    """Return items selected by --filter and/or --items to pending."""
    if not args.filter and not args.items:
        print("Error: pass --filter <status> and/or --items a,b", file=sys.stderr)
        return ExitCode.USAGE
    loaded = _load_for(args)
    if loaded is None:
        return ExitCode.ERROR
    _, ledger = loaded
    targets = [n for n, r in sorted(ledger.items.items()) if args.filter and _matches(r, args.filter)]
    named = [x.strip() for x in (args.items or "").split(",") if x.strip()]
    unknown = [n for n in named if n not in ledger.items]
    if unknown:
        print(f"Error: not in the fleet ledger: {', '.join(unknown)}", file=sys.stderr)
        return ExitCode.ERROR
    reset = reset_items(ledger, [*targets, *named])
    save_ledger(ledger)
    print(f"Reset {len(reset)} item(s) to pending.")
    return ExitCode.SUCCESS


def _report_row(name: str, rec: ItemRecord) -> dict[str, object]:
    progress = stage_progress(rec.workspace)
    return {
        "item": name, "status": rec.status.value,
        "stages_done": progress.done if progress else "-",
        "stages_total": progress.total if progress else "-",
        "completed": _short_ts(rec.completed_at), "workspace": rec.workspace or "-",
        "error": rec.error or "-",
    }


def _cmd_fleet_report(args: argparse.Namespace) -> int:
    """Per-item stage progress read from each item's workspace, plus status totals."""
    loaded = _load_for(args)
    if loaded is None:
        return ExitCode.ERROR
    _, ledger = loaded
    rows = [_report_row(n, r) for n, r in sorted(ledger.items.items()) if _matches(r, args.filter)]
    emit_rows(rows, fmt=args.format, headers=_REPORT_HEADERS, empty_msg=f"No items with status={args.filter}.")
    if args.format == "table":
        counts = ledger.counts()
        print("TOTAL  " + " ".join(f"{s.value}={counts[s]}" for s in ItemStatus))
    return ExitCode.SUCCESS


def _cmd_fleet_mark(args: argparse.Namespace) -> int:
    """Record an item's outcome; ``done`` is refused while its workspace has stages left."""
    loaded = _load_for(args)
    if loaded is None:
        return ExitCode.ERROR
    slug, ledger = loaded
    status = ItemStatus(args.status)
    record = ledger.items.get(args.item)
    if record is None:
        print(f"Error: item {args.item!r} is not in the {slug!r} fleet ledger", file=sys.stderr)
        return ExitCode.ERROR
    if status == ItemStatus.done and not args.force:
        progress = stage_progress(args.workspace or record.workspace)
        if progress is not None and not progress.complete:
            print(
                f"Error: {args.item} workspace has {progress.total - progress.done} stage(s) "
                "still to run (see 'workflow resume'); pass --force to mark it done anyway",
                file=sys.stderr,
            )
            return ExitCode.ERROR
    try:
        update_item(slug, args.item, **mark_fields(status, args.workspace, args.error))
    except FleetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return ExitCode.ERROR
    print(f"Marked {args.item} {status.value}")
    return ExitCode.SUCCESS
