"""Output formatters for the sessions subcommand.

Extracted from sessions.py to reduce complexity.
"""

from __future__ import annotations

from core.cli_output import emit_one
from telemetry.otel.analytics.cost import CostMetrics
from telemetry.otel.analytics.health_score import calculate_health_score
from telemetry.otel.cli._format_helpers import (
    format_duration as _format_duration,
    format_timestamp as _format_timestamp,
    sort_sessions as _sort_sessions,
)
from telemetry.otel.cost_models import SessionCost, SessionPerf
from telemetry.timeutil import format_latency as _format_latency


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
    from telemetry.otel.cli.sessions import _filter_sessions

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
    from telemetry.otel.cli.sessions import _filter_sessions

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
