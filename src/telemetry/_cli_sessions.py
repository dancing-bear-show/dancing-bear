"""Session-level rendering helpers for the telemetry CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

from core.format_utils import format_tokens as _fmt_tokens
from telemetry.cli_formatters import (
    _fmt_duration,
    _session_to_dict,
    _truncate_id,
)

console = Console()

if TYPE_CHECKING:
    from telemetry.models import SessionSummary

_LABEL_SESSION_ID = "Session ID"


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

