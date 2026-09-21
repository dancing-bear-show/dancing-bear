"""Timeline logic for the sessions subcommand.

Extracted from sessions.py to reduce complexity.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from telemetry.otel.reader import OTLPDataDir, OTLPReader

if TYPE_CHECKING:
    from telemetry.otel.models import OTLPEvent


def _sum_token_attrs(event: OTLPEvent) -> int:
    """Sum input_tokens and output_tokens from event attributes."""
    total = 0
    for attr in event.attributes:
        if attr.key in ("input_tokens", "output_tokens"):
            try:
                total += int(float(attr.value.as_str()))
            except (ValueError, TypeError):
                pass
    return total


def _extract_tool_result_detail(event: OTLPEvent) -> str:
    """Extract detail from a tool_result event."""
    tool_name = event.get_attr("tool_name") or "unknown"
    success = event.get_attr("success")
    duration = event.get_attr_as_float("duration_ms")
    outcome = "ok" if success not in ("false", "False", False) else "fail"
    dur_str = f", {duration:.0f}ms" if duration else ""
    return f"{tool_name}, {outcome}{dur_str}"


def _format_api_request_detail(
    model: str, duration: float | None, tokens: int
) -> str:
    """Format api_request detail string."""
    model_lower = model.lower()
    if "opus" in model_lower:
        short_model = "opus"
    elif "sonnet" in model_lower:
        short_model = "sonnet"
    elif "haiku" in model_lower:
        short_model = "haiku"
    else:
        short_model = model

    parts = [short_model]
    if duration:
        parts.append(f"{duration / 1000:.1f}s")
    if tokens > 0:
        if tokens >= 1000:
            parts.append(f"{tokens / 1000:.1f}K tokens")
        else:
            parts.append(f"{tokens} tokens")
    return ", ".join(parts)


def _extract_api_request_detail(event: OTLPEvent) -> str:
    """Extract detail from an api_request event."""
    model = event.get_attr("model") or "unknown"
    duration = event.get_attr_as_float("duration_ms")
    tokens = _sum_token_attrs(event)
    return _format_api_request_detail(model, duration, tokens)


def _extract_event_detail(event: OTLPEvent, body: str) -> str:
    """Extract detail string based on event type."""
    if "api_request" in body:
        return _extract_api_request_detail(event)
    if "api_error" in body:
        status = event.get_attr("status_code") or "unknown"
        return f"status={status}"
    if "tool_result" in body:
        return _extract_tool_result_detail(event)
    if "user_prompt" in body:
        length = event.get_attr("prompt_length") or ""
        return f"{length} chars" if length else ""
    return ""


def _event_to_timeline_entry(event: OTLPEvent) -> dict[str, object]:
    """Convert an OTLPEvent to a timeline entry dict."""
    body = event.body
    return {
        "timestamp": event.timestamp,
        "event_type": body,
        "detail": _extract_event_detail(event, body),
    }


def _format_timeline_entry(entry: dict) -> str:
    """Format a timeline entry for display."""
    ts: datetime | None = entry.get("timestamp")
    if ts:
        time_str = ts.strftime("%H:%M:%S")
    else:
        time_str = "??:??:??"

    event_type = entry["event_type"]
    if "." in event_type:
        event_type = event_type.rsplit(".", 1)[-1]

    detail = entry.get("detail", "")
    if detail:
        return f"[{time_str}] {event_type} ({detail})"
    return f"[{time_str}] {event_type}"


def _output_timeline(
    data_dir: OTLPDataDir,
    session_id: str,
    since: datetime | None,
) -> None:
    """Display chronological event timeline for a session."""
    reader = OTLPReader(data_dir=data_dir)
    records = reader.read_events()

    events: list[dict] = []
    for record in records:
        for event in record.log_records:
            if since and event.timestamp < since:
                continue
            sid = (
                event.get_attr("session.id")
                or event.get_attr("session_id")
                or "unknown"
            )
            if sid != session_id:
                continue
            events.append(_event_to_timeline_entry(event))

    if not events:
        print(f"No events found for session {session_id}")
        return

    events.sort(key=lambda e: e["timestamp"])

    print(f"Timeline for {session_id} ({len(events)} events)")
    print("─" * 60)
    for entry in events:
        print(_format_timeline_entry(entry))
