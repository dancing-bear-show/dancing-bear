"""Session-level rendering helpers for the telemetry CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

from core.text_utils import truncate_text

console = Console()

if TYPE_CHECKING:
    from telemetry.models import SessionSummary

_LABEL_SESSION_ID = "Session ID"


def _truncate_id(s: str) -> str:
    return truncate_text(s, 16, "…")


def _fmt_duration(s: object) -> str:
    """Format session duration as e.g. 2h34m."""
    from telemetry.models import SessionSummary
    if not isinstance(s, SessionSummary) or s.start_time is None or s.end_time is None:
        return "—"
    secs = int((s.end_time - s.start_time).total_seconds())
    h, rem = divmod(secs, 3600)
    m = rem // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _fmt_tokens(n: int) -> str:
    """Format token count with K/M suffix."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _session_to_dict(s: object) -> dict[str, object]:
    """Serialize a SessionSummary to a JSON-safe dict."""
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


def _sessions_json_payload(all_sessions: list[SessionSummary]) -> dict[str, object]:
    """Build the JSON payload for --format json."""
    total_cost = sum(s.total_cost for s in all_sessions)
    return {
        "source": "transcript",
        "session_count": len(all_sessions),
        "total_cost": round(total_cost, 6),
        "sessions": [_session_to_dict(s) for s in all_sessions],
    }


def _build_sessions_table(all_sessions: list[SessionSummary], since_label: str) -> Table:
    """Build a Rich table of sessions."""
    table = Table(show_header=True, header_style="bold", title=f"Sessions ({since_label})")
    table.add_column(_LABEL_SESSION_ID, style="cyan", no_wrap=True)
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
            s.start_time.strftime("%m-%d %H:%M") if s.start_time else "—",
            _fmt_duration(s),
            f"${s.total_cost:.4f}",
            _fmt_tokens(s.input_tokens),
            _fmt_tokens(s.output_tokens),
            _fmt_tokens(s.cache_read_tokens),
            str(len(s.agents)),
            str(s.total_events),
        )
    return table

