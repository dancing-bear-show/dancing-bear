"""Handlers for the stuck-run recovery commands: set-state and seed-pr-lifecycle.

Both write stage-result markers into an existing run workspace so ``resume``
(and the orchestrator's resume path) treat work finished outside the
orchestrator as done.  The marker logic lives in :mod:`workflow.set_state`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from core.cli_errors import ExitCode
from core.cli_output import emit_rows
from workflow.cli_dispatch import _stage_names_from_manifest, _stage_names_from_plan
from workflow.cli_helpers import format_workflow_not_found
from workflow.models import StageStatus
from workflow.set_state import (
    DEFAULT_PR_FRAGMENT,
    PrSeed,
    SeedError,
    SetStateRequest,
    seed_pr_lifecycle,
    set_state,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _workspace_or_none(raw: str) -> Path | None:
    """Return the run workspace, or print why it is not one and return None.

    A run workspace has a manifest.json (as ``resume`` requires).  Checking for
    it stops an empty or mistyped argument -- ``Path("")`` is the current
    directory -- from writing a stages/ dir into an arbitrary directory.
    """
    workspace = Path(raw)
    if not raw or not workspace.is_dir():
        print(format_workflow_not_found(raw, label="workspace"), file=sys.stderr)
        return None
    if not (workspace / "manifest.json").is_file():
        print(f"Error: {workspace} is not a run workspace (no manifest.json)", file=sys.stderr)
        return None
    return workspace


def _planned_stages(workspace: Path) -> list[str]:
    """The run's stage names, from plan.json then manifest.json ([] if neither)."""
    return _stage_names_from_plan(workspace) or _stage_names_from_manifest(workspace)


def _parse_data_json(raw: str) -> dict[str, Any]:
    """Parse --data as a JSON object; raise SeedError otherwise."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SeedError(f"invalid --data JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SeedError("invalid --data JSON: expected an object")
    return parsed


def _cmd_set_state(args: argparse.Namespace) -> int:
    """Write one stage-result marker; exit 1 on a bad workspace, name, or --data."""
    from workflow.cli import _emit_one

    workspace = _workspace_or_none(args.workspace_dir)
    if workspace is None:
        return ExitCode.ERROR
    try:
        request = SetStateRequest(
            status=StageStatus(args.status),
            data=_parse_data_json(args.data),
            note=args.note,
            stage_index=args.stage_index,
        )
        seeded = set_state(
            workspace, args.stage_name, request, known_stages=_planned_stages(workspace)
        )
    except SeedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return ExitCode.ERROR
    _emit_one(
        {
            "stage_name": seeded.stage_name,
            "stage_index": seeded.stage_index,
            "status": seeded.status.value,
            "path": str(seeded.path),
        },
        fmt=args.format,
    )
    return ExitCode.SUCCESS


def _fragment_suffixes(fragment: str) -> list[str]:
    """Stage names a fragment injects (before prefixing), in file order."""
    from workflow.include import parse_fragment
    from workflow.parser import WorkflowParseError

    path = Path(fragment)
    if not path.is_absolute() and not path.exists():
        path = _REPO_ROOT / path
    try:
        return [stage.name for stage in parse_fragment(path)]
    except WorkflowParseError as exc:
        raise SeedError(str(exc)) from exc


def _cmd_seed_pr_lifecycle(args: argparse.Namespace) -> int:
    """Mark every stage of an included PR fragment success for one PR."""
    workspace = _workspace_or_none(args.workspace_dir)
    if workspace is None:
        return ExitCode.ERROR
    try:
        seeded = seed_pr_lifecycle(
            workspace,
            args.prefix,
            _fragment_suffixes(args.fragment or DEFAULT_PR_FRAGMENT),
            PrSeed(pr_number=args.pr_number, url=args.url, note=args.note),
            known_stages=_planned_stages(workspace),
        )
    except SeedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return ExitCode.ERROR
    rows: list[dict[str, object]] = [
        {"index": s.stage_index, "stage": s.stage_name, "path": str(s.path)}
        for s in seeded
    ]
    emit_rows(rows, fmt=args.format, headers=["index", "stage", "path"])
    return ExitCode.SUCCESS
