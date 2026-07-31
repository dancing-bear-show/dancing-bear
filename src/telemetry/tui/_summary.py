"""Session summary computation — aggregates events into SessionSummary."""

from dataclasses import dataclass
from datetime import datetime, timezone

from telemetry.models import (
    AgentSummary,
    SessionEvent,
    SessionSummary,
    ToolStats,
)


@dataclass(frozen=True)
class SummaryConfig:
    """Session-level metadata passed alongside event data to compute_summary."""

    session_id: str | None
    project_path: str | None
    cost_is_estimated: bool
    total_cost_override: float | None = None


def _build_tool_stats(tool_events: list[SessionEvent]) -> dict[str, ToolStats]:
    """Aggregate per-tool call counts, costs, and waste counts."""
    tool_stats: dict[str, ToolStats] = {}
    for evt in tool_events:
        name = evt.tool_name or "unknown"
        stat = tool_stats.setdefault(name, ToolStats(tool_name=name))
        stat.count += 1
        if evt.cost_usd:
            stat.cost += evt.cost_usd
        if evt.classification == "avoidable":
            stat.avoidable_count += 1
        elif evt.classification == "review":
            stat.review_count += 1
    return tool_stats


def _latest_model(api_events: list[SessionEvent]) -> str:
    """Return the model name from the most recent api_request event."""
    for e in reversed(api_events):
        if e.model:
            return e.model
    return ""


def compute_summary(  # noqa: S3776 - flat aggregation; many generator expressions inflate score but there is no reducible nesting
    events: list[SessionEvent],
    agents: list[AgentSummary],
    config: SummaryConfig,
) -> SessionSummary:
    tool_events = [e for e in events if e.event_type == "tool_use"]
    api_events = [e for e in events if e.event_type == "api_request"]

    productive = sum(1 for e in tool_events if e.classification == "productive")
    neutral = sum(1 for e in tool_events if e.classification == "neutral")
    avoidable = sum(1 for e in tool_events if e.classification == "avoidable")
    review = sum(1 for e in tool_events if e.classification == "review")
    total = len(tool_events)

    efficiency_score = (
        (productive * 1.0 + neutral * 0.5) / total * 100 if total > 0 else 100.0
    )

    input_tokens = sum(e.input_tokens or 0 for e in api_events)
    output_tokens = sum(e.output_tokens or 0 for e in api_events)
    cache_read = sum(e.cache_read_tokens or 0 for e in api_events)
    cache_creation = sum(e.cache_creation_tokens or 0 for e in api_events)

    total_cacheable = input_tokens + cache_read
    cache_hit_rate: float | None = (
        cache_read / total_cacheable if total_cacheable > 0 else None
    )

    tool_stats = _build_tool_stats(tool_events)

    total_cost = (
        config.total_cost_override
        if config.total_cost_override is not None
        else sum(e.cost_usd or 0.0 for e in api_events)
    )
    productive_cost = sum(e.cost_usd or 0.0 for e in api_events if e.cost_usd)
    avoidable_cost = sum(
        e.cost_usd or 0.0
        for e in tool_events if e.classification == "avoidable" and e.cost_usd
    )

    start_time = events[0].timestamp if events else datetime.now(timezone.utc)
    end_time = events[-1].timestamp if events else None

    return SessionSummary(
        session_id=config.session_id,
        project_path=config.project_path,
        start_time=start_time,
        end_time=end_time,
        model=_latest_model(api_events),
        total_cost=total_cost,
        cost_is_estimated=config.cost_is_estimated,
        total_events=len(events),
        efficiency_score=efficiency_score,
        productive_count=productive,
        neutral_count=neutral,
        avoidable_count=avoidable,
        review_count=review,
        productive_cost=productive_cost,
        avoidable_cost=avoidable_cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
        cache_hit_rate=cache_hit_rate,
        tool_stats=tool_stats,
        agents=agents,
    )
