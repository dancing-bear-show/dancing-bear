"""Anomaly detection for telemetry sessions using z-score analysis."""

from __future__ import annotations

import math
from datetime import datetime

from telemetry.otel.analytics.cost import get_all_costs
from telemetry.otel.cost_models import AnomalyFlag, CostMetrics
from telemetry.otel.reader import OTLPDataDir


def detect_anomalies(
    data_dir: OTLPDataDir | None = None,
    since: datetime | None = None,
    threshold: float = 2.0,
) -> list[AnomalyFlag]:
    """Detect anomalous sessions using z-score on key metrics.

    Analyzes cost, billable_tokens, and avg_api_latency_ms across all
    sessions. A session metric is flagged when its absolute z-score
    meets or exceeds the threshold.

    Args:
        data_dir: Optional data directory override.
        since: Optional cutoff datetime for session filtering.
        threshold: Z-score threshold for flagging (default 2.0).

    Returns:
        List of AnomalyFlag instances for flagged session metrics.
    """
    metrics = get_all_costs(data_dir=data_dir, since=since)
    return _detect_from_metrics(metrics, threshold)


def _detect_from_metrics(metrics: CostMetrics, threshold: float) -> list[AnomalyFlag]:
    """Run z-score detection on pre-loaded metrics."""
    sessions = metrics.by_session
    if len(sessions) < 3:
        return []

    flags: list[AnomalyFlag] = []

    metric_extractors: list[tuple[str, list[tuple[str, float]]]] = [
        ("cost", [(s.session_id, s.cost) for s in sessions]),
        ("tokens", [(s.session_id, float(s.billable_tokens)) for s in sessions]),
        (
            "latency",
            [
                (s.session_id, s.perf.avg_api_latency_ms)
                for s in sessions
                if s.perf is not None
            ],
        ),
    ]

    for metric_name, values in metric_extractors:
        if len(values) < 3:
            continue

        nums = [v for _, v in values]
        mean = sum(nums) / len(nums)
        variance = sum((x - mean) ** 2 for x in nums) / len(nums)
        std_dev = math.sqrt(variance)

        if math.isclose(std_dev, 0.0):
            continue

        for session_id, value in values:
            z_score = (value - mean) / std_dev
            if abs(z_score) >= threshold:
                flags.append(
                    AnomalyFlag(
                        session_id=session_id,
                        metric=metric_name,
                        value=value,
                        mean=round(mean, 4),
                        std_dev=round(std_dev, 4),
                        z_score=round(z_score, 4),
                    )
                )

    return flags
