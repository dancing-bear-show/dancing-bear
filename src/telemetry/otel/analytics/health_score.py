"""Health score calculation for telemetry sessions.

Provides a composite health score (0.0-1.0) based on error rates,
tool failure rates, and API latency.
"""

from __future__ import annotations

from telemetry.otel.cost_models import SessionCost, SessionHealthScore


def _score_to_grade(score: float) -> str:
    """Convert a numeric score to a letter grade."""
    if score >= 0.9:
        return "A"
    if score >= 0.75:
        return "B"
    if score >= 0.6:
        return "C"
    if score >= 0.4:
        return "D"
    return "F"


def calculate_health_score(session: SessionCost) -> SessionHealthScore:
    """Calculate composite health score for a session.

    Scoring:
        error_penalty = min(error_rate * 3, 0.4)
        tool_penalty = min(tool_failure_rate * 2, 0.3)
        latency_penalty = min(max(0, (avg_latency_ms - 5000) / 30000), 0.3)
        score = max(0, 1.0 - error_penalty - tool_penalty - latency_penalty)

    If perf data is unavailable, returns score=1.0, grade="A".

    Args:
        session: SessionCost with optional perf data.

    Returns:
        SessionHealthScore with score, grade, and individual penalties.
    """
    if session.perf is None:
        return SessionHealthScore(
            session_id=session.session_id,
            score=1.0,
            grade="A",
            error_penalty=0.0,
            tool_failure_penalty=0.0,
            latency_penalty=0.0,
        )

    perf = session.perf

    error_penalty = min(perf.error_rate * 3, 0.4)
    tool_failure_penalty = min(perf.tool_failure_rate * 2, 0.3)
    latency_penalty = min(max(0, (perf.avg_api_latency_ms - 5000) / 30000), 0.3)

    score = max(0.0, 1.0 - error_penalty - tool_failure_penalty - latency_penalty)
    grade = _score_to_grade(score)

    return SessionHealthScore(
        session_id=session.session_id,
        score=round(score, 3),
        grade=grade,
        error_penalty=round(error_penalty, 3),
        tool_failure_penalty=round(tool_failure_penalty, 3),
        latency_penalty=round(latency_penalty, 3),
    )
