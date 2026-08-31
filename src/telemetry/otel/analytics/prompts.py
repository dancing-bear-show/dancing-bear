"""Per-prompt metrics analytics.

Correlates api_request, tool_result, and user_prompt events by prompt.id
to produce per-prompt token spend, cost, tool calls, and duration.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from telemetry.otel.analytics.cost import get_model_pricing
from telemetry.otel.analytics.perf import get_session_id
from telemetry.otel.cost_models import PromptMetrics
from telemetry.otel.reader import OTLPDataDir, OTLPReader
from telemetry.timeutil import now_utc, parse_window

if TYPE_CHECKING:
    from telemetry.otel.models import OTLPEvent, OTLPEventsRecord


def get_prompt_metrics(
    data_dir: OTLPDataDir | None = None,
    since: str | None = None,
    session_id: str | None = None,
) -> list[PromptMetrics]:
    """Extract per-prompt metrics from telemetry events.

    Groups events by prompt.id to compute cost, tokens, tool usage,
    and duration per user prompt.

    Args:
        data_dir: Optional OTLPDataDir. If None, uses environment default.
        since: Optional time window (e.g., "7d", "24h").
        session_id: Optional session ID filter.

    Returns:
        List of PromptMetrics sorted by timestamp (most recent first).
    """
    if data_dir is None:
        data_dir = OTLPDataDir.from_env()

    reader = OTLPReader(data_dir)
    events = reader.read_events()

    since_dt = _parse_since(since)
    prompts = _accumulate_prompt_events(events, since_dt, session_id)
    return _build_prompt_metrics(prompts)


def _parse_since(since: str | None) -> datetime | None:
    """Parse a time window string into a datetime cutoff."""
    if not since:
        return None
    return now_utc() - parse_window(since)


@dataclass
class _PromptAccumulator:
    """Mutable accumulator for per-prompt metrics during event processing."""

    session_id: str = "unknown"
    timestamp: datetime | None = None
    prompt_length: int = 0
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cost: float = 0.0
    tool_calls: int = 0
    tool_failures: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None


def _matches_prompt_filters(
    event: OTLPEvent,
    since_dt: datetime | None,
    session_id: str | None,
) -> bool:
    """Return True when event passes the since/session_id filters."""
    if since_dt and event.timestamp < since_dt:
        return False
    if session_id and get_session_id(event) != session_id:
        return False
    return True


def _accumulate_record_events(
    record: OTLPEventsRecord,
    prompts: dict[str, _PromptAccumulator],
    since_dt: datetime | None,
    session_id: str | None,
) -> None:
    """Accumulate all log_records of a single record into prompts."""
    for event in record.log_records:
        if not _matches_prompt_filters(event, since_dt, session_id):
            continue

        prompt_id = event.get_attr("prompt.id")
        if not prompt_id:
            continue

        acc = prompts[prompt_id]
        acc.session_id = get_session_id(event)
        _dispatch_prompt_event(event, acc)


def _accumulate_prompt_events(
    events: list,
    since_dt: datetime | None,
    session_id: str | None,
) -> dict[str, _PromptAccumulator]:
    """Walk events and accumulate per-prompt metrics."""
    prompts: dict[str, _PromptAccumulator] = defaultdict(_PromptAccumulator)

    for record in events:
        _accumulate_record_events(record, prompts, since_dt, session_id)

    return prompts


def _dispatch_prompt_event(event: OTLPEvent, acc: _PromptAccumulator) -> None:
    """Route an event to the appropriate processor."""
    body = event.body
    if "user_prompt" in body:
        _process_user_prompt(event, acc)
    elif "api_request" in body:
        _process_api_request(event, acc)
    elif "tool_result" in body:
        _process_tool_result(event, acc)


def _build_prompt_metrics(prompts: dict[str, _PromptAccumulator]) -> list[PromptMetrics]:
    """Convert accumulated data into sorted PromptMetrics list."""
    result = []
    for pid, acc in prompts.items():
        duration_ms = 0.0
        if acc.first_ts and acc.last_ts:
            duration_ms = (acc.last_ts - acc.first_ts).total_seconds() * 1000

        result.append(PromptMetrics(
            prompt_id=pid,
            session_id=acc.session_id,
            timestamp=(acc.first_ts.isoformat() if acc.first_ts else None),
            prompt_length=acc.prompt_length,
            api_calls=acc.api_calls,
            input_tokens=acc.input_tokens,
            output_tokens=acc.output_tokens,
            cost=round(acc.cost, 6),
            tool_calls=acc.tool_calls,
            tool_failures=acc.tool_failures,
            duration_ms=round(duration_ms, 1),
        ))

    result.sort(key=lambda p: p.timestamp or "", reverse=True)
    return result


def _process_user_prompt(event: OTLPEvent, acc: _PromptAccumulator) -> None:
    """Extract prompt metadata from a user_prompt event."""
    _update_time_range(event.timestamp, acc)
    length_str = event.get_attr("prompt_length")
    if length_str:
        try:
            acc.prompt_length = int(length_str)
        except (ValueError, TypeError):
            pass


def _process_api_request(event: OTLPEvent, acc: _PromptAccumulator) -> None:
    """Extract token counts and cost from an api_request event."""
    _update_time_range(event.timestamp, acc)
    acc.api_calls += 1

    input_tokens = _int_attr(event, "input_tokens")
    output_tokens = _int_attr(event, "output_tokens")
    cache_creation = _int_attr(event, "cache_creation_input_tokens")

    acc.input_tokens += input_tokens
    acc.output_tokens += output_tokens
    acc.cache_creation_tokens += cache_creation

    model = event.get_attr("model") or "unknown"
    input_price, output_price = get_model_pricing(model)
    acc.cost += (
        (input_tokens * input_price / 1_000_000)
        + (output_tokens * output_price / 1_000_000)
        + (cache_creation * input_price / 1_000_000)
    )


def _process_tool_result(event: OTLPEvent, acc: _PromptAccumulator) -> None:
    """Count tool calls and failures from a tool_result event."""
    _update_time_range(event.timestamp, acc)
    acc.tool_calls += 1
    success = event.get_attr("success")
    if success in ("false", "False", False):
        acc.tool_failures += 1


def _update_time_range(ts: datetime, acc: _PromptAccumulator) -> None:
    """Track earliest and latest event timestamps."""
    if acc.first_ts is None or ts < acc.first_ts:
        acc.first_ts = ts
    if acc.last_ts is None or ts > acc.last_ts:
        acc.last_ts = ts


def _int_attr(event: OTLPEvent, key: str) -> int:
    """Get an integer attribute, returning 0 if absent or invalid."""
    val = event.get_attr_as_float(key)
    if val is not None:
        return int(val)
    raw = event.get_attr(key)
    if raw:
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass
    return 0
