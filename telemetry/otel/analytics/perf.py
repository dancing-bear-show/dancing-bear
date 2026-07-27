"""Performance extraction for telemetry sessions.

Single-pass event extraction and SessionPerf construction, split from cost.py
to isolate performance-related logic from cost calculations.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from telemetry.otel.cost_models import SessionPerf


def _parse_token_attribute(attr: object, event_dict: dict) -> None:
    """Parse a single token attribute and update event_dict."""
    token_keys = {
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "cache_creation_tokens": "cache_creation_tokens",
        "cache_read_tokens": "cache_read_tokens",
    }

    if attr.key not in token_keys:  # type: ignore[union-attr]
        return

    try:
        value = int(float(attr.value.as_str()))  # type: ignore[union-attr]
        event_dict[token_keys[attr.key]] = value  # type: ignore[union-attr]
    except (ValueError, TypeError):
        pass


def _process_api_request(
    event: object, sid: str, acc: dict, api_requests: list[dict]
) -> None:
    """Process an api_request event for cost and perf data."""
    event_dict = {
        "timestamp": event.timestamp,  # type: ignore[union-attr]
        "session_id": sid,
        "model": event.get_attr("model") or "unknown",  # type: ignore[union-attr]
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "duration_ms": event.get_attr_as_float("duration_ms"),  # type: ignore[union-attr]
    }
    for attr in event.attributes:  # type: ignore[union-attr]
        _parse_token_attribute(attr, event_dict)
    api_requests.append(event_dict)

    acc["api_calls"] += 1
    acc["model_mix"][event_dict["model"]] += 1
    terminal = event.get_attr("terminal.type") or ""  # type: ignore[union-attr]
    if terminal:
        acc["terminal_type"] = terminal
    dur = event.get_attr_as_float("duration_ms")  # type: ignore[union-attr]
    if dur is not None and dur > 0:
        acc["api_latencies"].append(dur)


def _process_api_error(event: object, acc: dict) -> None:
    """Process an api_error event."""
    acc["error_count"] += 1
    status = event.get_attr("status_code") or "unknown"  # type: ignore[union-attr]
    acc["error_status_codes"][str(status)] += 1


def _process_tool_result(event: object, acc: dict) -> None:
    """Process a tool_result event."""
    acc["tool_calls"] += 1
    tool_name = event.get_attr("tool_name") or "unknown"  # type: ignore[union-attr]
    acc["tool_usage"][tool_name] += 1
    success_val = event.get_attr("success")  # type: ignore[union-attr]
    if success_val in ("false", "False", False):
        acc["tool_failures"] += 1


def _new_perf_accumulator() -> dict:
    """Create a fresh perf accumulator dict for a session."""
    return {
        "error_count": 0,
        "error_status_codes": defaultdict(int),
        "tool_calls": 0,
        "tool_failures": 0,
        "api_latencies": [],
        "prompt_count": 0,
        "api_calls": 0,
        "model_mix": defaultdict(int),
        "terminal_type": "",
        "tool_usage": defaultdict(int),
    }


def get_session_id(event: object) -> str:
    """Extract session ID from an event."""
    return (
        event.get_attr("session.id")  # type: ignore[union-attr]
        or event.get_attr("session_id")  # type: ignore[union-attr]
        or "unknown"
    )


def _process_user_prompt(acc: dict) -> None:
    """Increment the user prompt counter."""
    acc["prompt_count"] += 1


_EVENT_DISPATCH = {
    "api_request": lambda event, sid, acc, reqs: _process_api_request(event, sid, acc, reqs),
    "api_error": lambda event, _sid, acc, _reqs: _process_api_error(event, acc),
    "tool_result": lambda event, _sid, acc, _reqs: _process_tool_result(event, acc),
    "user_prompt": lambda _event, _sid, acc, _reqs: _process_user_prompt(acc),
}


def _dispatch_event(
    event: object, sid: str, acc: dict, api_requests: list[dict]
) -> None:
    """Dispatch a single event to the appropriate handler."""
    body = event.body  # type: ignore[union-attr]
    for key, handler in _EVENT_DISPATCH.items():
        if key in body:
            handler(event, sid, acc, api_requests)
            return


def _extract_all_events(
    events: list, since: datetime | None = None
) -> tuple[list[dict], dict[str, dict]]:
    """Single-pass extraction of api_requests and session perf accumulators.

    Iterates all events once to extract both cost data (api_request tokens)
    and performance data (errors, tool results, prompts, latency).

    Args:
        events: List of OTLPEventsRecord objects.
        since: Optional cutoff datetime.

    Returns:
        Tuple of (api_requests list, perf_accumulators dict).
        Perf accumulators are raw dicts — call _build_session_perf_objects()
        to convert to SessionPerf dataclasses.
    """
    api_requests: list[dict] = []
    perf_sessions: dict[str, dict] = {}

    for record in events:
        for event in record.log_records:
            if since and event.timestamp < since:
                continue
            sid = get_session_id(event)
            acc = perf_sessions.setdefault(sid, _new_perf_accumulator())
            _dispatch_event(event, sid, acc, api_requests)

    return api_requests, perf_sessions


def _calc_p95(latencies: list[float]) -> float:
    """Calculate p95 latency from a sorted list of latencies.

    *latencies* must be sorted in ascending order before calling this function.
    The index is clamped to ``len - 1`` to guard against floating-point edge cases.
    """
    if not latencies:
        return 0.0
    if len(latencies) >= 20:
        idx = min(int(len(latencies) * 0.95), len(latencies) - 1)
        return latencies[idx]
    return latencies[-1]


def _build_session_perf_objects(
    perf_accumulators: dict[str, dict],
) -> dict[str, SessionPerf]:
    """Convert raw perf accumulators to SessionPerf dataclass objects.

    Args:
        perf_accumulators: Dict of session_id -> raw accumulator dict
            (from _extract_all_events).

    Returns:
        Dict mapping session_id to SessionPerf.
    """
    result: dict[str, SessionPerf] = {}
    for sid, acc in perf_accumulators.items():
        latencies = sorted(acc["api_latencies"])
        total_wait = sum(latencies)
        avg_latency = total_wait / len(latencies) if latencies else 0.0
        p95_latency = _calc_p95(latencies)
        api_calls = acc["api_calls"]
        prompt_count = acc["prompt_count"]

        result[sid] = SessionPerf(
            error_count=acc["error_count"],
            error_rate=(acc["error_count"] / api_calls if api_calls > 0 else 0.0),
            error_status_codes=dict(acc["error_status_codes"]),
            tool_calls=acc["tool_calls"],
            tool_failures=acc["tool_failures"],
            tool_failure_rate=(
                acc["tool_failures"] / acc["tool_calls"] if acc["tool_calls"] > 0 else 0.0
            ),
            avg_api_latency_ms=avg_latency,
            p95_api_latency_ms=p95_latency,
            prompt_count=prompt_count,
            autonomy_ratio=(api_calls / prompt_count if prompt_count > 0 else 0.0),
            model_mix=dict(acc["model_mix"]),
            terminal_type=acc["terminal_type"],
            total_api_wait_ms=total_wait,
            tool_usage=dict(acc["tool_usage"]),
        )

    return result
