"""Shared test-fixture helpers for otel_analytics and otel_cli telemetry tests.

Consolidates near-identical `_make_session_cost` / `_make_perf` /
`_make_cost_metrics` / `_utc` helpers that were duplicated across
tests/telemetry_tests/otel_analytics/*.py (and, where the shape genuinely
matched, tests/telemetry_tests/otel_cli/*.py). Each function here is a
superset of every consolidated variant's parameters, with matching defaults,
so existing call sites continue to work unmodified after switching their
import to this module.
"""

from __future__ import annotations

from datetime import datetime, timezone

from telemetry.otel.cost_models import CostMetrics, SessionCost, SessionPerf


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Build a UTC datetime. `minute` defaults to 0, matching hour-only callers."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _make_perf(
    avg_api_latency_ms: float = 100.0,
    error_rate: float = 0.0,
    tool_failure_rate: float = 0.0,
    error_count: int = 0,
    tool_calls: int = 0,
    tool_failures: int = 0,
) -> SessionPerf:
    """Superset of the otel_analytics `_make_perf` variants (anomaly/compare/health_score)."""
    return SessionPerf(
        error_count=error_count,
        error_rate=error_rate,
        tool_calls=tool_calls,
        tool_failures=tool_failures,
        tool_failure_rate=tool_failure_rate,
        avg_api_latency_ms=avg_api_latency_ms,
    )


def _make_session_cost(
    session_id: str = "sess-1",
    cost: float = 0.0,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    api_calls: int = 1,
    efficiency_ratio: float = 0.5,
    first_seen: datetime | None = None,
    last_seen: datetime | None = None,
    perf: SessionPerf | None = None,
) -> SessionCost:
    """Superset of the otel_analytics `_make_session_cost` variants.

    (anomaly.py, clustering.py, compare.py, health_score.py)
    """
    return SessionCost(
        session_id=session_id,
        api_calls=api_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        cost=cost,
        efficiency_ratio=efficiency_ratio,
        first_seen=first_seen,
        last_seen=last_seen,
        perf=perf,
    )


def _make_cost_metrics(sessions: list[SessionCost]) -> CostMetrics:
    """Sums totals from `sessions` (anomaly.py's behavior).

    Standardized here because no consolidated caller (clustering.py,
    compare.py) ever asserts on total_input_tokens/total_output_tokens/
    total_cost, so the summing behavior is safe to use everywhere.
    """
    return CostMetrics(
        total_api_calls=len(sessions),
        total_input_tokens=sum(s.input_tokens for s in sessions),
        total_output_tokens=sum(s.output_tokens for s in sessions),
        total_cache_creation_tokens=0,
        total_cache_read_tokens=0,
        total_cost=sum(s.cost for s in sessions),
        total_cache_savings=0.0,
        efficiency_ratio=0.5,
        by_session=sessions,
        by_model=[],
    )
