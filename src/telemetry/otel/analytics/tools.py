"""Tool error analysis for telemetry data.

Extracts tool_result events from OTLPReader, groups by tool_name, and
computes per-tool statistics: total_calls, failures, failure_rate,
avg_duration_ms, and sessions_affected.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from telemetry.otel.cost_models import ToolErrorSummary
from telemetry.otel.reader import OTLPDataDir, OTLPReader

if TYPE_CHECKING:
    from telemetry.otel.models import OTLPEvent


@dataclass
class _ToolAccumulator:
    """Mutable accumulator for per-tool statistics during event processing."""

    total_calls: int = 0
    failures: int = 0
    durations: list[float] = field(default_factory=list)
    sessions: set[str] = field(default_factory=set)


def get_tool_summaries(
    data_dir: OTLPDataDir | None = None,
    since: datetime | None = None,
) -> list[ToolErrorSummary]:
    """Compute per-tool usage and error summaries.

    Args:
        data_dir: Optional OTLPDataDir. If None, uses environment default.
        since: Optional cutoff datetime. Only includes events after this time.

    Returns:
        List of ToolErrorSummary, one per distinct tool_name.
    """
    if data_dir is None:
        data_dir = OTLPDataDir.from_env()

    reader = OTLPReader(data_dir)
    events = reader.read_events()
    tools = _accumulate_tool_events(events, since)
    return _build_tool_summaries(tools)


def _accumulate_tool_events(
    events: list, since: datetime | None
) -> dict[str, _ToolAccumulator]:
    """Walk events and accumulate per-tool statistics."""
    tools: dict[str, _ToolAccumulator] = defaultdict(_ToolAccumulator)

    for record in events:
        for event in record.log_records:
            if since and event.timestamp < since:
                continue
            if "tool_result" not in event.body:
                continue
            _process_tool_event(event, tools)

    return tools


def _process_tool_event(
    event: OTLPEvent, tools: dict[str, _ToolAccumulator]
) -> None:
    """Process a single tool_result event into accumulators."""
    tool_name = event.get_attr("tool_name") or "unknown"
    session_id = (
        event.get_attr("session.id")
        or event.get_attr("session_id")
        or "unknown"
    )

    acc = tools[tool_name]
    acc.total_calls += 1
    acc.sessions.add(session_id)

    success_val = event.get_attr("success")
    if success_val in ("false", "False", False):
        acc.failures += 1

    dur = event.get_attr_as_float("duration_ms")
    if dur is not None and dur > 0:
        acc.durations.append(dur)


def _build_tool_summaries(
    tools: dict[str, _ToolAccumulator],
) -> list[ToolErrorSummary]:
    """Convert accumulated tool data into sorted ToolErrorSummary list."""
    summaries: list[ToolErrorSummary] = []
    for tool_name, acc in sorted(tools.items()):
        total = acc.total_calls
        failures = acc.failures
        durations = acc.durations
        avg_dur = sum(durations) / len(durations) if durations else 0.0

        summaries.append(
            ToolErrorSummary(
                tool_name=tool_name,
                total_calls=total,
                failures=failures,
                failure_rate=failures / total if total > 0 else 0.0,
                avg_duration_ms=avg_dur,
                sessions_affected=len(acc.sessions),
            )
        )

    return summaries
