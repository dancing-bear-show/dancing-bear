"""Mermaid diagram CLI — generate .mmd from telemetry and repo data."""

from __future__ import annotations

import argparse
from typing import Optional

from .mermaid import GanttBuilder, PieBuilder

DAYS_HELP = "Lookback days (default: 7)"
NO_SESSIONS = "No sessions found."


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _load_telemetry(days: int):
    """Load session stats and helpers from the telemetry module."""
    from telemetry.parser import iter_session_files, parse_session
    from telemetry.pricing import compute_cost, model_tier
    from datetime import datetime, timezone

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
    return compute_cost(
        s.input_tokens, s.output_tokens,
        s.cache_read_tokens, s.cache_create_tokens, s.model,
    )


# ── Diagram renderers ────────────────────────────────────────────────


def _render_cost_pie(sessions, days, compute_cost, model_tier) -> str:
    tier_cost = {"opus": 0.0, "sonnet": 0.0, "haiku": 0.0}
    for s in sessions:
        if s.model:
            tier_cost[model_tier(s.model)] += _session_cost(s, compute_cost)
    pie = PieBuilder(f"Cost by Model (last {days}d)")
    for tier, cost in tier_cost.items():
        if cost > 0:
            pie.slice(f"{tier.title()} ${cost:.2f}", round(cost, 2))
    return pie.render()


def _render_token_pie(sessions, days, model_tier) -> str:
    tier_tokens = {"opus": 0, "sonnet": 0, "haiku": 0}
    for s in sessions:
        if s.model:
            tier_tokens[model_tier(s.model)] += s.total_tokens
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
            dur = max(1, int(s.duration_seconds / 60))
            tasks.append(f"{sid} ({tier} ${cost:.0f}) :t{sid[:8]}, {start}, {dur}m")
        gantt.section(date_key, tasks)
    return gantt.render()


# ── Commands ──────────────────────────────────────────────────────────


def cmd_telemetry(args) -> int:
    sessions, compute_cost, model_tier = _load_telemetry(args.days)
    if not sessions:
        print(NO_SESSIONS)
        return 1

    renderers = {
        "cost-pie": lambda: _render_cost_pie(sessions, args.days, compute_cost, model_tier),
        "token-pie": lambda: _render_token_pie(sessions, args.days, model_tier),
        "timeline": lambda: _render_timeline(sessions, args.days, compute_cost, model_tier),
    }
    renderer = renderers.get(args.type)
    if not renderer:
        print(f"Unknown diagram type: {args.type}")
        return 1
    print(renderer())
    return 0


# ── Entry point ───────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="diagrams",
        description="Mermaid diagram generation",
    )
    sub = parser.add_subparsers(dest="command")

    p_tel = sub.add_parser("telemetry", help="Telemetry diagrams (cost, tokens, timeline)")
    p_tel.add_argument("type", choices=["cost-pie", "token-pie", "timeline"],
                       help="Diagram type")
    p_tel.add_argument("-d", "--days", type=int, default=7, help=DAYS_HELP)

    args = parser.parse_args(argv)

    commands = {
        "telemetry": cmd_telemetry,
    }
    handler = commands.get(args.command)
    if handler:
        return handler(args)
    parser.print_help()
    return 0
