"""Claude Code telemetry CLI — history, summary, cost."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Optional

from .parser import SessionStats, iter_session_files, parse_session
from .pricing import compute_cost, model_tier


def _session_cost(s: SessionStats) -> float:
    if not s.model:
        return 0.0
    return compute_cost(s.input_tokens, s.output_tokens,
                        s.cache_read_tokens, s.cache_create_tokens, s.model)


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _load_sessions(days: int) -> list[SessionStats]:
    sessions = []
    for path in iter_session_files(days=days):
        s = parse_session(path)
        if s.events > 0:
            sessions.append(s)
    sessions.sort(key=lambda s: s.start_time or datetime.min.replace(tzinfo=timezone.utc),
                  reverse=True)
    return sessions


# ── Commands ──────────────────────────────────────────────────────────


def cmd_history(args) -> int:
    sessions = _load_sessions(args.days)
    if not sessions:
        print("No sessions found.")
        return 0

    # Header
    print(f"{'SESSION':<44} {'MODEL':<10} {'START':<14} {'EVENTS':>7} {'COST':>9}")
    print("─" * 88)

    for s in sessions:
        sid = s.session_id[:40] + "…" if len(s.session_id) > 40 else s.session_id
        tier = model_tier(s.model) if s.model else "?"
        start = s.start_time.strftime("%m-%d %H:%M") if s.start_time else "?"
        cost = _session_cost(s)
        print(f"{sid:<44} {tier:<10} {start:<14} {s.events:>7,} ${cost:>8.2f}")

    total = sum(_session_cost(s) for s in sessions)
    print("─" * 88)
    print(f"{'TOTAL':<44} {'':<10} {'':<14} {sum(s.events for s in sessions):>7,} ${total:>8.2f}")
    return 0


def cmd_summary(args) -> int:
    if args.session:
        # Find by session ID prefix
        sessions = _load_sessions(days=90)
        matches = [s for s in sessions if s.session_id.startswith(args.session)]
        if not matches:
            print(f"No session matching '{args.session}'")
            return 1
        session = matches[0]
    else:
        # Most recently modified
        latest = None
        for path in iter_session_files(days=90):
            if latest is None or path.stat().st_mtime > latest.stat().st_mtime:
                latest = path
        if not latest:
            print("No sessions found.")
            return 1
        session = parse_session(latest)
        if session.events == 0:
            print("Current session has no events.")
            return 1

    cost = _session_cost(session)
    tier = model_tier(session.model) if session.model else "?"
    dur = _format_duration(session.duration_seconds)
    start = session.start_time.strftime("%Y-%m-%d %H:%M") if session.start_time else "?"

    print(f"Session:  {session.session_id}")
    print(f"Model:    {session.model} ({tier})")
    print(f"Start:    {start}")
    print(f"Duration: {dur}")
    print(f"Events:   {session.events:,}")
    print()

    print("── Tokens ──")
    print(f"  Input:        {_format_tokens(session.input_tokens):>10}")
    print(f"  Output:       {_format_tokens(session.output_tokens):>10}")
    print(f"  Cache read:   {_format_tokens(session.cache_read_tokens):>10}")
    print(f"  Cache create: {_format_tokens(session.cache_create_tokens):>10}")
    print(f"  Total:        {_format_tokens(session.total_tokens):>10}")
    print()

    print(f"── Cost: ${cost:.2f} ──")
    if session.model:
        from .pricing import PRICING
        r = PRICING[tier]
        print(f"  Input:        ${session.input_tokens * r['input'] / 1_000_000:>8.2f}")
        print(f"  Output:       ${session.output_tokens * r['output'] / 1_000_000:>8.2f}")
        print(f"  Cache read:   ${session.cache_read_tokens * r['cache_read'] / 1_000_000:>8.2f}")
        print(f"  Cache create: ${session.cache_create_tokens * r['cache_create'] / 1_000_000:>8.2f}")
    print()

    if session.tool_counts:
        print("── Top Tools ──")
        sorted_tools = sorted(session.tool_counts.items(), key=lambda x: x[1], reverse=True)
        for name, count in sorted_tools[:10]:
            print(f"  {name:<30} {count:>6,}")

    return 0


def cmd_cost(args) -> int:
    sessions = _load_sessions(args.days)
    if not sessions:
        print("No sessions found.")
        return 0

    # Aggregate by date and tier
    daily: dict[str, dict[str, int]] = {}  # date -> tier -> total tokens
    daily_cost: dict[str, float] = {}

    for s in sessions:
        if not s.start_time or not s.model:
            continue
        date_key = s.start_time.strftime("%Y-%m-%d")
        tier = model_tier(s.model)
        cost = _session_cost(s)

        if date_key not in daily:
            daily[date_key] = {"opus": 0, "sonnet": 0, "haiku": 0}
            daily_cost[date_key] = 0.0

        daily[date_key][tier] += s.total_tokens
        daily_cost[date_key] += cost

    if not daily:
        print("No sessions with model data found.")
        return 0

    print(f"{'Date':<12} {'Opus':>10} {'Sonnet':>10} {'Haiku':>10} {'Cost':>10}")
    print("─" * 56)

    total_cost = 0.0
    for date_key in sorted(daily.keys(), reverse=True):
        tiers = daily[date_key]
        cost = daily_cost[date_key]
        total_cost += cost
        print(f"{date_key:<12} "
              f"{_format_tokens(tiers['opus']):>10} "
              f"{_format_tokens(tiers['sonnet']):>10} "
              f"{_format_tokens(tiers['haiku']):>10} "
              f"${cost:>9.2f}")

    print("─" * 56)
    print(f"{'TOTAL':<12} {'':<10} {'':<10} {'':<10} ${total_cost:>9.2f}")
    return 0


# ── Entry point ───────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="telemetry",
        description="Claude Code session telemetry",
    )
    sub = parser.add_subparsers(dest="command")

    p_hist = sub.add_parser("history", help="List recent sessions")
    p_hist.add_argument("-d", "--days", type=int, default=7, help="Lookback days (default: 7)")

    p_sum = sub.add_parser("summary", help="Session detail summary")
    p_sum.add_argument("--session", help="Session ID (prefix match); default: current")

    p_cost = sub.add_parser("cost", help="Daily cost breakdown")
    p_cost.add_argument("-d", "--days", type=int, default=7, help="Lookback days (default: 7)")

    args = parser.parse_args(argv)

    if args.command == "history":
        return cmd_history(args)
    elif args.command == "summary":
        return cmd_summary(args)
    elif args.command == "cost":
        return cmd_cost(args)
    else:
        parser.print_help()
        return 0
