"""Telemetry diagram renderers — cost/token pies and session timeline."""

from __future__ import annotations

from core.format_utils import format_tokens as _format_tokens

from .mermaid import GanttBuilder, PieBuilder


def _load_telemetry(days: int):
    """Load session stats and helpers from the telemetry module."""
    from datetime import datetime, timezone

    from telemetry.parser import iter_session_files, parse_session
    from telemetry.pricing import compute_cost, model_tier

    sessions = []
    for path in iter_session_files(days=days):
        s = parse_session(path)
        if s.events > 0:
            sessions.append(s)
    sessions.sort(
        key=lambda s: s.start_time or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return sessions, compute_cost, model_tier


def _session_cost(s, compute_cost) -> float:
    if not s.model:
        return 0.0
    from telemetry.pricing import TokenMetrics
    return compute_cost(
        TokenMetrics(s.input_tokens, s.output_tokens, s.cache_read_tokens, s.cache_create_tokens),
        s.model,
    )


def _render_cost_pie(sessions, days, compute_cost, model_tier) -> str:
    tier_cost: dict[str, float] = {"opus": 0.0, "sonnet": 0.0, "haiku": 0.0}
    for s in sessions:
        if s.model:
            tier = model_tier(s.model)
            tier_cost[tier] = tier_cost.get(tier, 0.0) + _session_cost(s, compute_cost)
    pie = PieBuilder(f"Cost by Model (last {days}d)")
    for tier, cost in tier_cost.items():
        if cost > 0:
            pie.slice(f"{tier.title()} ${cost:.2f}", round(cost, 2))
    return pie.render()


def _render_token_pie(sessions, days, model_tier) -> str:
    tier_tokens: dict[str, int] = {"opus": 0, "sonnet": 0, "haiku": 0}
    for s in sessions:
        if s.model:
            tier = model_tier(s.model)
            tier_tokens[tier] = tier_tokens.get(tier, 0) + s.total_tokens
    pie = PieBuilder(f"Tokens by Model (last {days}d)")
    for tier, tok in tier_tokens.items():
        if tok > 0:
            pie.slice(f"{tier.title()} {_format_tokens(tok)}", tok)
    return pie.render()


def _render_timeline(sessions, days, compute_cost, model_tier) -> str:
    gantt = GanttBuilder(f"Sessions (last {days}d)", date_format="YYYY-MM-DD")
    by_date: dict[str, list] = {}
    for s in sessions:
        if s.start_time:
            key = s.start_time.strftime("%Y-%m-%d")
            by_date.setdefault(key, []).append(s)
    for date_key in sorted(by_date.keys()):
        tasks = []
        for s in by_date[date_key]:
            sid = s.session_id[:12]
            tier = model_tier(s.model) if s.model else "?"
            cost = _session_cost(s, compute_cost)
            start = s.start_time.strftime("%Y-%m-%d") if s.start_time else date_key
            dur_days = max(1, round(s.duration_seconds / 86400))
            safe_id = "".join(c for c in sid if c.isalnum() or c == "_")[:8]
            tasks.append(f"{sid} ({tier} ${cost:.0f}) :t{safe_id}, {start}, {dur_days}d")
        gantt.section(date_key, tasks)
    return gantt.render()
