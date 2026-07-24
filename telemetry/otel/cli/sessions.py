"""sessions subcommand — list sessions with token usage and performance."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from core.cli_output import emit_one
from telemetry.otel.analytics.cost import get_all_costs
from telemetry.otel.analytics.health_score import calculate_health_score
from telemetry.otel.cli._format_helpers import (
    format_duration as _format_duration,
    format_timestamp as _format_timestamp,
    format_validation_error,
    sort_sessions as _sort_sessions,
)
from telemetry.otel.cost_models import CostMetrics, SessionCost, SessionPerf
from telemetry.otel.reader import OTLPDataDir, OTLPReader
from telemetry.otel.utils import parse_time_window
from telemetry.timeutil import format_latency as _format_latency


def main(argv: list[str] | None = None) -> int:
    """List sessions with token usage, cost, and performance metrics."""
    parser = argparse.ArgumentParser(
        prog="telemetry sessions",
        description="List sessions with token usage, cost, performance, and errors",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Time range (e.g., '1h', '24h', '7d')",
    )
    parser.add_argument(
        "--sort",
        choices=["cost", "time", "tokens", "errors", "health"],
        default="time",
        help="Sort by cost, time, tokens, errors, or health (default: time)",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        help="Override default data directory",
    )
    parser.add_argument(
        "--perf",
        action="store_true",
        help="Show performance details (latency, model mix, tools)",
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help="Show only sessions with API errors or tool failures",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Show only top N sessions (0 = all)",
    )
    parser.add_argument(
        "--error-codes",
        action="store_true",
        help="Show HTTP error status code breakdown per session",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Show health grade and score per session",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        help="Filter to a specific session ID",
    )
    parser.add_argument(
        "--timeline",
        action="store_true",
        help="Show chronological event timeline (requires --session-id)",
    )

    args = parser.parse_args(argv)

    if args.timeline and not args.session_id:
        return format_validation_error("--timeline", "requires --session-id")

    if args.data_dir:
        data_dir = OTLPDataDir(path=Path(args.data_dir))
    else:
        data_dir = OTLPDataDir.from_env()

    try:
        since = parse_time_window(args.since)
    except ValueError as e:
        return format_validation_error("--since", f"invalid value: {e}")

    if args.timeline:
        _output_timeline(data_dir, args.session_id, since)
        return 0

    metrics = get_all_costs(data_dir=data_dir, since=since)

    if args.format == "json":
        _output_json(
            metrics, args.sort, args.errors_only, args.limit,
            args.error_codes, args.health, args.session_id,
        )
    else:
        _output_table(
            metrics, args.sort, args.perf, args.errors_only, args.limit,
            args.error_codes, args.health, args.session_id,
        )

    return 0


def _format_model_mix(model_mix: dict[str, int]) -> str:
    """Format model mix as compact string (e.g., 'opus:150 haiku:42')."""
    if not model_mix:
        return ""
    short_names: dict[str, int] = {
        "opus": 0,
        "sonnet": 0,
        "haiku": 0,
    }
    for model, count in model_mix.items():
        model_lower = model.lower()
        if "opus" in model_lower:
            short_names["opus"] += count
        elif "sonnet" in model_lower:
            short_names["sonnet"] += count
        elif "haiku" in model_lower:
            short_names["haiku"] += count
        else:
            short_names[model] = count
    parts = [f"{name}:{count}" for name, count in short_names.items() if count > 0]
    return " ".join(parts)


def _has_errors(session: SessionCost) -> bool:
    """Check if session has any errors or tool failures."""
    if not session.perf:
        return False
    return session.perf.error_count > 0 or session.perf.tool_failures > 0


def _filter_sessions(
    sessions: list[SessionCost],
    errors_only: bool,
    limit: int,
    session_id: str | None = None,
) -> list[SessionCost]:
    """Apply common filters to sessions list."""
    if session_id:
        sessions = [s for s in sessions if s.session_id == session_id]

    if errors_only:
        sessions = [s for s in sessions if _has_errors(s)]

    if limit > 0:
        sessions = sessions[:limit]

    return sessions


def _output_table(
    metrics: CostMetrics,
    sort_key: str,
    show_perf: bool,
    errors_only: bool,
    limit: int,
    show_error_codes: bool = False,
    show_health: bool = False,
    session_id: str | None = None,
) -> None:
    """Output session list as formatted table."""
    sessions = _sort_sessions(metrics.by_session, sort_key)
    sessions = _filter_sessions(sessions, errors_only, limit, session_id)

    if not sessions:
        print("No sessions found.")
        return

    total_cost = metrics.total_cost
    print(f"Sessions ({len(sessions)})")
    print("─" * 72)
    for session in sessions:
        _print_session(
            session, total_cost, show_perf, show_error_codes, show_health,
        )
    print("─" * 72)
    total_billable = metrics.total_billable_tokens
    total_all = total_billable + metrics.total_cache_read_tokens
    print(
        f"Total: ${total_cost:.2f}  |  "
        f"{total_billable:,} billable  |  "
        f"{total_all:,} total tokens"
    )


def _print_session(
    session: SessionCost,
    total_cost: float,
    show_perf: bool,
    show_error_codes: bool = False,
    show_health: bool = False,
) -> None:
    """Print a single session's details."""
    pct = (session.cost / total_cost * 100) if total_cost > 0 else 0
    sid = session.session_id
    if len(sid) > 20:
        sid = sid[:8] + "…" + sid[-8:]

    _print_session_header(session, sid, pct)

    perf = session.perf
    if perf and perf.model_mix:
        mix = _format_model_mix(perf.model_mix)
        print(f"    models: {mix}")

    if perf:
        _print_perf_summary(perf, session.api_calls)

    if show_perf and perf:
        _print_perf_details(perf)

    _print_error_codes_standalone(perf, show_error_codes, show_perf)

    if show_health:
        health = calculate_health_score(session)
        print(f"    health: {health.grade} ({health.score:.2f})")


def _print_session_header(session: SessionCost, sid: str, pct: float) -> None:
    """Print the header and token summary lines for a session."""
    ts_start = _format_timestamp(session.first_seen)
    ts_end = _format_timestamp(session.last_seen)
    dur = _format_duration(session.duration_minutes)

    header = f"  {sid}  {ts_start} → {ts_end}  {dur}"
    if session.perf and session.perf.terminal_type:
        header += f"  [{session.perf.terminal_type}]"
    print(header)

    print(
        f"    ${session.cost:.2f} ({pct:.1f}%)  |  "
        f"{session.api_calls:,} calls  |  "
        f"{session.billable_tokens:,} billable tokens"
    )
    print(
        f"    in:{session.input_tokens:,}  "
        f"out:{session.output_tokens:,}  "
        f"cache_create:{session.cache_creation_tokens:,}  "
        f"cache_read:{session.cache_read_tokens:,}"
    )


def _print_error_codes_standalone(
    perf: SessionPerf | None,
    show_error_codes: bool,
    show_perf: bool,
) -> None:
    """Print error status codes when --error-codes is set without --perf."""
    if not show_error_codes or show_perf:
        return
    if not perf or not perf.error_status_codes:
        return
    codes = " ".join(
        f"{code}:{count}"
        for code, count in sorted(perf.error_status_codes.items())
    )
    print(f"    error codes: {codes}")


def _print_perf_summary(perf: SessionPerf, api_calls: int) -> None:
    """Print a one-line perf summary for a session."""
    parts = []

    if perf.avg_api_latency_ms > 0:
        parts.append(f"avg {_format_latency(perf.avg_api_latency_ms)}/call")

    if perf.error_count > 0:
        parts.append(
            f"{perf.error_count} errors ({perf.error_rate:.1%})"
        )

    if perf.tool_failures > 0:
        parts.append(f"{perf.tool_failures} tool failures")

    if perf.prompt_count > 0:
        parts.append(
            f"{perf.prompt_count} prompts → "
            f"{api_calls} calls ({perf.autonomy_ratio:.1f}x)"
        )

    if parts:
        print(f"    perf: {' | '.join(parts)}")


def _print_perf_details(perf: SessionPerf) -> None:
    """Print detailed perf info (--perf flag)."""
    details = []

    if perf.p95_api_latency_ms > 0:
        total_wait_s = perf.total_api_wait_ms / 1000
        details.append(
            f"    latency: p95 {_format_latency(perf.p95_api_latency_ms)}  "
            f"total wait {total_wait_s:.0f}s"
        )

    if perf.error_status_codes:
        codes = " ".join(
            f"{code}:{count}"
            for code, count in sorted(perf.error_status_codes.items())
        )
        details.append(f"    error codes: {codes}")

    if perf.tool_usage:
        top_tools = sorted(
            perf.tool_usage.items(), key=lambda x: x[1], reverse=True
        )[:5]
        tools_str = " ".join(f"{name}:{count}" for name, count in top_tools)
        details.append(f"    tools: {tools_str}")

    for line in details:
        print(line)


def _output_json(
    metrics: CostMetrics,
    sort_key: str,
    errors_only: bool,
    limit: int,
    show_error_codes: bool = False,
    show_health: bool = False,
    session_id: str | None = None,
) -> None:
    """Output session list as JSON."""
    sessions = _sort_sessions(metrics.by_session, sort_key)
    sessions = _filter_sessions(sessions, errors_only, limit, session_id)

    output = {
        "session_count": len(sessions),
        "total_cost": round(metrics.total_cost, 4),
        "total_billable_tokens": metrics.total_billable_tokens,
        "sessions": [
            _session_to_json(s, show_error_codes, show_health)
            for s in sessions
        ],
    }
    emit_one(output, "json")


def _session_to_json(
    s: SessionCost,
    show_error_codes: bool = False,
    show_health: bool = False,
) -> dict[str, object]:
    """Convert a SessionCost to JSON-serializable dict."""
    result: dict = {
        "session_id": s.session_id,
        "first_seen": s.first_seen.isoformat() if s.first_seen else None,
        "last_seen": s.last_seen.isoformat() if s.last_seen else None,
        "duration_minutes": (
            round(s.duration_minutes, 1)
            if s.duration_minutes is not None
            else None
        ),
        "api_calls": s.api_calls,
        "cost": round(s.cost, 4),
        "billable_tokens": s.billable_tokens,
        "input_tokens": s.input_tokens,
        "output_tokens": s.output_tokens,
        "cache_creation_tokens": s.cache_creation_tokens,
        "cache_read_tokens": s.cache_read_tokens,
    }

    if s.perf:
        result["perf"] = {
            "error_count": s.perf.error_count,
            "error_rate": round(s.perf.error_rate, 4),
            "error_status_codes": s.perf.error_status_codes,
            "tool_calls": s.perf.tool_calls,
            "tool_failures": s.perf.tool_failures,
            "tool_failure_rate": round(s.perf.tool_failure_rate, 4),
            "avg_api_latency_ms": round(s.perf.avg_api_latency_ms, 1),
            "p95_api_latency_ms": round(s.perf.p95_api_latency_ms, 1),
            "total_api_wait_ms": round(s.perf.total_api_wait_ms, 1),
            "prompt_count": s.perf.prompt_count,
            "autonomy_ratio": round(s.perf.autonomy_ratio, 1),
            "model_mix": s.perf.model_mix,
            "terminal_type": s.perf.terminal_type,
            "tool_usage": s.perf.tool_usage,
        }

    if show_error_codes and s.perf and s.perf.error_status_codes:
        result["error_codes"] = s.perf.error_status_codes

    if show_health:
        health = calculate_health_score(s)
        result["health"] = {
            "score": health.score,
            "grade": health.grade,
            "error_penalty": health.error_penalty,
            "tool_failure_penalty": health.tool_failure_penalty,
            "latency_penalty": health.latency_penalty,
        }

    return result


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


def _event_to_timeline_entry(event: object) -> dict[str, object]:
    """Convert an OTLPEvent to a timeline entry dict."""
    body = event.body  # type: ignore[union-attr]
    return {
        "timestamp": event.timestamp,  # type: ignore[union-attr]
        "event_type": body,
        "detail": _extract_event_detail(event, body),
    }


def _extract_event_detail(event: object, body: str) -> str:
    """Extract detail string based on event type."""
    if "api_request" in body:
        return _extract_api_request_detail(event)
    if "api_error" in body:
        status = event.get_attr("status_code") or "unknown"  # type: ignore[union-attr]
        return f"status={status}"
    if "tool_result" in body:
        return _extract_tool_result_detail(event)
    if "user_prompt" in body:
        length = event.get_attr("prompt_length") or ""  # type: ignore[union-attr]
        return f"{length} chars" if length else ""
    return ""


def _extract_api_request_detail(event: object) -> str:
    """Extract detail from an api_request event."""
    model = event.get_attr("model") or "unknown"  # type: ignore[union-attr]
    duration = event.get_attr_as_float("duration_ms")  # type: ignore[union-attr]
    tokens = _sum_token_attrs(event)
    return _format_api_request_detail(model, duration, tokens)


def _sum_token_attrs(event: object) -> int:
    """Sum input_tokens and output_tokens from event attributes."""
    total = 0
    for attr in event.attributes:  # type: ignore[union-attr]
        if attr.key in ("input_tokens", "output_tokens"):
            try:
                total += int(float(attr.value.as_str()))
            except (ValueError, TypeError):
                pass
    return total


def _extract_tool_result_detail(event: object) -> str:
    """Extract detail from a tool_result event."""
    tool_name = event.get_attr("tool_name") or "unknown"  # type: ignore[union-attr]
    success = event.get_attr("success")  # type: ignore[union-attr]
    duration = event.get_attr_as_float("duration_ms")  # type: ignore[union-attr]
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
