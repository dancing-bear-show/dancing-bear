"""workflow-cost subcommand — per-stage cost breakdown from workflow stage JSON files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.cli_output import emit_rows
from telemetry.otel.cli._format_helpers import add_format_argument, get_work_dir
from telemetry.timeutil import parse_window

_NO_METADATA_MSG = (
    "No cost metadata found in stage results — workflow skill version"
    " may predate cost tracking"
)


def _coerce_float(v: object) -> float:
    """Safely coerce a metadata value to float, returning 0.0 on failure."""
    try:
        return float(v) if v else 0.0
    except (TypeError, ValueError):
        return 0.0


def _coerce_int(v: object) -> int:
    """Safely coerce a metadata value to int, returning 0 on failure."""
    try:
        return int(v) if v else 0
    except (TypeError, ValueError):
        return 0


def main(argv: list[str] | None = None) -> int:
    """Show per-stage cost breakdown for a workflow run."""
    parser = argparse.ArgumentParser(
        prog="telemetry workflow-cost",
        description="Show per-stage cost/token breakdown for a workflow run",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--workspace",
        type=str,
        help="Path to a workflow workspace directory (stages/*.json)",
    )
    mode.add_argument(
        "--since",
        type=str,
        help="Time window (e.g. '2h', '1d', '7d') — scans all runs under work_dir",
    )
    add_format_argument(parser, formats=["table", "json", "csv"], default="table")

    args = parser.parse_args(argv)

    if not args.workspace and not args.since:
        parser.error("one of --workspace or --since is required")

    if args.workspace:
        return _run_workspace_mode(Path(args.workspace), args.format)
    return _run_since_mode(args.since, args.format)


def _run_workspace_mode(workspace: Path, fmt: str) -> int:
    stages_dir = workspace / "stages"
    if not workspace.exists():
        print(f"Error: workspace not found: {workspace}", file=sys.stderr, flush=True)
        return 1

    stage_results = _read_stage_results(stages_dir)
    if not stage_results:
        print(f"Error: no stage results found in {stages_dir}", file=sys.stderr, flush=True)
        return 1

    rows, has_cost = _build_workspace_rows(stage_results)

    if not has_cost:
        print(_NO_METADATA_MSG, file=sys.stderr, flush=True)
        emit_rows([], fmt=fmt, headers=["stage", "model", "tokens", "cost_usd", "tool_uses", "duration_agent_ms"])
        return 0

    emit_rows(
        rows,
        fmt=fmt,
        headers=["stage", "model", "tokens", "cost_usd", "tool_uses", "duration_agent_ms"],
    )
    return 0


def _read_stage_results(stages_dir: Path) -> list[dict]:
    results = []
    if not stages_dir.exists():
        return results
    for p in sorted(stages_dir.glob("*.json")):
        try:
            parsed = json.loads(p.read_text())
            if isinstance(parsed, dict):
                results.append(parsed)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue  # nosec B110 - skip unreadable stage files silently
    return results


def _build_workspace_rows(stage_results: list[dict]) -> tuple[list[dict], bool]:
    rows = []
    total_tokens = 0
    total_cost = 0.0
    total_tool_uses = 0
    total_duration = 0
    has_cost = False

    for s in stage_results:
        raw_meta = s.get("metadata", {})
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        cost = _coerce_float(meta.get("subagent_cost_usd", 0.0))
        tokens = _coerce_int(meta.get("subagent_tokens", 0))
        tool_uses = _coerce_int(meta.get("tool_uses", 0))
        duration = _coerce_int(meta.get("duration_agent_ms", 0))
        if "subagent_cost_usd" in meta:
            has_cost = True
        rows.append(
            {
                "stage": s.get("stage_name", ""),
                "model": meta.get("model", ""),
                "tokens": tokens,
                "cost_usd": round(cost, 4),
                "tool_uses": tool_uses,
                "duration_agent_ms": duration,
            }
        )
        total_tokens += tokens
        total_cost += cost
        total_tool_uses += tool_uses
        total_duration += duration

    rows.append(
        {
            "stage": "TOTAL",
            "model": "",
            "tokens": total_tokens,
            "cost_usd": round(total_cost, 4),
            "tool_uses": total_tool_uses,
            "duration_agent_ms": total_duration,
        }
    )
    return rows, has_cost


def _load_stage_if_in_window(p: Path, cutoff: datetime) -> dict | None:
    """Parse a stage JSON file and return its data if finished_at >= cutoff, else None."""
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict):
            return None
        finished_raw = data.get("finished_at", "")
        if not isinstance(finished_raw, str) or not finished_raw:
            return None
        finished = datetime.fromisoformat(finished_raw.replace("Z", "+00:00"))
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        if finished < cutoff:
            return None
        meta = data.get("metadata", {})
        if not isinstance(meta, dict):
            data = {**data, "metadata": {}}
        return data
    except (OSError, ValueError):
        return None


def _run_since_mode(since_str: str, fmt: str) -> int:
    try:
        delta = parse_window(since_str, default_unit="minutes")
    except (ValueError, TypeError) as e:
        print(f"Error: invalid --since value {since_str!r}: {e}", file=sys.stderr, flush=True)
        return 1

    cutoff = datetime.now(timezone.utc) - delta
    work_dir = get_work_dir()

    run_groups: dict[str, list[dict]] = {}
    has_cost = False
    stages_in_window = 0
    for p in sorted(work_dir.glob("*/stages/*.json")):
        data = _load_stage_if_in_window(p, cutoff)
        if data is None:
            continue
        stages_in_window += 1
        if "subagent_cost_usd" in data.get("metadata", {}):
            has_cost = True
        run_id = p.parent.parent.name
        run_groups.setdefault(run_id, []).append(data)

    if stages_in_window == 0:
        emit_rows([], fmt=fmt, headers=["run_id", "workflow", "started_at", "stages", "total_tokens", "total_cost_usd"])
        return 0

    if not has_cost:
        print(_NO_METADATA_MSG, file=sys.stderr, flush=True)
        emit_rows([], fmt=fmt, headers=["run_id", "workflow", "started_at", "stages", "total_tokens", "total_cost_usd"])
        return 0

    rows = _build_since_rows(run_groups)
    emit_rows(
        rows,
        fmt=fmt,
        headers=["run_id", "workflow", "started_at", "stages", "total_tokens", "total_cost_usd"],
    )
    return 0


def _earliest_started_at(stages: list[dict]) -> str:
    """Return the earliest started_at timestamp across stages as an ISO string, or ''."""
    dts = []
    for s in stages:
        raw = s.get("started_at", "")
        if not isinstance(raw, str) or not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dts.append(dt)
        except ValueError:
            pass
    return min(dts).isoformat() if dts else ""


def _build_since_rows(run_groups: dict[str, list[dict]]) -> list[dict]:
    rows = []
    grand_tokens = 0
    grand_cost = 0.0

    for run_id, stages in sorted(run_groups.items()):
        workflow = re.sub(r"-\d{8}-[0-9a-f]{8}$", "", run_id)
        started_at = _earliest_started_at(stages)
        total_tokens = sum(_coerce_int(s.get("metadata", {}).get("subagent_tokens", 0)) for s in stages)
        total_cost = sum(_coerce_float(s.get("metadata", {}).get("subagent_cost_usd", 0.0)) for s in stages)
        rows.append(
            {
                "run_id": run_id,
                "workflow": workflow,
                "started_at": started_at,
                "stages": len(stages),
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 4),
            }
        )
        grand_tokens += total_tokens
        grand_cost += total_cost

    rows.append(
        {
            "run_id": "TOTAL",
            "workflow": "",
            "started_at": "",
            "stages": sum(r["stages"] for r in rows),
            "total_tokens": grand_tokens,
            "total_cost_usd": round(grand_cost, 4),
        }
    )
    return rows
