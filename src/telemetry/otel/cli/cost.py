"""cost subcommand — analyze telemetry costs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.cli_output import OutputWriter, emit_one, emit_rows
from core.pipeline import BaseProducer, RequestConsumer, SafeProcessor
from telemetry.otel.analytics.cost import (
    get_all_costs,
    get_daily_costs,
    get_model_performance,
)
from telemetry.otel.cli._format_helpers import (
    add_format_argument,
    format_duration as _format_duration,
    format_timestamp as _format_timestamp,
    format_validation_error,
    sort_sessions as _sort_sessions,
)
from telemetry.otel.cost_models import CostMetrics
from telemetry.otel.reader import OTLPDataDir
from telemetry.otel.utils import parse_time_window


@dataclass(frozen=True)
class CostScanRequest:
    """Request to scan telemetry cost data."""

    data_dir: OTLPDataDir
    since: datetime | None
    breakdown: str
    sort_key: str
    fmt: str


@dataclass
class CostScanResult:
    """Result of a telemetry cost scan."""

    metrics: CostMetrics


class CostScanProcessor(SafeProcessor[CostScanRequest, CostScanResult]):
    """Load telemetry cost metrics from JSONL data files."""

    def _process_safe(self, payload: CostScanRequest) -> CostScanResult:
        metrics = get_all_costs(data_dir=payload.data_dir, since=payload.since)
        return CostScanResult(metrics=metrics)


class CostScanProducer(BaseProducer):
    """Render telemetry cost output (table or JSON) via OutputWriter."""

    def _produce_success(
        self, payload: CostScanResult, diagnostics: dict[str, Any] | None
    ) -> None:
        # fmt and breakdown are carried via diagnostics from the call site
        fmt = (diagnostics or {}).get("fmt", "table")
        breakdown = (diagnostics or {}).get("breakdown", "none")
        sort_key = (diagnostics or {}).get("sort_key", "time")
        if fmt == "json":
            _output_json(payload.metrics, breakdown, sort_key)
        else:
            _output_table(payload.metrics, breakdown, sort_key, self._writer)


def main(argv: list[str] | None = None) -> int:
    """Analyze telemetry costs."""
    parser = argparse.ArgumentParser(
        prog="telemetry cost",
        description="Analyze telemetry costs with breakdowns",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--breakdown",
        choices=["session", "model", "none"],
        default="none",
        help="Breakdown by session/model or total only (default: none)",
    )
    group.add_argument(
        "--by-date",
        action="store_true",
        help="Show daily cost trends",
    )

    parser.add_argument(
        "--since",
        type=str,
        help="Time range (e.g., '1h', '24h', '7d')",
    )
    parser.add_argument(
        "--sort",
        choices=["cost", "time", "tokens"],
        default="time",
        help="Sort sessions by cost, time (most recent first), or tokens (default: time)",
    )
    parser.add_argument(
        "--perf",
        action="store_true",
        help="Include performance metrics (error rate, latency) with --breakdown model",
    )
    add_format_argument(parser, formats=["table", "json"], default="table")
    parser.add_argument(
        "--data-dir",
        type=str,
        help="Override default data directory",
    )

    args = parser.parse_args(argv)

    if args.by_date:
        return _handle_by_date(args)

    if args.perf and args.breakdown == "model":
        return _handle_model_perf(args)

    if args.data_dir:
        data_dir = OTLPDataDir(path=Path(args.data_dir))
    else:
        data_dir = OTLPDataDir.from_env()

    try:
        since = parse_time_window(args.since)
    except ValueError as e:
        return format_validation_error("--since", str(e))

    request = CostScanRequest(
        data_dir=data_dir,
        since=since,
        breakdown=args.breakdown,
        sort_key=args.sort,
        fmt=args.format,
    )
    writer = OutputWriter()
    producer = CostScanProducer(writer=writer)
    envelope = CostScanProcessor().process(RequestConsumer(request).consume())
    # Pass rendering context via diagnostics so the producer can render correctly
    if envelope.ok():
        producer._produce_success(  # noqa: SLF001 - direct call to pass extra context
            envelope.unwrap(),
            {"fmt": args.format, "breakdown": args.breakdown, "sort_key": args.sort},
        )
        return 0
    producer.produce(envelope)
    return 1


def _load_or_error(loader_fn, empty_msg: str, writer: OutputWriter):
    """Run a data-dir-scoped loader, handling invalid --since consistently.

    Returns (data, exit_code). exit_code is None if the caller should continue
    with the returned data; otherwise it's the exit code to return immediately.
    """
    try:
        data = loader_fn()
    except ValueError as e:
        return None, format_validation_error("--since", str(e))

    if not data:
        writer.print(empty_msg)
        return None, 0

    return data, None


def _handle_by_date(args: argparse.Namespace) -> int:
    """Handle --by-date flag."""
    writer = OutputWriter()
    data_dir = OTLPDataDir(path=Path(args.data_dir)) if args.data_dir else None
    daily, exit_code = _load_or_error(
        lambda: get_daily_costs(data_dir=data_dir, since=args.since),
        "No cost data found",
        writer,
    )
    if exit_code is not None:
        return exit_code

    if args.format == "json":
        _output_daily_json(daily)
    else:
        _output_daily_table(daily, writer)
    return 0


def _output_daily_table(daily: list, writer: OutputWriter | None = None) -> None:
    """Output daily cost summary as table."""
    w = writer or OutputWriter()
    w.print("Daily Cost Summary")
    w.print("─" * 80)
    w.print(f"  {'Date':<12} {'Calls':>8} {'Cost':>10} {'Input':>12} {'Output':>12} {'Cache Read':>12}")
    w.print("─" * 80)
    for d in daily:
        w.print(
            f"  {d.date:<12} {d.api_calls:>8,} {d.cost:>10.4f} "
            f"{d.input_tokens:>12,} {d.output_tokens:>12,} {d.cache_read_tokens:>12,}"
        )
    w.print("─" * 80)
    total_cost = sum(d.cost for d in daily)
    total_calls = sum(d.api_calls for d in daily)
    total_input = sum(d.input_tokens for d in daily)
    total_output = sum(d.output_tokens for d in daily)
    total_cache = sum(d.cache_read_tokens for d in daily)
    w.print(
        f"  {'Total':<12} {total_calls:>8,} {total_cost:>10.4f} "
        f"{total_input:>12,} {total_output:>12,} {total_cache:>12,}"
    )


def _output_daily_json(daily: list) -> None:
    """Output daily cost summary as JSON."""
    rows = [
        {
            "date": d.date,
            "api_calls": d.api_calls,
            "cost": d.cost,
            "input_tokens": d.input_tokens,
            "output_tokens": d.output_tokens,
            "cache_read_tokens": d.cache_read_tokens,
        }
        for d in daily
    ]
    emit_rows(rows, "json")


def _handle_model_perf(args: argparse.Namespace) -> int:
    """Handle --perf --breakdown model."""
    writer = OutputWriter()
    data_dir = OTLPDataDir(path=Path(args.data_dir)) if args.data_dir else None
    perfs, exit_code = _load_or_error(
        lambda: get_model_performance(data_dir=data_dir, since=args.since),
        "No model performance data found",
        writer,
    )
    if exit_code is not None:
        return exit_code

    if args.format == "json":
        _output_model_perf_json(perfs)
    else:
        _output_model_perf_table(perfs, writer)
    return 0


def _output_model_perf_table(perfs: list, writer: OutputWriter | None = None) -> None:
    """Output model performance as table."""
    w = writer or OutputWriter()
    w.print("Model Performance")
    w.print("─" * 100)
    w.print(
        f"  {'Model':<30} {'Calls':>8} {'Cost':>10} "
        f"{'Err%':>8} {'Avg Lat':>10} {'P95 Lat':>10} "
        f"{'Input':>12} {'Output':>12}"
    )
    w.print("─" * 100)
    for mp in perfs:
        w.print(
            f"  {mp.model_name:<30} {mp.api_calls:>8,} ${mp.cost:>9.4f} "
            f"{mp.error_rate * 100:>7.1f}% {mp.avg_latency_ms:>9.0f}ms {mp.p95_latency_ms:>9.0f}ms "
            f"{mp.input_tokens:>12,} {mp.output_tokens:>12,}"
        )


def _output_model_perf_json(perfs: list) -> None:
    """Output model performance as JSON."""
    rows = [
        {
            "model_name": mp.model_name,
            "api_calls": mp.api_calls,
            "error_count": mp.error_count,
            "error_rate": mp.error_rate,
            "avg_latency_ms": mp.avg_latency_ms,
            "p95_latency_ms": mp.p95_latency_ms,
            "cost": mp.cost,
            "input_tokens": mp.input_tokens,
            "output_tokens": mp.output_tokens,
        }
        for mp in perfs
    ]
    emit_rows(rows, "json")


def _output_table(
    metrics: CostMetrics,
    breakdown: str,
    sort_key: str,
    writer: OutputWriter | None = None,
) -> None:
    """Output results as formatted table."""
    w = writer or OutputWriter()
    w.print("Telemetry Cost Summary")
    w.print("─" * 60)
    w.print(f"Input Tokens:          {metrics.total_input_tokens:,}")
    w.print(f"Output Tokens:         {metrics.total_output_tokens:,}")
    w.print(f"Cache Creation:        {metrics.total_cache_creation_tokens:,}")
    w.print(f"Cache Read (FREE):     {metrics.total_cache_read_tokens:,}")
    w.print("")
    w.print(f"Total Billable:        {metrics.total_billable_tokens:,}")
    w.print(f"Total Cost:            ${metrics.total_cost:.2f}")
    w.print("")
    pct = metrics.cache_savings_percent
    savings = metrics.total_cache_savings
    w.print(f"Cache Savings:         ${savings:.2f} ({pct:.1f}%)")
    ratio = metrics.efficiency_ratio
    w.print(f"Efficiency:            {ratio:.2f}x (output/input)")

    if breakdown == "session" and metrics.by_session:
        _print_session_breakdown(metrics, sort_key, w)
    elif breakdown == "model" and metrics.by_model:
        _print_model_breakdown(metrics, w)


def _print_session_breakdown(
    metrics: CostMetrics, sort_key: str, writer: OutputWriter | None = None
) -> None:
    """Print session cost breakdown table."""
    w = writer or OutputWriter()
    w.print("")
    w.print("")
    sessions = _sort_sessions(metrics.by_session, sort_key)
    w.print(f"Sessions ({len(sessions)})")
    w.print("─" * 60)
    total_cost = metrics.total_cost
    for session in sessions:
        pct = (session.cost / total_cost * 100) if total_cost > 0 else 0
        sid = session.session_id
        if len(sid) > 20:
            sid = sid[:8] + "…" + sid[-8:]
        ts_start = _format_timestamp(session.first_seen)
        ts_end = _format_timestamp(session.last_seen)
        dur = _format_duration(session.duration_minutes)
        w.print(f"  {sid}  {ts_start} → {ts_end}  {dur}")
        w.print(
            f"    ${session.cost:.2f} ({pct:.1f}%)  |  "
            f"{session.api_calls:,} calls  |  "
            f"{session.billable_tokens:,} tokens"
        )


def _print_model_breakdown(
    metrics: CostMetrics, writer: OutputWriter | None = None
) -> None:
    """Print model cost breakdown table."""
    w = writer or OutputWriter()
    w.print("")
    w.print("")
    w.print("Cost by Model")
    w.print("─" * 60)
    total_cost = metrics.total_cost
    for model in metrics.by_model:
        pct = (model.cost / total_cost * 100) if total_cost > 0 else 0
        w.print(f"  {model.model_name}")
        w.print(
            f"    Calls: {model.api_calls:,}  |  "
            f"Cost: ${model.cost:.4f} ({pct:.1f}%)"
        )
        w.print(
            f"    Tokens: {model.billable_tokens:,} billable  |  "
            f"Efficiency: {model.efficiency_ratio:.2f}x"
        )


def _output_json(metrics: CostMetrics, breakdown: str, sort_key: str) -> None:
    """Output results as JSON."""
    output = {
        "total_api_calls": metrics.total_api_calls,
        "total_cost": round(metrics.total_cost, 4),
        "total_cache_savings": round(metrics.total_cache_savings, 4),
        "cache_savings_percent": round(metrics.cache_savings_percent, 1),
        "efficiency_ratio": round(metrics.efficiency_ratio, 2),
        "tokens": {
            "input": metrics.total_input_tokens,
            "output": metrics.total_output_tokens,
            "cache_creation": metrics.total_cache_creation_tokens,
            "cache_read": metrics.total_cache_read_tokens,
            "billable_total": metrics.total_billable_tokens,
        },
    }

    if breakdown == "session":
        output["by_session"] = _session_breakdown(metrics, sort_key)
    elif breakdown == "model":
        output["by_model"] = _model_breakdown(metrics)

    emit_one(output, "json")


def _session_breakdown(metrics: CostMetrics, sort_key: str) -> list[dict]:
    """Build session breakdown for JSON output."""
    sessions = _sort_sessions(metrics.by_session, sort_key)
    return [
        {
            "session_id": s.session_id,
            "first_seen": s.first_seen.isoformat() if s.first_seen else None,
            "last_seen": s.last_seen.isoformat() if s.last_seen else None,
            "duration_minutes": round(s.duration_minutes, 1) if s.duration_minutes is not None else None,
            "api_calls": s.api_calls,
            "input_tokens": s.input_tokens,
            "output_tokens": s.output_tokens,
            "cache_creation_tokens": s.cache_creation_tokens,
            "cache_read_tokens": s.cache_read_tokens,
            "billable_tokens": s.billable_tokens,
            "cost": round(s.cost, 4),
            "cost_percent": round(
                (s.cost / metrics.total_cost * 100)
                if metrics.total_cost > 0
                else 0,
                1,
            ),
            "efficiency_ratio": round(s.efficiency_ratio, 2),
        }
        for s in sessions
    ]


def _model_breakdown(metrics: CostMetrics) -> list[dict]:
    """Build model breakdown for JSON output."""
    return [
        {
            "model_name": m.model_name,
            "api_calls": m.api_calls,
            "input_tokens": m.input_tokens,
            "output_tokens": m.output_tokens,
            "cache_creation_tokens": m.cache_creation_tokens,
            "cache_read_tokens": m.cache_read_tokens,
            "cost": round(m.cost, 4),
            "cost_percent": round(
                (m.cost / metrics.total_cost * 100)
                if metrics.total_cost > 0
                else 0,
                1,
            ),
            "efficiency_ratio": round(m.efficiency_ratio, 2),
        }
        for m in metrics.by_model
    ]
