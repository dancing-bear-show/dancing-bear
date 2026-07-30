"""otel-summary subcommand — aggregated OTEL statistics across all display groups."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.cli_output import emit_one, emit_rows
from telemetry.otel.cli._format_helpers import add_data_dir_argument, add_format_argument, get_work_dir
from telemetry.otel.menubar_provider import (
    OtelDisplayData,
    OtelMenubarProvider,
)
from telemetry.otel.reader import OTLPDataDir

_RELATIVE_SINCE_RE = re.compile(r"^(\d+)([mhdw])$")
_RELATIVE_SINCE_MULTIPLIERS: dict[str, int] = {
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


def _parse_since(value: str) -> float:
    """Parse a --since value to a Unix timestamp cutoff.

    Accepts:
    - Relative: '30m', '6h', '2d', '1w' — time.time() - seconds
    - Absolute: 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM' (UTC)

    Raises:
        argparse.ArgumentTypeError: on unrecognised format
    """
    m = _RELATIVE_SINCE_RE.match(value)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        return time.time() - amount * _RELATIVE_SINCE_MULTIPLIERS[unit]

    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        pass

    raise argparse.ArgumentTypeError(
        f"Invalid --since value {value!r}. "
        "Use relative (30m, 6h, 2d, 1w) or absolute (YYYY-MM-DD, YYYY-MM-DDTHH:MM)."
    )


def main(argv: list[str] | None = None) -> int:
    """Display aggregated OTEL statistics."""
    parser = argparse.ArgumentParser(
        prog="telemetry otel-summary",
        description="Display aggregated OTEL statistics: usage, models, meta, hooks, tools, code, skills, and session patterns",
    )
    add_format_argument(parser, formats=["table", "json"], default="table")
    parser.add_argument(
        "--window",
        choices=["1h", "24h", "7d", "30d"],
        default=None,
        help="Time window for OTEL data aggregation. One of: 1h, 24h (default), 7d, 30d. Mutually exclusive with --since.",
    )
    parser.add_argument(
        "--since",
        metavar="DATETIME",
        default=None,
        help="Show data since this point in time. Accepts: '30m', '6h', '2d', '1w' (relative) or 'YYYY-MM-DD' / 'YYYY-MM-DDTHH:MM' (absolute UTC). Mutually exclusive with --window.",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        default=None,
        help="Show data for a specific calendar day (UTC). Note: not yet implemented — shows --window data instead.",
    )
    add_data_dir_argument(parser)
    args = parser.parse_args(argv)

    if args.since is not None and args.window is not None:
        parser.error("--since and --window are mutually exclusive")

    # Resolve window default here (after mutual-exclusion check) so argparse
    # default=None lets us distinguish "explicitly set" from "not provided".
    window = args.window or "24h"

    cutoff: float | None = None
    display_label = window
    if args.since is not None:
        try:
            cutoff = _parse_since(args.since)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        display_label = f"since_{args.since}"

    data_dir: OTLPDataDir | None = None
    if args.data_dir:
        data_dir = OTLPDataDir(path=Path(args.data_dir))

    provider = OtelMenubarProvider(data_dir=data_dir)
    if args.date:
        showing_label = f"--since {args.since}" if args.since else f"--window {window}"
        print(
            f"note: --date filtering is not yet implemented; showing {showing_label} data instead",
            file=sys.stderr,
        )
    data = provider.get_display_data(window=window, cutoff=cutoff)

    if not data.available:
        print(
            "OTEL data unavailable — collector may be offline or data directory missing.",
            file=sys.stderr,
        )
        return 1

    if args.format == "json":
        return _emit_json(data, window=display_label)
    return _emit_table(data, window=display_label)


def _emit_json(data: OtelDisplayData, window: str = "24h") -> int:
    ou = data.otel_usage
    ms = data.meta_stats
    hk = data.hook_health
    ta = data.tool_activity
    ci = data.code_impact
    sk = data.skills
    sp = data.session_patterns

    payload = {
        "source": "otel",
        "window": window,
        "usage": {
            f"cost_{window}": ou.cost_24h,
            f"total_tokens_{window}": ou.total_tokens_24h,
            f"input_tokens_{window}": ou.input_tokens_24h,
            f"output_tokens_{window}": ou.output_tokens_24h,
            f"cache_read_tokens_{window}": ou.cache_read_tokens_24h,
            f"cache_creation_tokens_{window}": ou.cache_creation_tokens_24h,
            f"active_hours_{window}": ou.active_hours_24h,
            "model_cost_breakdown": [
                {"model": m, "cost": c} for m, c in ou.model_cost_breakdown
            ],
        },
        "models": [
            {"model": m, f"cost_{window}": c, f"total_tokens_{window}": t}
            for m, c, t in data.otel_models.model_rows
        ],
        "meta": {
            "cost_per_active_hour": ms.cost_per_active_hour,
            "cost_per_loc_added": ms.cost_per_loc_added,
            "cost_per_commit": ms.cost_per_commit,
            "cache_hit_rate_pct": ms.cache_hit_rate_pct,
            f"total_tokens_{window}": ms.total_tokens_24h,
        },
        "hooks": {
            "hooks_fired_today": hk.hooks_fired_today,
            "avg_hook_latency_ms": hk.avg_hook_latency_ms,
            "blocking_count": hk.blocking_count,
            "error_count": hk.error_count,
            "hook_names": hk.hook_names,
        },
        "tools": {
            "tool_calls_today": ta.tool_calls_today,
            "accept_rate_pct": ta.accept_rate_pct,
            "top_tools": [{"tool": t, "calls": c} for t, c in ta.top_tools],
            "tool_error_count": ta.tool_error_count,
            "bash_error_rate_pct": ta.bash_error_rate_pct,
            "avg_input_bytes": ta.avg_input_bytes,
            "avg_output_bytes": ta.avg_output_bytes,
        },
        "code": {
            "lines_added_today": ci.lines_added_today,
            "lines_removed_today": ci.lines_removed_today,
            "commits_today": ci.commits_today,
            "compaction_count": ci.compaction_count,
            "tokens_saved_by_compaction": ci.tokens_saved_by_compaction,
            "top_languages": [
                {"language": lang, "edits": cnt} for lang, cnt in ci.top_languages
            ],
        },
        "skills": {
            "skills_invoked_today": sk.skills_invoked_today,
            "top_skills": [
                {"skill": name, "invocations": cnt} for name, cnt in sk.top_skills
            ],
        },
        "sessions": {
            "prompts_today": sp.prompts_today,
            "agent_call_pct": sp.agent_call_pct,
            "effort_mix": sp.effort_mix,
            "model_mix": [{"model": m, "count": cnt} for m, cnt in sp.model_mix],
        },
    }
    wf_cost = _get_workflow_runs_cost_24h()
    if wf_cost is not None:
        payload["workflow_runs_cost_24h"] = round(wf_cost, 4)
    return emit_one(payload, fmt="json")


def _emit_table(data: OtelDisplayData, window: str = "24h") -> int:
    ou = data.otel_usage
    ms = data.meta_stats
    hk = data.hook_health
    ta = data.tool_activity
    ci = data.code_impact
    sk = data.skills
    sp = data.session_patterns

    rows: list[dict] = [
        {"metric": f"cost_{window}", "value": f"${ou.cost_24h:.2f}"},
        {"metric": f"total_tokens_{window}", "value": f"{ou.total_tokens_24h:,}"},
        {"metric": f"active_hours_{window}", "value": f"{ou.active_hours_24h:.1f}h"},
        {"metric": "cache_hit_rate", "value": f"{ms.cache_hit_rate_pct:.1f}%"},
    ]

    for rank, (model, cost, toks) in enumerate(data.otel_models.model_rows, 1):
        short = model.split(".")[-1] if "." in model else model
        rows.append(
            {
                "metric": f"model #{rank} {short}",
                "value": f"${cost:.2f}  {toks // 1000}k tok",
            }
        )

    rows += [
        {"metric": "cost_per_active_hour", "value": f"${ms.cost_per_active_hour:.2f}"},
        {"metric": "cost_per_commit", "value": f"${ms.cost_per_commit:.2f}"},
        {"metric": "cost_per_loc_added", "value": f"${ms.cost_per_loc_added:.4f}"},
        {"metric": "hooks_fired_today", "value": str(hk.hooks_fired_today)},
        {"metric": "hook_avg_latency_ms", "value": f"{hk.avg_hook_latency_ms:.0f}ms"},
        {"metric": "hook_error_count", "value": str(hk.error_count)},
        {"metric": "tool_calls_today", "value": str(ta.tool_calls_today)},
        {"metric": "tool_accept_rate", "value": f"{ta.accept_rate_pct:.1f}%"},
        {"metric": "bash_error_rate", "value": f"{ta.bash_error_rate_pct:.1f}%"},
    ]
    for tool, calls in ta.top_tools[:3]:
        rows.append({"metric": f"  {tool}", "value": f"{calls} calls"})

    rows += [
        {"metric": "lines_added_today", "value": f"+{ci.lines_added_today:,}"},
        {"metric": "lines_removed_today", "value": f"-{ci.lines_removed_today:,}"},
        {"metric": "commits_today", "value": str(ci.commits_today)},
        {"metric": "compactions", "value": str(ci.compaction_count)},
        {"metric": "skills_invoked_today", "value": str(sk.skills_invoked_today)},
    ]
    for skill, cnt in sk.top_skills[:3]:
        rows.append({"metric": f"  {skill}", "value": f"×{cnt}"})

    rows += [
        {"metric": "prompts_today", "value": str(sp.prompts_today)},
        {"metric": "agent_call_pct", "value": f"{sp.agent_call_pct:.1f}%"},
    ]

    wf_cost = _get_workflow_runs_cost_24h()
    if wf_cost is not None:
        rows.append({"metric": "workflow_runs_cost_24h", "value": f"${wf_cost:.4f}"})

    return emit_rows(
        rows, fmt="table", headers=["metric", "value"], empty_msg="No data."
    )


def _stage_cost_if_recent(p: Path, cutoff: datetime) -> float | None:
    """Return subagent_cost_usd from a stage JSON if it finished after cutoff."""
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict):
            return None
        finished_raw = data.get("finished_at", "")
        if not finished_raw:
            return None
        finished = datetime.fromisoformat(finished_raw.replace("Z", "+00:00"))
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        if finished < cutoff:
            return None
        meta = data.get("metadata", {})
        if not isinstance(meta, dict) or "subagent_cost_usd" not in meta:
            return None
        cost_val = meta["subagent_cost_usd"]
        return float(cost_val) if cost_val else 0.0
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def _get_workflow_runs_cost_24h() -> float | None:
    """Sum subagent_cost_usd from workflow stage results in the last 24h."""
    try:
        work_dir = get_work_dir()
        if not work_dir.exists():
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        costs = [
            c
            for p in work_dir.glob("*/stages/*.json")
            if (c := _stage_cost_if_recent(p, cutoff)) is not None
        ]
        return sum(costs) if costs else None
    except (OSError, AttributeError):
        return None
