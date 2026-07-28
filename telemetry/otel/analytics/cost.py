"""Cost analysis engine for telemetry data.

Aggregates api_request events and calculates costs, cache savings,
and efficiency metrics.

## Updating Model Pricing

To update pricing when Anthropic releases new pricing:

1. Check official pricing at https://platform.claude.com/docs/en/about-claude/pricing
2. Update MODEL_PRICING dict below
3. Update get_model_pricing() for intelligent fallback matching
4. Run validation tests: python3 -m unittest discover tests/ -v

## Pricing Notes

- Base pricing: Listed in MODEL_PRICING
- Long context (4.x models with 1M context): no premium — same price as base
- Prompt caching writes: 1.25x base input price
- Prompt caching reads: 0.1x base input price
- Batch API: 50% discount on all tokens
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from telemetry.otel.analytics.perf import (
    _build_session_perf_objects,
    _calc_p95,
    _extract_all_events,
    _parse_token_attribute,
)
from telemetry.otel.cost_models import DailyCost, ModelPerformance
from telemetry.otel.cost_models import (
    CostMetrics,
    ModelCost,
    SessionCost,
    SessionPerf,
)
from telemetry.otel.models import MetricDataPoint
from telemetry.otel.reader import OTLPDataDir, OTLPReader
from telemetry.otel.utils import parse_time_window

# Re-export perf functions for backward compatibility (tests import from here)
__all__ = [
    "_build_session_perf_objects",
    "_extract_all_events",
    "_parse_token_attribute",
]

# Model pricing (as of Jul 2026 — official Anthropic API pricing)
# Format: (input_cost_per_million, output_cost_per_million)
# Source: https://platform.claude.com/docs/en/about-claude/pricing
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4-1-20250805": (15.0, 75.0),
    # Sonnet 5 introductory pricing through Aug 31, 2026; standard is (3.0, 15.0)
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-4-7-1m": (5.0, 25.0),
    "claude-opus-4-6-1m": (5.0, 25.0),
    "claude-sonnet-4-6-1m": (3.0, 15.0),
    "claude-opus": (5.0, 25.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (1.0, 5.0),
}

DEFAULT_MODEL = "claude-haiku-4-5"


def get_model_pricing(model_name: str) -> tuple[float, float]:
    """Get pricing for a model, with intelligent fallback.

    Args:
        model_name: Model identifier from telemetry events.

    Returns:
        (input_cost_per_million, output_cost_per_million)
    """
    if model_name in MODEL_PRICING:
        return MODEL_PRICING[model_name]

    model_lower = model_name.lower()

    # Check sonnet-5 before generic substring matches — introductory pricing
    if "sonnet-5" in model_lower:
        return MODEL_PRICING["claude-sonnet-5"]

    if "opus" in model_lower and "1m" in model_lower:
        return MODEL_PRICING["claude-opus-4-7-1m"]
    if "sonnet" in model_lower and "1m" in model_lower:
        return MODEL_PRICING["claude-sonnet-4-6-1m"]

    if "mythos" in model_lower:
        return MODEL_PRICING["claude-mythos-5"]
    if "fable" in model_lower:
        return MODEL_PRICING["claude-fable-5"]

    if "opus" in model_lower:
        return MODEL_PRICING["claude-opus"]
    if "sonnet" in model_lower:
        return MODEL_PRICING["claude-sonnet"]
    if "haiku" in model_lower:
        return MODEL_PRICING["claude-haiku"]

    return MODEL_PRICING[DEFAULT_MODEL]


def _extract_api_requests(events: list, since: datetime | None = None) -> list[dict]:
    """Extract api_request events from telemetry and parse token attributes."""
    api_requests, _ = _extract_all_events(events, since)
    return api_requests


def _aggregate_requests_by_key(api_requests: list[dict], key: str) -> dict[str, dict]:
    """Aggregate api_requests by a given key (session_id or model)."""
    aggregated: dict[str, dict] = defaultdict(
        lambda: {
            "api_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }
    )

    for req in api_requests:
        group_key = req[key]
        aggregated[group_key]["api_calls"] += 1
        aggregated[group_key]["input_tokens"] += req["input_tokens"]
        aggregated[group_key]["output_tokens"] += req["output_tokens"]
        aggregated[group_key]["cache_creation_tokens"] += req["cache_creation_tokens"]
        aggregated[group_key]["cache_read_tokens"] += req["cache_read_tokens"]

    return aggregated


def _aggregate_requests_by_session_and_model(
    api_requests: list[dict],
) -> dict[tuple[str, str], dict]:
    """Aggregate api_requests by (session_id, model) for per-model costs."""
    aggregated: dict[tuple[str, str], dict] = defaultdict(
        lambda: {
            "api_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }
    )

    for req in api_requests:
        key = (req["session_id"], req["model"])
        aggregated[key]["api_calls"] += 1
        aggregated[key]["input_tokens"] += req["input_tokens"]
        aggregated[key]["output_tokens"] += req["output_tokens"]
        aggregated[key]["cache_creation_tokens"] += req["cache_creation_tokens"]
        aggregated[key]["cache_read_tokens"] += req["cache_read_tokens"]

    return aggregated


def _calculate_totals(api_requests: list[dict]) -> dict[str, int]:
    """Calculate total token and API call counts."""
    return {
        "api_calls": len(api_requests),
        "input": sum(req["input_tokens"] for req in api_requests),
        "output": sum(req["output_tokens"] for req in api_requests),
        "cache_creation": sum(req["cache_creation_tokens"] for req in api_requests),
        "cache_read": sum(req["cache_read_tokens"] for req in api_requests),
    }


def _build_session_costs(
    session_model_data: dict[tuple[str, str], dict],
    session_timestamps: dict[str, dict] | None = None,
    session_perf: dict[str, SessionPerf] | None = None,
) -> list[SessionCost]:
    """Build SessionCost objects from (session, model) data."""
    session_totals: dict[str, dict] = defaultdict(
        lambda: {
            "api_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cost": 0.0,
        }
    )

    for (session_id, model), data in session_model_data.items():
        input_cost, output_cost = get_model_pricing(model)
        cost = (
            (data["input_tokens"] * input_cost / 1_000_000)
            + (data["output_tokens"] * output_cost / 1_000_000)
            + (data["cache_creation_tokens"] * input_cost * 1.25 / 1_000_000)
            + (data["cache_read_tokens"] * input_cost * 0.1 / 1_000_000)
        )
        st = session_totals[session_id]
        st["api_calls"] += data["api_calls"]
        st["input_tokens"] += data["input_tokens"]
        st["output_tokens"] += data["output_tokens"]
        st["cache_creation_tokens"] += data["cache_creation_tokens"]
        st["cache_read_tokens"] += data["cache_read_tokens"]
        st["cost"] += cost

    timestamps = session_timestamps or {}
    perf_data = session_perf or {}

    session_costs = []
    for session_id, totals in sorted(session_totals.items()):
        eff = (
            (totals["output_tokens"] / totals["input_tokens"])
            if totals["input_tokens"] > 0
            else 0.0
        )
        ts = timestamps.get(session_id, {})
        session_costs.append(
            SessionCost(
                session_id=session_id,
                api_calls=totals["api_calls"],
                input_tokens=totals["input_tokens"],
                output_tokens=totals["output_tokens"],
                cache_creation_tokens=totals["cache_creation_tokens"],
                cache_read_tokens=totals["cache_read_tokens"],
                cost=totals["cost"],
                efficiency_ratio=eff,
                first_seen=ts.get("first_seen"),
                last_seen=ts.get("last_seen"),
                perf=perf_data.get(session_id),
            )
        )
    return session_costs


def _build_model_costs(model_data: dict[str, dict]) -> list[ModelCost]:
    """Build ModelCost objects from aggregated model data."""
    model_costs = []
    for model_name, data in sorted(model_data.items()):
        input_cost, output_cost = get_model_pricing(model_name)
        cost = (
            (data["input_tokens"] * input_cost / 1_000_000)
            + (data["output_tokens"] * output_cost / 1_000_000)
            + (data["cache_creation_tokens"] * input_cost * 1.25 / 1_000_000)
            + (data["cache_read_tokens"] * input_cost * 0.1 / 1_000_000)
        )
        eff = (
            (data["output_tokens"] / data["input_tokens"])
            if data["input_tokens"] > 0
            else 0.0
        )
        model_costs.append(
            ModelCost(
                model_name=model_name,
                api_calls=data["api_calls"],
                input_tokens=data["input_tokens"],
                output_tokens=data["output_tokens"],
                cache_creation_tokens=data["cache_creation_tokens"],
                cache_read_tokens=data["cache_read_tokens"],
                cost=cost,
                efficiency_ratio=eff,
            )
        )
    return model_costs


def _build_session_timestamps(api_requests: list[dict]) -> dict[str, dict]:
    """Build first_seen/last_seen timestamps per session from api_requests."""
    timestamps: dict[str, dict] = {}
    for req in api_requests:
        sid = req["session_id"]
        ts = req["timestamp"]
        if sid not in timestamps:
            timestamps[sid] = {"first_seen": ts, "last_seen": ts}
        else:
            if ts < timestamps[sid]["first_seen"]:
                timestamps[sid]["first_seen"] = ts
            if ts > timestamps[sid]["last_seen"]:
                timestamps[sid]["last_seen"] = ts
    return timestamps


def get_all_costs(
    data_dir: OTLPDataDir | None = None, since: datetime | None = None
) -> CostMetrics:
    """Calculate comprehensive cost metrics from telemetry data.

    Args:
        data_dir: Optional OTLPDataDir. If None, uses environment default.
        since: Optional cutoff datetime. Only includes events after this time.

    Returns:
        CostMetrics with session and model breakdowns.
    """
    if data_dir is None:
        data_dir = OTLPDataDir.from_env()

    reader = OTLPReader(data_dir)
    events = reader.read_events()

    api_requests, perf_accumulators = _extract_all_events(events, since)

    model_data = _aggregate_requests_by_key(api_requests, "model")
    totals = _calculate_totals(api_requests)
    efficiency = (totals["output"] / totals["input"]) if totals["input"] > 0 else 0.0

    session_model_data = _aggregate_requests_by_session_and_model(api_requests)
    session_timestamps = _build_session_timestamps(api_requests)
    session_perf = _build_session_perf_objects(perf_accumulators)
    session_costs = _build_session_costs(session_model_data, session_timestamps, session_perf)
    model_costs = _build_model_costs(model_data)

    total_cost = sum(mc.cost for mc in model_costs)

    input_denom = max(1, totals["input"] + totals["cache_read"])
    input_ratio = totals["input"] / input_denom
    cache_savings = total_cost * (1 - input_ratio) * 0.9

    return CostMetrics(
        total_api_calls=totals["api_calls"],
        total_input_tokens=totals["input"],
        total_output_tokens=totals["output"],
        total_cache_creation_tokens=totals["cache_creation"],
        total_cache_read_tokens=totals["cache_read"],
        total_cost=total_cost,
        total_cache_savings=cache_savings,
        efficiency_ratio=efficiency,
        by_session=session_costs,
        by_model=model_costs,
    )


def get_daily_costs(
    data_dir: OTLPDataDir | None = None, since: str | None = None
) -> list[DailyCost]:
    """Aggregate costs by date from api_request events.

    Args:
        data_dir: Optional OTLPDataDir. If None, uses environment default.
        since: Optional time window string (e.g., '7d', '24h').

    Returns:
        List of DailyCost sorted by date ascending.
    """
    if data_dir is None:
        data_dir = OTLPDataDir.from_env()

    reader = OTLPReader(data_dir)
    events = reader.read_events()

    since_dt = parse_time_window(since) if since else None
    api_requests = _extract_api_requests(events, since_dt)

    daily: dict[str, dict] = defaultdict(
        lambda: {
            "api_calls": 0,
            "cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }
    )

    for req in api_requests:
        date_str = req["timestamp"].strftime("%Y-%m-%d")
        input_price, output_price = get_model_pricing(req["model"])
        cost = (
            (req["input_tokens"] * input_price / 1_000_000)
            + (req["output_tokens"] * output_price / 1_000_000)
            + (req["cache_creation_tokens"] * input_price * 1.25 / 1_000_000)
            + (req["cache_read_tokens"] * input_price * 0.1 / 1_000_000)
        )
        daily[date_str]["api_calls"] += 1
        daily[date_str]["cost"] += cost
        daily[date_str]["input_tokens"] += req["input_tokens"]
        daily[date_str]["output_tokens"] += req["output_tokens"]
        daily[date_str]["cache_creation_tokens"] += req["cache_creation_tokens"]
        daily[date_str]["cache_read_tokens"] += req["cache_read_tokens"]

    return [
        DailyCost(
            date=date_str,
            api_calls=data["api_calls"],
            cost=data["cost"],
            input_tokens=data["input_tokens"],
            output_tokens=data["output_tokens"],
            cache_creation_tokens=data["cache_creation_tokens"],
            cache_read_tokens=data["cache_read_tokens"],
        )
        for date_str, data in sorted(daily.items())
    ]


def _accumulate_cost_datapoints(
    data_points: list[MetricDataPoint],
    since_dt: datetime | None,
    daily_cost: dict[str, float],
    daily_calls: dict[str, int],
) -> None:
    """Add cost.usage data points on/after ``since_dt`` into the daily totals."""
    for point in data_points:
        if since_dt is not None and point.timestamp < since_dt:
            continue
        date_str = point.timestamp.strftime("%Y-%m-%d")
        daily_cost[date_str] += point.value
        daily_calls[date_str] += 1


def get_model_performance(
    data_dir: OTLPDataDir | None = None, since: str | None = None
) -> list[ModelPerformance]:
    """Get per-model performance metrics including error rates and latency.

    Args:
        data_dir: Optional OTLPDataDir. If None, uses environment default.
        since: Optional time window string (e.g., '7d', '24h').

    Returns:
        List of ModelPerformance sorted by model name.
    """
    if data_dir is None:
        data_dir = OTLPDataDir.from_env()

    reader = OTLPReader(data_dir)
    events = reader.read_events()

    since_dt = parse_time_window(since) if since else None
    api_requests, perf_accumulators = _extract_all_events(events, since_dt)

    model_data: dict[str, dict] = defaultdict(
        lambda: {
            "api_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "latencies": [],
            "error_count": 0,
        }
    )

    for req in api_requests:
        model = req["model"]
        model_data[model]["api_calls"] += 1
        model_data[model]["input_tokens"] += req["input_tokens"]
        model_data[model]["output_tokens"] += req["output_tokens"]
        model_data[model]["cache_creation_tokens"] += req["cache_creation_tokens"]
        if req.get("duration_ms") is not None:
            model_data[model]["latencies"].append(req["duration_ms"])

    session_perf = _build_session_perf_objects(perf_accumulators)
    for _sid, perf in session_perf.items():
        if perf.error_count > 0 and perf.model_mix:
            total_calls = sum(perf.model_mix.values())
            for model, calls in perf.model_mix.items():
                proportion = calls / max(total_calls, 1)
                model_data[model]["error_count"] += round(perf.error_count * proportion)

    results = []
    for model_name, data in sorted(model_data.items()):
        input_price, output_price = get_model_pricing(model_name)
        cost = (
            (data["input_tokens"] * input_price / 1_000_000)
            + (data["output_tokens"] * output_price / 1_000_000)
            + (data["cache_creation_tokens"] * input_price / 1_000_000)
        )
        latencies = sorted(data["latencies"])
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        p95_latency = _calc_p95(latencies)
        api_calls = data["api_calls"]
        error_count = data["error_count"]
        results.append(
            ModelPerformance(
                model_name=model_name,
                api_calls=api_calls,
                error_count=error_count,
                error_rate=error_count / max(api_calls, 1),
                avg_latency_ms=avg_latency,
                p95_latency_ms=p95_latency,
                cost=cost,
                input_tokens=data["input_tokens"],
                output_tokens=data["output_tokens"],
            )
        )

    return results
