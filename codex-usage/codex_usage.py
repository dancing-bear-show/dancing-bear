#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import json
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


HOME = Path.home()
CODEX_SESSIONS = HOME / ".codex" / "sessions"
CODEX_HISTORY = HOME / ".codex" / "history.jsonl"
CODEX_LOG = HOME / ".codex" / "log" / "codex-tui.log"


# -------------------- Cost estimation --------------------
def _default_rates() -> Dict[str, object]:
    # Example defaults (USD per 1K tokens). Adjust for your provider/models.
    return {
        "currency": "USD",
        "per_1k": {
            "input": 0.0050,
            "cached_input": 0.0010,
            "output": 0.0150,
            "reasoning": 0.0300,
        },
    }


def load_rates(path: Optional[str], overrides: Dict[str, Optional[float]]) -> Dict[str, object]:
    cfg = _default_rates()
    # Load from JSON if provided
    if path:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                user_cfg = json.load(f)
            # Merge shallowly
            if isinstance(user_cfg, dict):
                if 'currency' in user_cfg:
                    cfg['currency'] = user_cfg['currency']
                if 'per_1k' in user_cfg and isinstance(user_cfg['per_1k'], dict):
                    cfg['per_1k'].update(user_cfg['per_1k'])
        except Exception:
            pass  # nosec B110 - config load failure
    # Apply CLI overrides (per 1K tokens)
    for key, val in overrides.items():
        if val is not None:
            cfg['per_1k'][key] = float(val)
    return cfg


def estimate_cost_from_totals(tokens: Dict[str, int], rates: Dict[str, object]) -> Dict[str, float]:
    per = rates.get('per_1k', {})
    # Separate non-cached input from cached portion
    input_total = int(tokens.get('input_tokens', 0))
    cached = int(tokens.get('cached_input_tokens', 0))
    noncached = max(input_total - cached, 0)
    output = int(tokens.get('output_tokens', 0))
    reasoning = int(tokens.get('reasoning_output_tokens', 0))

    def cost(tok: int, rate: float) -> float:
        return (tok / 1000.0) * float(rate)

    # Defaults: if a specific rate is missing, fall back sensibly
    # - cached_input falls back to input rate if no discount
    # - reasoning tokens are billed as output tokens if no separate rate is defined
    c_in = cost(noncached, float(per.get('input', 0.0)))
    c_cached = cost(cached, float(per.get('cached_input', per.get('input', 0.0))))
    c_out = cost(output, float(per.get('output', 0.0)))
    c_reason = cost(reasoning, float(per.get('reasoning', per.get('output', 0.0))))
    total = c_in + c_cached + c_out + c_reason
    return {
        'cost_input': c_in,
        'cost_cached_input': c_cached,
        'cost_output': c_out,
        'cost_reasoning': c_reason,
        'cost_total': total,
        'currency': rates.get('currency', 'USD'),
        'noncached_input_tokens': noncached,
    }


def load_model_rate_table(path: Optional[str]) -> Dict[str, Dict[str, float]]:
    """Load model->per_1k rates mapping from JSON.
    File format:
      {
        "currency": "USD",
        "default": {"input": 0.005, "cached_input": 0.001, "output": 0.015, "reasoning": 0.030},
        "models": {"gpt-4o": {"input": 0.005, "output": 0.015}},
        "aliases": {"gpt-4o-2024-08-06": "gpt-4o"}
      }
    """
    table: Dict[str, Dict[str, float]] = {}
    currency = 'USD'
    default = {
        'input': 0.0050,
        'cached_input': 0.0010,
        'output': 0.0150,
        'reasoning': 0.0300,
    }
    if path:
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                cfg = json.load(fh)
            currency = cfg.get('currency', currency)
            if isinstance(cfg.get('default'), dict):
                default.update(cfg['default'])
            models = cfg.get('models') or {}
            aliases = cfg.get('aliases') or {}
            for k, v in models.items():
                if isinstance(v, dict):
                    table[k] = {
                        'input': float(v.get('input', default['input'])),
                        'cached_input': float(v.get('cached_input', default['cached_input'])),
                        'output': float(v.get('output', default['output'])),
                        'reasoning': float(v.get('reasoning', default['reasoning'])),
                    }
            for alias, target in aliases.items():
                if target in table:
                    table[alias] = dict(table[target])
        except Exception:
            pass  # nosec B110 - alias config failure
    table['__currency__'] = {'currency': currency}
    table['__default__'] = default
    return table


def pick_rates_for_model(model: Optional[str], model_table: Dict[str, Dict[str, float]]) -> Dict[str, object]:
    cur = model_table.get('__currency__', {}).get('currency', 'USD')
    base = model_table.get('__default__', {'input':0.005,'cached_input':0.001,'output':0.015,'reasoning':0.030})
    per = None
    if model and model in model_table:
        per = model_table[model]
    else:
        if model:
            for key, v in model_table.items():
                if key.startswith('__'):
                    continue
                if model.startswith(key):
                    per = v
                    break
    if per is None:
        per = base
    return {'currency': cur, 'per_1k': per}


def aggregate_totals(start: Optional[dt.datetime], end: Optional[dt.datetime]) -> Dict[str, int]:
    agg = defaultdict(int)
    for _, ev, _ in iter_token_count_events(CODEX_SESSIONS, start=start, end=end):
        for k, v in ev.items():
            agg[k] += int(v or 0)
    return dict(agg)


def parse_iso8601_z(ts: str) -> dt.datetime:
    """Parse timestamps like 2025-11-04T17:49:24.639Z into aware UTC datetimes.
    Falls back to naive UTC if timezone info missing.
    """
    # Normalize trailing Z with optional fractional seconds
    # Replace 'Z' with '+00:00' for fromisoformat
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(ts)
        if d.tzinfo is None:
            return d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        # Last resort: try parsing without fractional seconds
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?Z$", ts)
        if m:
            base = m.group(1)
            return dt.datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
        raise


def iter_session_files(root: Path) -> Iterator[Path]:
    if not root.exists():
        return
    for p in root.rglob("*.jsonl"):
        # Only files under YYYY/MM/DD folders
        try:
            _ = int(p.parts[-4])  # year
            _ = int(p.parts[-3])  # month
            _ = int(p.parts[-2])  # day
        except Exception:
            pass  # nosec B110 - path validation
        yield p


class TokenEvent(Tuple[dt.datetime, Dict[str, int], Path]):
    pass


def iter_token_count_events(root: Path, start: Optional[dt.datetime] = None, end: Optional[dt.datetime] = None) -> Iterator[Tuple[dt.datetime, Dict[str, int], Path]]:
    """Yield (timestamp_utc, last_token_usage_dict, source_file) for token_count events."""
    for f in iter_session_files(root):
        try:
            with f.open('r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    if 'token_count' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if obj.get('type') != 'event_msg':
                        continue
                    payload = obj.get('payload') or {}
                    if payload.get('type') != 'token_count':
                        continue
                    ts_s = obj.get('timestamp')
                    if not ts_s:
                        continue
                    try:
                        ts = parse_iso8601_z(ts_s)
                    except Exception:
                        continue
                    if start and ts < start:
                        continue
                    if end and ts >= end:
                        continue
                    info = payload.get('info') or {}
                    last = info.get('last_token_usage') or {}
                    # Normalize ints; default 0
                    ev = {
                        'input_tokens': int(last.get('input_tokens') or 0),
                        'cached_input_tokens': int(last.get('cached_input_tokens') or 0),
                        'output_tokens': int(last.get('output_tokens') or 0),
                        'reasoning_output_tokens': int(last.get('reasoning_output_tokens') or 0),
                        'total_tokens': int(last.get('total_tokens') or 0),
                    }
                    yield (ts, ev, f)
        except Exception:
            # Ignore unreadable files
            continue


def iter_token_count_events_with_model(root: Path, start: Optional[dt.datetime] = None, end: Optional[dt.datetime] = None) -> Iterator[Tuple[dt.datetime, Dict[str, int], Path, Optional[str]]]:
    """Yield (timestamp_utc, last_token_usage_dict, source_file, model) for token_count events.
    Tracks the most recently seen "model" value within the same session file and associates it to following token_count events.
    """
    model_re = re.compile(r"\"model\"\s*:\s*\"([^\"]+)\"")
    for f in iter_session_files(root):
        try:
            cur_model: Optional[str] = None
            with f.open('r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    m = model_re.search(line)
                    if m:
                        cur_model = m.group(1)
                    if 'token_count' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if obj.get('type') != 'event_msg':
                        continue
                    payload = obj.get('payload') or {}
                    if payload.get('type') != 'token_count':
                        continue
                    ts_s = obj.get('timestamp')
                    if not ts_s:
                        continue
                    try:
                        ts = parse_iso8601_z(ts_s)
                    except Exception:
                        continue
                    if start and ts < start:
                        continue
                    if end and ts >= end:
                        continue
                    info = payload.get('info') or {}
                    last = info.get('last_token_usage') or {}
                    ev = {
                        'input_tokens': int(last.get('input_tokens') or 0),
                        'cached_input_tokens': int(last.get('cached_input_tokens') or 0),
                        'output_tokens': int(last.get('output_tokens') or 0),
                        'reasoning_output_tokens': int(last.get('reasoning_output_tokens') or 0),
                        'total_tokens': int(last.get('total_tokens') or 0),
                    }
                    yield (ts, ev, f, cur_model)
        except Exception:
            # Ignore unreadable files
            continue


def sum_events(events: Iterable[Dict[str, int]]) -> Dict[str, int]:
    out = defaultdict(int)
    for e in events:
        for k, v in e.items():
            out[k] += int(v or 0)
    return dict(out)


def summarize_window(hours: Optional[int]) -> Dict[str, int]:
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(hours=hours) if hours else None
    events = [e for _, e, _ in iter_token_count_events(CODEX_SESSIONS, start=start, end=None)]
    return sum_events(events)


def rollup_daily(start_date: dt.date, end_date: dt.date) -> List[Dict[str, object]]:
    """Compute daily rollups inclusive of start_date and end_date (UTC days)."""
    # Pre-scan token events once
    start_dt = dt.datetime.combine(start_date, dt.time.min, tzinfo=dt.timezone.utc)
    end_dt = dt.datetime.combine(end_date + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc)

    per_day_tokens: Dict[dt.date, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_day_sessions: Dict[dt.date, set] = defaultdict(set)

    for ts, ev, src in iter_token_count_events(CODEX_SESSIONS, start=start_dt, end=end_dt):
        d = ts.date()
        for k, v in ev.items():
            per_day_tokens[d][k] += v
        per_day_sessions[d].add(src)

    # Prompt counts from history.jsonl
    per_day_prompts: Counter = Counter()
    if CODEX_HISTORY.exists():
        try:
            with CODEX_HISTORY.open('r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    ts_val = obj.get('ts')
                    if not isinstance(ts_val, (int, float)):
                        continue
                    t = dt.datetime.fromtimestamp(float(ts_val), tz=dt.timezone.utc)
                    if start_dt <= t < end_dt:
                        per_day_prompts[t.date()] += 1
        except Exception:
            pass  # nosec B110 - log parse failure

    # ToolCall counts from codex-tui.log (best-effort)
    per_day_toolcalls: Counter = Counter()
    if CODEX_LOG.exists():
        # Timestamp pattern: 2025-11-04T19:14:54.932769Z (strip ANSI if present)
        ts_re = re.compile(r"(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}:\d{2}")
        try:
            with CODEX_LOG.open('r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    if 'ToolCall:' not in line:
                        continue
                    m = ts_re.search(line)
                    if not m:
                        continue
                    day_s = m.group(1)
                    try:
                        day = dt.datetime.strptime(day_s, "%Y-%m-%d").date()
                    except Exception:
                        continue
                    if start_date <= day <= end_date:
                        per_day_toolcalls[day] += 1
        except Exception:
            pass  # nosec B110 - log parse failure

    # Build rows
    rows: List[Dict[str, object]] = []
    d = start_date
    while d <= end_date:
        tokens = per_day_tokens.get(d, {})
        rows.append({
            'date': d.isoformat(),
            'input_tokens': int(tokens.get('input_tokens', 0)),
            'cached_input_tokens': int(tokens.get('cached_input_tokens', 0)),
            'output_tokens': int(tokens.get('output_tokens', 0)),
            'reasoning_output_tokens': int(tokens.get('reasoning_output_tokens', 0)),
            'total_tokens': int(tokens.get('total_tokens', 0)),
            'prompts': int(per_day_prompts.get(d, 0)),
            'tool_calls': int(per_day_toolcalls.get(d, 0)),
            'sessions': int(len(per_day_sessions.get(d, set()))),
        })
        d += dt.timedelta(days=1)
    return rows


def export_csv(rows: List[Dict[str, object]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        'date', 'input_tokens', 'cached_input_tokens', 'output_tokens',
        'reasoning_output_tokens', 'total_tokens', 'prompts', 'tool_calls', 'sessions'
    ]
    with out_path.open('w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def humanize(n: int) -> str:
    # Format large integers with suffixes for readability
    for unit in ["", "K", "M", "B", "T"]:
        if abs(n) < 1000:
            return f"{n}{unit}"
        n = n // 1000
    return f"{n}P"


def cmd_summarize(args: argparse.Namespace) -> int:
    hours = None
    if args.since:
        m = re.match(r"^(\d+)([hd])$", args.since)
        if not m:
            print("--since must be like 24h or 7d", file=sys.stderr)
            return 2
        val, unit = int(m.group(1)), m.group(2)
        hours = val * (24 if unit == 'd' else 1)

    totals = summarize_window(hours)
    print("Window:", f"last {args.since}" if args.since else "all time (sessions store)")
    for k in [
        'input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens'
    ]:
        v = int(totals.get(k, 0))
        print(f"{k:24s} {v:12d} (~{humanize(v)})")
    return 0


def cmd_export_daily(args: argparse.Namespace) -> int:
    try:
        start_date = dt.date.fromisoformat(args.start)
        end_date = dt.date.fromisoformat(args.end)
    except Exception:
        print("--start/--end must be YYYY-MM-DD", file=sys.stderr)
        return 2
    if end_date < start_date:
        print("--end must be on/after --start", file=sys.stderr)
        return 2
    rows = rollup_daily(start_date, end_date)
    export_csv(rows, Path(args.out))
    print(f"Wrote {len(rows)} rows to {args.out}")
    return 0


def cmd_top_calls(args: argparse.Namespace) -> int:
    # Determine time window
    hours = 24
    if args.since:
        m = re.match(r"^(\d+)([hd])$", args.since)
        if not m:
            print("--since must be like 24h or 7d", file=sys.stderr)
            return 2
        val, unit = int(m.group(1)), m.group(2)
        hours = val * (24 if unit == 'd' else 1)
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(hours=hours)

    # Collect events
    evs: List[Tuple[dt.datetime, Dict[str, int], Path]] = list(iter_token_count_events(CODEX_SESSIONS, start=start, end=None))
    evs.sort(key=lambda t: t[1].get('total_tokens', 0), reverse=True)
    for ts, e, src in evs[: args.limit]:
        print(f"{ts.isoformat()}Z\t{e.get('total_tokens',0):>8d}\t{src}")
    return 0


def _parse_since_window(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    m = re.match(r"^(\d+)([hdw])$", s)
    if not m:
        return None
    n = int(m.group(1)); unit = m.group(2)
    if unit == 'h':
        return n
    if unit == 'd':
        return n * 24
    if unit == 'w':
        return n * 24 * 7
    return None


def cmd_estimate_cost(args: argparse.Namespace) -> int:
    # Determine window
    start = end = None
    if args.since:
        hours = _parse_since_window(args.since)
        if hours is None:
            print("--since must be like 24h, 7d, or 4w", file=sys.stderr)
            return 2
        end = dt.datetime.now(dt.timezone.utc)
        start = end - dt.timedelta(hours=hours)
    else:
        if not (args.start and args.end):
            print("Provide --since or both --start and --end", file=sys.stderr)
            return 2
        try:
            start = dt.datetime.fromisoformat(args.start).replace(tzinfo=dt.timezone.utc)
            end = dt.datetime.fromisoformat(args.end).replace(tzinfo=dt.timezone.utc)
        except Exception:
            print("--start/--end must be ISO8601 date-time (e.g., 2025-11-01T00:00:00)", file=sys.stderr)
            return 2

    totals = aggregate_totals(start, end)
    rates = load_rates(args.rates, {
        'input': args.r_in,
        'cached_input': args.r_cached,
        'output': args.r_out,
        'reasoning': args.r_reason,
    })
    cost = estimate_cost_from_totals(totals, rates)
    cur = cost['currency']

    noncached = cost['noncached_input_tokens']
    print(f"Window: {args.since or (args.start + ' to ' + args.end)}")
    print("Tokens (sum):")
    print(f"  input_noncached: {noncached}")
    print(f"  input_cached:    {totals.get('cached_input_tokens',0)}")
    print(f"  output:          {totals.get('output_tokens',0)}")
    print(f"  reasoning:       {totals.get('reasoning_output_tokens',0)}")
    print(f"  total_tokens:    {totals.get('total_tokens',0)}")
    print("Cost (per 1K tokens rates):")
    per = rates['per_1k']
    print(f"  rates: input={per.get('input')} {cur}/1K, cached={per.get('cached_input')} {cur}/1K, output={per.get('output')} {cur}/1K, reasoning={per.get('reasoning')} {cur}/1K")
    print("Cost breakdown:")
    print(f"  input:     {cur} {cost['cost_input']:.2f}")
    print(f"  cached:    {cur} {cost['cost_cached_input']:.2f}")
    print(f"  output:    {cur} {cost['cost_output']:.2f}")
    print(f"  reasoning: {cur} {cost['cost_reasoning']:.2f}")
    print(f"  TOTAL:     {cur} {cost['cost_total']:.2f}")
    # Optional average per day
    if args.average:
        if start and end:
            days = max(1, int((end - start).total_seconds() // 86400))
            print(f"  AVG/DAY:  {cur} {cost['cost_total']/days:.2f}")
    return 0


def cmd_export_daily_cost(args: argparse.Namespace) -> int:
    try:
        start_date = dt.date.fromisoformat(args.start)
        end_date = dt.date.fromisoformat(args.end)
    except Exception:
        print("--start/--end must be YYYY-MM-DD", file=sys.stderr)
        return 2
    rows = rollup_daily(start_date, end_date)
    rates = load_rates(args.rates, {
        'input': args.r_in,
        'cached_input': args.r_cached,
        'output': args.r_out,
        'reasoning': args.r_reason,
    })
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        'date', 'input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens',
        'cost_input', 'cost_cached_input', 'cost_output', 'cost_reasoning', 'cost_total', 'currency'
    ]
    with out_path.open('w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            tokens = {
                'input_tokens': int(r.get('input_tokens',0)),
                'cached_input_tokens': int(r.get('cached_input_tokens',0)),
                'output_tokens': int(r.get('output_tokens',0)),
                'reasoning_output_tokens': int(r.get('reasoning_output_tokens',0)),
                'total_tokens': int(r.get('total_tokens',0)),
            }
            c = estimate_cost_from_totals(tokens, rates)
            w.writerow({
                'date': r['date'],
                **tokens,
                'cost_input': f"{c['cost_input']:.6f}",
                'cost_cached_input': f"{c['cost_cached_input']:.6f}",
                'cost_output': f"{c['cost_output']:.6f}",
                'cost_reasoning': f"{c['cost_reasoning']:.6f}",
                'cost_total': f"{c['cost_total']:.6f}",
                'currency': c['currency'],
            })
    print(f"Wrote daily cost to {out_path}")
    return 0


def cmd_estimate_cost_by_model(args: argparse.Namespace) -> int:
    # Determine window
    start = end = None
    if args.since:
        hours = _parse_since_window(args.since)
        if hours is None:
            print("--since must be like 24h, 7d, or 4w", file=sys.stderr)
            return 2
        end = dt.datetime.now(dt.timezone.utc)
        start = end - dt.timedelta(hours=hours)
    else:
        if not (args.start and args.end):
            print("Provide --since or both --start and --end", file=sys.stderr)
            return 2
        try:
            start = dt.datetime.fromisoformat(args.start).replace(tzinfo=dt.timezone.utc)
            end = dt.datetime.fromisoformat(args.end).replace(tzinfo=dt.timezone.utc)
        except Exception:
            print("--start/--end must be ISO8601 date-time (e.g., 2025-11-01T00:00:00)", file=sys.stderr)
            return 2

    rates_table = load_model_rate_table(args.rates_models)
    currency = rates_table.get('__currency__', {}).get('currency', 'USD')
    # Aggregate per model
    per_model: Dict[str, Dict[str, int]] = {}
    for ts, ev, src, model in iter_token_count_events_with_model(CODEX_SESSIONS, start=start, end=end):
        key = model or 'unknown'
        slot = per_model.setdefault(key, {'input_tokens':0,'cached_input_tokens':0,'output_tokens':0,'reasoning_output_tokens':0,'total_tokens':0})
        for k, v in ev.items():
            slot[k] += int(v or 0)
    # Print breakdown
    grand = 0.0
    print(f"Window: {args.since or (args.start + ' to ' + args.end)}")
    print("model\tinput\tcached\toutput\treasoning\ttotal_tokens\tcost")
    for model, toks in sorted(per_model.items(), key=lambda kv: kv[1].get('total_tokens',0), reverse=True):
        rates = pick_rates_for_model(model if model!='unknown' else None, rates_table)
        c = estimate_cost_from_totals(toks, rates)
        grand += c['cost_total']
        print(f"{model}\t{toks.get('input_tokens',0)}\t{toks.get('cached_input_tokens',0)}\t{toks.get('output_tokens',0)}\t{toks.get('reasoning_output_tokens',0)}\t{toks.get('total_tokens',0)}\t{currency} {c['cost_total']:.2f}")
    print(f"TOTAL\t-\t-\t-\t-\t-\t{currency} {grand:.2f}")
    return 0


def cmd_export_daily_cost_by_model(args: argparse.Namespace) -> int:
    try:
        start_date = dt.date.fromisoformat(args.start)
        end_date = dt.date.fromisoformat(args.end)
    except Exception:
        print("--start/--end must be YYYY-MM-DD", file=sys.stderr)
        return 2
    start_dt = dt.datetime.combine(start_date, dt.time.min, tzinfo=dt.timezone.utc)
    end_dt = dt.datetime.combine(end_date + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc)
    rates_table = load_model_rate_table(args.rates_models)
    currency = rates_table.get('__currency__', {}).get('currency', 'USD')

    per_day_model: Dict[Tuple[dt.date, str], Dict[str, int]] = {}
    for ts, ev, src, model in iter_token_count_events_with_model(CODEX_SESSIONS, start=start_dt, end=end_dt):
        day = ts.date()
        key = (day, model or 'unknown')
        slot = per_day_model.setdefault(key, {'input_tokens':0,'cached_input_tokens':0,'output_tokens':0,'reasoning_output_tokens':0,'total_tokens':0})
        for k, v in ev.items():
            slot[k] += int(v or 0)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ['date','model','input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens','total_tokens','cost_total','currency']
    with out_path.open('w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for (day, model), toks in sorted(per_day_model.items()):
            rates = pick_rates_for_model(model if model!='unknown' else None, rates_table)
            c = estimate_cost_from_totals(toks, rates)
            w.writerow({
                'date': day.isoformat(),
                'model': model,
                **toks,
                'cost_total': f"{c['cost_total']:.6f}",
                'currency': currency,
            })
    print(f"Wrote daily per-model cost to {out_path}")
    return 0


def _iso_year_week(d: dt.date) -> Tuple[int, int]:
    iso = d.isocalendar()
    # py3.11+: has attributes year, week; older: tuple(y,w,wd)
    year = getattr(iso, 'year', iso[0])
    week = getattr(iso, 'week', iso[1])
    return int(year), int(week)


def rollup_weekly(start_date: dt.date, end_date: dt.date) -> List[Dict[str, object]]:
    start_dt = dt.datetime.combine(start_date, dt.time.min, tzinfo=dt.timezone.utc)
    end_dt = dt.datetime.combine(end_date + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc)

    per_week_tokens: Dict[Tuple[int, int], Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_week_sessions: Dict[Tuple[int, int], set] = defaultdict(set)

    for ts, ev, src in iter_token_count_events(CODEX_SESSIONS, start=start_dt, end=end_dt):
        yw = _iso_year_week(ts.date())
        for k, v in ev.items():
            per_week_tokens[yw][k] += v
        per_week_sessions[yw].add(src)

    # Prompts aggregated by ISO week
    per_week_prompts: Counter = Counter()
    if CODEX_HISTORY.exists():
        try:
            with CODEX_HISTORY.open('r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    ts_val = obj.get('ts')
                    if not isinstance(ts_val, (int, float)):
                        continue
                    t = dt.datetime.fromtimestamp(float(ts_val), tz=dt.timezone.utc)
                    if start_dt <= t < end_dt:
                        per_week_prompts[_iso_year_week(t.date())] += 1
        except Exception:
            pass  # nosec B110 - log parse failure

    # ToolCall counts from log
    per_week_toolcalls: Counter = Counter()
    if CODEX_LOG.exists():
        ts_re = re.compile(r"(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}:\d{2}")
        try:
            with CODEX_LOG.open('r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    if 'ToolCall:' not in line:
                        continue
                    m = ts_re.search(line)
                    if not m:
                        continue
                    try:
                        day = dt.datetime.strptime(m.group(1), "%Y-%m-%d").date()
                    except Exception:
                        continue
                    if start_date <= day <= end_date:
                        per_week_toolcalls[_iso_year_week(day)] += 1
        except Exception:
            pass  # nosec B110 - log parse failure

    # Iterate weeks from start_date (aligned to Monday) to end_date
    week_rows: List[Dict[str, object]] = []
    cursor = start_date - dt.timedelta(days=start_date.weekday())  # Monday
    last_day = end_date
    while cursor <= last_day:
        week_start = cursor
        week_end = cursor + dt.timedelta(days=6)
        yw = _iso_year_week(week_start)
        tokens = per_week_tokens.get(yw, {})
        week_rows.append({
            'iso_year': yw[0],
            'iso_week': yw[1],
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'input_tokens': int(tokens.get('input_tokens', 0)),
            'cached_input_tokens': int(tokens.get('cached_input_tokens', 0)),
            'output_tokens': int(tokens.get('output_tokens', 0)),
            'reasoning_output_tokens': int(tokens.get('reasoning_output_tokens', 0)),
            'total_tokens': int(tokens.get('total_tokens', 0)),
            'prompts': int(per_week_prompts.get(yw, 0)),
            'tool_calls': int(per_week_toolcalls.get(yw, 0)),
            'sessions': int(len(per_week_sessions.get(yw, set()))),
        })
        cursor += dt.timedelta(days=7)
    return week_rows


def export_csv_weekly(rows: List[Dict[str, object]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        'iso_year', 'iso_week', 'week_start', 'week_end',
        'input_tokens', 'cached_input_tokens', 'output_tokens',
        'reasoning_output_tokens', 'total_tokens', 'prompts', 'tool_calls', 'sessions'
    ]
    with out_path.open('w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def cmd_export_weekly(args: argparse.Namespace) -> int:
    try:
        start_date = dt.date.fromisoformat(args.start)
        end_date = dt.date.fromisoformat(args.end)
    except Exception:
        print("--start/--end must be YYYY-MM-DD", file=sys.stderr)
        return 2
    if end_date < start_date:
        print("--end must be on/after --start", file=sys.stderr)
        return 2
    rows = rollup_weekly(start_date, end_date)
    export_csv_weekly(rows, Path(args.out))
    print(f"Wrote {len(rows)} rows to {args.out}")
    return 0


def cmd_summarize_weekly(args: argparse.Namespace) -> int:
    # Parse since like 8w
    n_weeks = 8
    if args.since:
        m = re.match(r"^(\d+)w$", args.since)
        if not m:
            print("--since must be like 8w", file=sys.stderr)
            return 2
        n_weeks = int(m.group(1))
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(weeks=n_weeks)
    rows = rollup_weekly(start, today)
    # Compute WoW and 4-week MA
    totals = [r['total_tokens'] for r in rows]
    # Print header summary
    for i, r in enumerate(rows):
        total = r['total_tokens']
        wow = None
        if i > 0:
            prev = totals[i-1]
            wow = ((total - prev) / prev * 100) if prev > 0 else None
        ma4 = None
        if i >= 3:
            ma4 = sum(totals[i-3:i+1]) / 4
        wk = f"{r['iso_year']}-W{int(r['iso_week']):02d}"
        parts = [wk, r['week_start'], r['week_end'], f"total={total}"]
        if wow is not None:
            parts.append(f"WoW={wow:.1f}%")
        if ma4 is not None:
            parts.append(f"MA4={int(ma4)}")
        print(" | ".join(parts))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Codex usage parser")
    sub = p.add_subparsers(dest='cmd', required=True)

    p_sum = sub.add_parser('summarize', help='Summarize tokens in a recent window')
    p_sum.add_argument('--since', default='24h', help='Window like 24h or 7d (default: 24h)')
    p_sum.set_defaults(func=cmd_summarize)

    p_exp = sub.add_parser('export-daily', help='Export per-day CSV over a range')
    p_exp.add_argument('--start', required=True, help='Start date YYYY-MM-DD (UTC)')
    p_exp.add_argument('--end', required=True, help='End date YYYY-MM-DD (UTC)')
    p_exp.add_argument('--out', required=True, help='Output CSV path')
    p_exp.set_defaults(func=cmd_export_daily)

    p_top = sub.add_parser('top-calls', help='List top calls by total tokens')
    p_top.add_argument('--since', default='24h', help='Window like 24h or 7d (default: 24h)')
    p_top.add_argument('--limit', type=int, default=10, help='Max rows (default: 10)')
    p_top.set_defaults(func=cmd_top_calls)

    p_wexp = sub.add_parser('export-weekly', help='Export per-week CSV over a range')
    p_wexp.add_argument('--start', required=True, help='Start date YYYY-MM-DD (UTC)')
    p_wexp.add_argument('--end', required=True, help='End date YYYY-MM-DD (UTC)')
    p_wexp.add_argument('--out', required=True, help='Output CSV path')
    p_wexp.set_defaults(func=cmd_export_weekly)

    p_wsum = sub.add_parser('summarize-weekly', help='Print week-over-week with moving averages')
    p_wsum.add_argument('--since', default='8w', help='Window like 8w (default: 8w)')
    p_wsum.set_defaults(func=cmd_summarize_weekly)

    p_ins = sub.add_parser('insights', help='Derive additional insights over recent days')
    p_ins.add_argument('--days', type=int, default=30, help='Window of days (default: 30)')
    p_ins.set_defaults(func=cmd_insights)

    # Cost estimation
    p_cost = sub.add_parser('estimate-cost', help='Estimate cost over a window')
    p_cost.add_argument('--since', help='Window like 24h, 7d, 4w')
    p_cost.add_argument('--start', help='Start ISO8601 (e.g., 2025-11-01T00:00:00)')
    p_cost.add_argument('--end', help='End ISO8601 (e.g., 2025-11-04T00:00:00)')
    p_cost.add_argument('--rates', help='Rates JSON file with per_1k fields')
    p_cost.add_argument('--r-in', dest='r_in', type=float, help='Override input USD per 1K')
    p_cost.add_argument('--r-cached', dest='r_cached', type=float, help='Override cached input USD per 1K')
    p_cost.add_argument('--r-out', dest='r_out', type=float, help='Override output USD per 1K')
    p_cost.add_argument('--r-reason', dest='r_reason', type=float, help='Override reasoning USD per 1K')
    p_cost.add_argument('--average', action='store_true', help='Also print average per day')
    p_cost.set_defaults(func=cmd_estimate_cost)

    p_costdaily = sub.add_parser('export-daily-cost', help='Export per-day cost CSV')
    p_costdaily.add_argument('--start', required=True, help='Start date YYYY-MM-DD (UTC)')
    p_costdaily.add_argument('--end', required=True, help='End date YYYY-MM-DD (UTC)')
    p_costdaily.add_argument('--out', required=True, help='Output CSV path')
    p_costdaily.add_argument('--rates', help='Rates JSON file with per_1k fields')
    p_costdaily.add_argument('--r-in', dest='r_in', type=float, help='Override input USD per 1K')
    p_costdaily.add_argument('--r-cached', dest='r_cached', type=float, help='Override cached input USD per 1K')
    p_costdaily.add_argument('--r-out', dest='r_out', type=float, help='Override output USD per 1K')
    p_costdaily.add_argument('--r-reason', dest='r_reason', type=float, help='Override reasoning USD per 1K')
    p_costdaily.set_defaults(func=cmd_export_daily_cost)

    # Per-model cost breakdown
    p_cost_m = sub.add_parser('estimate-cost-by-model', help='Estimate cost broken down by model')
    p_cost_m.add_argument('--since', help='Window like 24h, 7d, 4w')
    p_cost_m.add_argument('--start', help='Start ISO8601 (e.g., 2025-11-01T00:00:00)')
    p_cost_m.add_argument('--end', help='End ISO8601 (e.g., 2025-11-04T00:00:00)')
    p_cost_m.add_argument('--rates-models', help='Model rate table JSON (with default/models/aliases)')
    p_cost_m.set_defaults(func=cmd_estimate_cost_by_model)

    p_cost_dm = sub.add_parser('export-daily-cost-by-model', help='Export per-day per-model costs to CSV')
    p_cost_dm.add_argument('--start', required=True, help='Start date YYYY-MM-DD (UTC)')
    p_cost_dm.add_argument('--end', required=True, help='End date YYYY-MM-DD (UTC)')
    p_cost_dm.add_argument('--out', required=True, help='Output CSV path')
    p_cost_dm.add_argument('--rates-models', help='Model rate table JSON (with default/models/aliases)')
    p_cost_dm.set_defaults(func=cmd_export_daily_cost_by_model)

    return p


def cmd_insights(args: argparse.Namespace) -> int:
    # Build last N days rollup ending today (UTC)
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=args.days)
    rows = rollup_daily(start, today)
    if not rows:
        print("No data found.")
        return 0

    # Convert types
    def gi(r,k):
        return int(r.get(k, 0) or 0)
    rows2 = []
    for r in rows:
        rr = dict(r)
        for k in ('input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens','total_tokens','prompts','tool_calls','sessions'):
            rr[k] = gi(r,k)
        rows2.append(rr)

    # Metrics
    import statistics
    import math
    tot = [r['total_tokens'] for r in rows2]
    prom = [r['prompts'] for r in rows2]
    outs = [r['output_tokens'] for r in rows2]
    reas = [r['reasoning_output_tokens'] for r in rows2]
    cache = [r['cached_input_tokens'] for r in rows2]

    def mean(xs): return sum(xs)/len(xs) if xs else 0
    avg = mean(tot)
    std = statistics.pstdev(tot) if len(tot)>1 else 0
    cv = (std/avg) if avg>0 else 0

    sorted_tot = sorted(tot)
    def pct_val(arr, p):
        if not arr:
            return 0
        k = (len(arr)-1)*p
        f = math.floor(k); c = math.ceil(k)
        if f==c: return arr[int(k)]
        return arr[f]*(c-k)+arr[c]*(k-f)
    p50 = pct_val(sorted_tot, 0.5)
    p90 = pct_val(sorted_tot, 0.9)
    p95 = pct_val(sorted_tot, 0.95)

    n = len(rows2)
    k_top = max(1, math.ceil(0.2*n))
    share_top = sum(sorted(tot, reverse=True)[:k_top]) / sum(tot) if sum(tot)>0 else 0

    # Weekday vs weekend share
    weekday_total = weekend_total = 0
    for r in rows2:
        d = dt.date.fromisoformat(r['date'])
        if d.weekday() >= 5:
            weekend_total += r['total_tokens']
        else:
            weekday_total += r['total_tokens']
    weekday_share = (weekday_total/(weekday_total+weekend_total)*100) if (weekday_total+weekend_total)>0 else 0

    # Tokens per prompt (active days with prompts)
    active_idxs = [i for i,t in enumerate(tot) if t>0 and prom[i]>0]
    cpp = [ tot[i]/prom[i] for i in active_idxs ]
    cpp_avg = mean(cpp)
    cpp_p50 = statistics.median(cpp) if cpp else 0
    cpp_p90 = (sorted(cpp)[int(0.9*(len(cpp)-1))] if cpp else 0)

    eff_out_avg = mean([ outs[i]/tot[i] for i in range(n) if tot[i]>0 ])*100 if any(tot) else 0
    eff_reas_avg = mean([ reas[i]/tot[i] for i in range(n) if tot[i]>0 ])*100 if any(tot) else 0
    cache_ratio = (sum(cache)/sum([r['input_tokens'] for r in rows2])*100) if sum([r['input_tokens'] for r in rows2])>0 else 0

    # Trend slope: tokens/day index, convert to % of mean per 7 days
    xs = list(range(n))
    xbar = mean(xs); ybar = mean(tot)
    num = sum((x-xbar)*(y-ybar) for x,y in zip(xs,tot))
    den = sum((x-xbar)**2 for x in xs) or 1
    slope = num/den
    trend_7d_pct = ((slope*7)/avg*100) if avg>0 else 0

    # Print concise insight lines
    print(f"Days={n}, Active={sum(1 for t in tot if t>0)}, Idle={sum(1 for t in tot if t==0)}")
    print(f"Central: avg={int(avg)}, median={int(p50)}, p90={int(p90)}, p95={int(p95)}")
    print(f"Burstiness: CV={cv:.2f}, top20% share={share_top*100:.1f}%")
    print(f"Workload timing: weekday share={weekday_share:.1f}%")
    print(f"Efficiency: cache_ratio={cache_ratio:.2f}%, out%={eff_out_avg:.2f}%, reason%={eff_reas_avg:.2f}%")
    print(f"Prompts: avg/day={mean(prom):.2f}, tokens/prompt avg={int(cpp_avg)}, p50={int(cpp_p50)}, p90={int(cpp_p90)}")
    print(f"Trend: 7d slope={trend_7d_pct:.1f}% of mean per week")
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
