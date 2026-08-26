"""Pure formatting/parsing helpers extracted from telemetry/cli.py."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import click
from rich.table import Table

from core.cli_output import emit_one
from core.format_utils import format_tokens as _fmt_tokens
from core.text_utils import truncate_text

if TYPE_CHECKING:
    from telemetry.models import AgentTokenRow, SessionSummary

_COL_EST_COST = "Est. Cost"

_AGENT_SORT_KEYS = {
    "cost": lambda r: r.est_cost,
    "output": lambda r: r.output_tokens,
    "calls": lambda r: r.calls,
    "input": lambda r: r.input_tokens,
    "cache-read": lambda r: r.cache_read_tokens,
}


def _truncate_id(s: str) -> str:
    return truncate_text(s, 16, "…")


def _parse_since_cli(since: str) -> datetime:
    """Parse --since window string, raising click.BadParameter on bad input."""
    from telemetry.timeutil import now_utc, parse_window

    if since.strip().isdigit():
        raise click.BadParameter(
            f"bare integer {since!r} is ambiguous — use a unit suffix (e.g. {since}h, {since}d)",
            param_hint="--since",
        )
    try:
        return now_utc() - parse_window(since)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="--since") from e


def _fmt_duration(s: object) -> str:
    from telemetry.models import SessionSummary
    if not isinstance(s, SessionSummary) or s.start_time is None or s.end_time is None:
        return "—"
    secs = int((s.end_time - s.start_time).total_seconds())
    h, rem = divmod(secs, 3600)
    m = rem // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"



def _session_to_dict(s: object) -> dict[str, object]:
    from telemetry.models import SessionSummary
    if not isinstance(s, SessionSummary):
        return {}
    dur = None
    if s.start_time and s.end_time:
        dur = round((s.end_time - s.start_time).total_seconds() / 60, 1)
    return {
        "session_id": s.session_id,
        "project_path": s.project_path,
        "start_time": s.start_time.isoformat() if s.start_time else None,
        "end_time": s.end_time.isoformat() if s.end_time else None,
        "duration_minutes": dur,
        "model": s.model,
        "total_cost": round(s.total_cost, 6),
        "total_events": s.total_events,
        "input_tokens": s.input_tokens,
        "output_tokens": s.output_tokens,
        "cache_read_tokens": s.cache_read_tokens,
        "cache_creation_tokens": s.cache_creation_tokens,
        "efficiency_score": round(s.efficiency_score, 6),
        "num_agents": len(s.agents),
        "agents": [
            {
                "agent_id": a.agent_id,
                "agent_type": a.agent_type,
                "description": a.description,
                "model": a.model,
                "duration_ms": a.duration_ms,
                "total_tokens": a.total_tokens,
                "total_tool_uses": a.total_tool_uses,
                "cost_usd": round(a.cost_usd, 6),
            }
            for a in s.agents
        ],
    }


def _sessions_json_payload(all_sessions: list["SessionSummary"]) -> dict[str, object]:
    total_cost = sum(s.total_cost for s in all_sessions)
    return {
        "session_count": len(all_sessions),
        "total_cost": round(total_cost, 6),
        "sessions": [_session_to_dict(s) for s in all_sessions],
    }


def _build_sessions_table(all_sessions: list["SessionSummary"], since_label: str) -> Table:
    table = Table(show_header=True, header_style="bold", title=f"Sessions ({since_label})")
    table.add_column("Session ID", style="cyan", no_wrap=True)
    table.add_column("Project", no_wrap=True)
    table.add_column("Start")
    table.add_column("Duration", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("In", justify="right")
    table.add_column("Out", justify="right")
    table.add_column("Cache", justify="right")
    table.add_column("Agents", justify="right")
    table.add_column("Events", justify="right")
    for s in all_sessions:
        parts = [p for p in (s.project_path or "").split("/") if p]
        project = "/".join(parts[-2:]) if len(parts) >= 2 else (s.project_path or "—")
        table.add_row(
            _truncate_id(s.session_id),
            project[-22:],
            s.start_time.strftime("%m-%d %H:%M"),
            _fmt_duration(s),
            f"${s.total_cost:.4f}",
            _fmt_tokens(s.input_tokens),
            _fmt_tokens(s.output_tokens),
            _fmt_tokens(s.cache_read_tokens),
            str(len(s.agents)),
            str(s.total_events),
        )
    return table


def _agent_row_to_dict(r: object) -> dict[str, object]:
    from telemetry.models import AgentTokenRow
    if not isinstance(r, AgentTokenRow):
        return {}
    return {
        "agent": r.agent,
        "calls": r.calls,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "cache_read_tokens": r.cache_read_tokens,
        "cache_write_tokens": r.cache_write_tokens,
        "models": r.models,
        "est_cost": round(r.est_cost, 6),
    }


def _print_agents_json(all_rows: list["AgentTokenRow"], rows: list["AgentTokenRow"], since: str) -> None:
    emit_one(
        {
            "agent_count": len(all_rows),
            "returned_count": len(rows),
            "since": since,
            "total_cost": round(sum(r.est_cost for r in all_rows), 6),
            "agents": [_agent_row_to_dict(r) for r in rows],
        },
        fmt="json",
    )


def _print_agents_csv(rows: list["AgentTokenRow"]) -> None:
    import csv as csv_mod
    import io

    buf = io.StringIO()
    writer = csv_mod.writer(buf)
    writer.writerow([
        "agent", "calls", "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_write_tokens", "models", "est_cost",
    ])
    for r in rows:
        writer.writerow([
            r.agent, r.calls, r.input_tokens, r.output_tokens,
            r.cache_read_tokens, r.cache_write_tokens,
            ";".join(r.models), round(r.est_cost, 6),
        ])
    from rich.console import Console
    Console().print(buf.getvalue(), end="")


def _build_agents_table(all_rows: list["AgentTokenRow"], rows: list["AgentTokenRow"], since: str) -> Table:
    table = Table(show_header=True, header_style="bold", title=f"Agent usage ({since})", show_footer=True)
    table.add_column("Agent", style="cyan", no_wrap=True, footer="TOTAL")
    table.add_column("Calls", justify="right", footer=str(sum(r.calls for r in all_rows)))
    table.add_column("In", justify="right", footer=_fmt_tokens(sum(r.input_tokens for r in all_rows)))
    table.add_column("Out", justify="right", footer=_fmt_tokens(sum(r.output_tokens for r in all_rows)))
    table.add_column("Cache R", justify="right", footer=_fmt_tokens(sum(r.cache_read_tokens for r in all_rows)))
    table.add_column("Cache W", justify="right", footer=_fmt_tokens(sum(r.cache_write_tokens for r in all_rows)))
    table.add_column("Models")
    table.add_column(_COL_EST_COST, justify="right", footer=f"${sum(r.est_cost for r in all_rows):.4f}")
    for r in rows:
        table.add_row(
            r.agent,
            str(r.calls),
            _fmt_tokens(r.input_tokens),
            _fmt_tokens(r.output_tokens),
            _fmt_tokens(r.cache_read_tokens),
            _fmt_tokens(r.cache_write_tokens),
            ", ".join(r.models) or "—",
            f"${r.est_cost:.4f}",
        )
    return table


def _breakdown_by_agent(all_rows: list["AgentTokenRow"]) -> list[dict[str, object]]:
    rows = [
        {
            "agent": r.agent,
            "calls": r.calls,
            "est_cost": round(r.est_cost, 6),
        }
        for r in all_rows
    ]
    rows.sort(key=lambda d: float(d["est_cost"]), reverse=True)  # type: ignore[arg-type]
    return rows


def _breakdown_by_day(sessions: list["SessionSummary"]) -> list[dict[str, object]]:
    import sys as _sys
    from collections import defaultdict

    buckets: dict[str, float] = defaultdict(float)
    skipped = sum(1 for s in sessions if s.start_time is None)
    if skipped:
        print(f"Warning: {skipped} session(s) with no start time skipped", file=_sys.stderr)
    for session in sessions:
        if session.start_time is None:
            continue
        day_key = session.start_time.date().isoformat()
        buckets[day_key] += session.total_cost

    rows: list[dict[str, object]] = [
        {"day": day, "est_cost": round(cost, 6)}
        for day, cost in buckets.items()
    ]
    rows.sort(key=lambda d: str(d["day"]), reverse=True)
    return rows


def _print_cost_csv(rows: list[dict[str, object]], _group_by: str) -> None:
    import csv
    import sys as _sys

    if not rows:
        return
    writer = csv.DictWriter(_sys.stdout, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)


def _build_breakdown_table(
    rows: list[dict[str, object]], group_by: str, since: str
) -> Table:
    title = f"Cost breakdown by {group_by} ({since})"
    table = Table(show_header=True, header_style="bold", title=title, show_footer=True)

    total_cost = sum(float(r["est_cost"]) for r in rows)

    if group_by == "agent":
        table.add_column("Agent", style="cyan", no_wrap=True, footer="TOTAL")
        table.add_column("Calls", justify="right", footer=str(sum(int(r["calls"]) for r in rows)))  # type: ignore[arg-type]
        table.add_column(_COL_EST_COST, justify="right", footer=f"${total_cost:.4f}")
        for r in rows:
            table.add_row(
                str(r["agent"]),
                str(r["calls"]),
                f"${float(r['est_cost']):.4f}",
            )
    else:
        table.add_column("Day", style="cyan", no_wrap=True, footer="TOTAL")
        table.add_column(_COL_EST_COST, justify="right", footer=f"${total_cost:.4f}")
        for r in rows:
            table.add_row(
                str(r["day"]),
                f"${float(r['est_cost']):.4f}",
            )

    return table
