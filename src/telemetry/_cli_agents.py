"""Agent-level rendering helpers for the telemetry CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table

from telemetry._cli_sessions import _fmt_tokens

if TYPE_CHECKING:
    from telemetry.models import AgentTokenRow

_COL_EST_COST = "Est. Cost"


def _agent_row_to_dict(r: object) -> dict[str, object]:
    """Serialize one AgentTokenRow to a JSON-safe dict."""
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


def _print_agents_json(all_rows: list[AgentTokenRow], rows: list[AgentTokenRow], since: str) -> None:
    """Emit agent data as JSON."""
    from core.cli_output import emit_one
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


def _print_agents_csv(rows: list[AgentTokenRow]) -> None:
    """Emit agent data as CSV via emit_rows for consistent quoting and headers."""
    from core.cli_output import emit_rows

    _HEADERS = [
        "agent", "calls", "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_write_tokens", "models", "est_cost",
    ]
    emit_rows(
        [
            {
                "agent": r.agent,
                "calls": r.calls,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cache_read_tokens": r.cache_read_tokens,
                "cache_write_tokens": r.cache_write_tokens,
                "models": ";".join(r.models),
                "est_cost": round(r.est_cost, 6),
            }
            for r in rows
        ],
        fmt="csv",
        headers=_HEADERS,
    )


def _build_agents_table(all_rows: list[AgentTokenRow], rows: list[AgentTokenRow], since: str) -> Table:
    """Build a Rich table of agent usage."""
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
