"""Session comparison analytics.

Loads two sessions by ID from cost analytics and builds a
SessionComparison dataclass with side-by-side metrics.
"""

from __future__ import annotations

from datetime import timedelta

from telemetry.otel.analytics.cost import get_all_costs
from telemetry.otel.cost_models import SessionComparison, SessionCost
from telemetry.otel.reader import OTLPDataDir


def compare_sessions(
    session_id_a: str,
    session_id_b: str,
    data_dir: OTLPDataDir | None = None,
) -> SessionComparison:
    """Build a side-by-side comparison of two sessions.

    Args:
        session_id_a: First session ID.
        session_id_b: Second session ID.
        data_dir: Optional OTLPDataDir. If None, uses environment default.

    Returns:
        SessionComparison dataclass.

    Raises:
        ValueError: If either session ID is not found in telemetry data.
    """
    metrics = get_all_costs(data_dir=data_dir)

    sessions_by_id: dict[str, SessionCost] = {s.session_id: s for s in metrics.by_session}

    if session_id_a not in sessions_by_id:
        raise ValueError(f"Session not found: {session_id_a}")
    if session_id_b not in sessions_by_id:
        raise ValueError(f"Session not found: {session_id_b}")

    a = sessions_by_id[session_id_a]
    b = sessions_by_id[session_id_b]

    dur_a = a.duration_minutes
    dur_b = b.duration_minutes
    duration_delta: timedelta | None = None
    if dur_a is not None and dur_b is not None:
        duration_delta = timedelta(minutes=dur_b) - timedelta(minutes=dur_a)

    errors_a = a.perf.error_count if a.perf else 0
    errors_b = b.perf.error_count if b.perf else 0

    return SessionComparison(
        session_a=a,
        session_b=b,
        cost_delta=b.cost - a.cost,
        token_delta=b.billable_tokens - a.billable_tokens,
        duration_delta=duration_delta,
        error_delta=errors_b - errors_a,
    )
