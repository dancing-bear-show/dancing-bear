"""Cost breakdown rendering helpers for the telemetry CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table

from telemetry._cli_agents import _COL_EST_COST

if TYPE_CHECKING:
    from telemetry.otel.cost_models import DailyCost
    from telemetry.models import AgentTokenRow, SessionSummary

_COL_BILLED_COST = "Cost (billed)"


def _breakdown_by_agent(all_rows: list[AgentTokenRow]) -> list[dict[str, object]]:
    """One dict per agent type, sorted by est_cost descending."""
    rows: list[dict[str, object]] = [
        {
            "agent": r.agent,
            "calls": r.calls,
            "est_cost": round(r.est_cost, 6),
            "is_estimated": True,
        }
        for r in all_rows
    ]
    rows.sort(key=lambda d: float(d["est_cost"]), reverse=True)  # type: ignore[arg-type]
    return rows


def _breakdown_by_day(sessions: list[SessionSummary]) -> list[dict[str, object]]:
    """Bucket sessions by calendar date, sorted by date descending."""
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
        {"day": day, "est_cost": round(cost, 6), "is_estimated": True}
        for day, cost in buckets.items()
    ]
    rows.sort(key=lambda d: str(d["day"]), reverse=True)
    return rows


def _daily_cost_rows_from_metric(daily: list[DailyCost]) -> list[dict[str, object]]:
    """Adapt DailyCost list to _breakdown_by_day's row shape.

    Keeps the existing table/json/csv rendering code source-agnostic — it
    only ever sees {"day": ..., "est_cost": ..., "is_estimated": ...} dicts,
    regardless of whether the underlying numbers came from transcripts or
    the OTel cost.usage metric. ``is_estimated=False`` here signals that
    ``est_cost`` is actually the authoritative billed figure, not an estimate.
    """
    rows: list[dict[str, object]] = [
        {"day": d.date, "est_cost": round(d.cost, 6), "is_estimated": False} for d in daily
    ]
    rows.sort(key=lambda d: str(d["day"]), reverse=True)
    return rows


def _print_cost_csv(rows: list[dict[str, object]], group_by: str) -> None:
    """Emit cost-breakdown rows as CSV via emit_rows."""
    from core.cli_output import emit_rows

    if not rows:
        return
    headers = ["agent", "calls", "est_cost", "is_estimated"] if group_by == "agent" else ["day", "est_cost", "is_estimated"]
    emit_rows(rows, fmt="csv", headers=headers)


def _build_breakdown_table(
    rows: list[dict[str, object]], group_by: str, since: str
) -> Table:
    """Build a Rich table for cost-breakdown output."""
    title = f"Cost breakdown by {group_by} ({since})"
    table = Table(show_header=True, header_style="bold", title=title, show_footer=True)

    total_cost = sum(float(r["est_cost"]) for r in rows)
    is_estimated = rows[0].get("is_estimated", True) if rows else True
    cost_col = _COL_EST_COST if is_estimated else _COL_BILLED_COST

    if group_by == "agent":
        table.add_column("Agent", style="cyan", no_wrap=True, footer="TOTAL")
        table.add_column("Calls", justify="right", footer=str(sum(int(r["calls"]) for r in rows)))  # type: ignore[arg-type]
        table.add_column(cost_col, justify="right", footer=f"${total_cost:.4f}")
        for r in rows:
            table.add_row(
                str(r["agent"]),
                str(r["calls"]),
                f"${float(r['est_cost']):.4f}",
            )
    else:
        table.add_column("Day", style="cyan", no_wrap=True, footer="TOTAL")
        table.add_column(cost_col, justify="right", footer=f"${total_cost:.4f}")
        for r in rows:
            table.add_row(
                str(r["day"]),
                f"${float(r['est_cost']):.4f}",
            )

    return table
