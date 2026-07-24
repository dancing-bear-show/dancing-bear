"""Session clustering using simple k-means on cost and token features."""

from __future__ import annotations

import math
import random
from datetime import datetime

from telemetry.otel.analytics.cost import get_all_costs
from telemetry.otel.cost_models import CostMetrics, SessionCluster
from telemetry.otel.reader import OTLPDataDir

_MAX_ITERATIONS = 20


def cluster_sessions(
    data_dir: OTLPDataDir | None = None,
    since: datetime | None = None,
    n_clusters: int = 3,
) -> list[SessionCluster]:
    """Cluster sessions by cost and token features using k-means.

    Args:
        data_dir: Optional data directory override.
        since: Optional cutoff datetime for session filtering.
        n_clusters: Number of clusters (default 3).

    Returns:
        List of SessionCluster assignments.
    """
    metrics = get_all_costs(data_dir=data_dir, since=since)
    return _cluster_from_metrics(metrics, n_clusters)


def _cluster_from_metrics(metrics: CostMetrics, n_clusters: int) -> list[SessionCluster]:
    """Run k-means clustering on pre-loaded metrics."""
    sessions = metrics.by_session
    if not sessions:
        return []

    features: list[tuple[str, float, float]] = [
        (s.session_id, s.cost, float(s.billable_tokens))
        for s in sessions
    ]

    if len(features) <= n_clusters:
        return [
            SessionCluster(
                session_id=sid,
                cluster_id=0,
                cluster_label="low-cost",
                features={"cost": cost, "billable_tokens": tokens},
            )
            for sid, cost, tokens in features
        ]

    normalized = _normalize_features(features)
    centers, assignments = _run_kmeans(normalized, n_clusters)
    labels = _assign_cluster_labels(centers, n_clusters)

    return [
        SessionCluster(
            session_id=sid,
            cluster_id=assignments[i],
            cluster_label=labels[assignments[i]],
            features={"cost": cost, "billable_tokens": tok},
        )
        for i, (sid, cost, tok) in enumerate(features)
    ]


def _normalize_features(features: list[tuple[str, float, float]]) -> list[tuple[float, float]]:
    """Normalize cost and token features to 0-1 range."""
    costs = [f[1] for f in features]
    tokens = [f[2] for f in features]

    cost_min, cost_max = min(costs), max(costs)
    tok_min, tok_max = min(tokens), max(tokens)

    cost_range = cost_max - cost_min if cost_max != cost_min else 1.0
    tok_range = tok_max - tok_min if tok_max != tok_min else 1.0

    return [
        ((c - cost_min) / cost_range, (t - tok_min) / tok_range)
        for _, c, t in features
    ]


def _run_kmeans(
    normalized: list[tuple[float, float]], n_clusters: int
) -> tuple[list[tuple[float, float]], list[int]]:
    """Run k-means iteration and return final centers and assignments."""
    rng = random.Random(42)  # nosec B311 - seeded for deterministic k-means centroid init, not cryptography
    indices = rng.sample(range(len(normalized)), n_clusters)
    centers = [normalized[i] for i in indices]
    assignments = [0] * len(normalized)

    for _ in range(_MAX_ITERATIONS):
        new_assignments = _assign_to_nearest(normalized, centers)
        if new_assignments == assignments:
            break
        assignments = new_assignments
        _recompute_centers(centers, normalized, assignments, n_clusters)

    return centers, assignments


def _assign_to_nearest(
    points: list[tuple[float, float]], centers: list[tuple[float, float]]
) -> list[int]:
    """Assign each point to its nearest center."""
    assignments = []
    for nc, nt in points:
        dists = [
            math.sqrt((nc - cc) ** 2 + (nt - ct) ** 2)
            for cc, ct in centers
        ]
        assignments.append(dists.index(min(dists)))
    return assignments


def _recompute_centers(
    centers: list[tuple[float, float]],
    normalized: list[tuple[float, float]],
    assignments: list[int],
    n_clusters: int,
) -> None:
    """Recompute cluster centers in-place from current assignments."""
    for k in range(n_clusters):
        members = [normalized[i] for i in range(len(normalized)) if assignments[i] == k]
        if members:
            centers[k] = (
                sum(m[0] for m in members) / len(members),
                sum(m[1] for m in members) / len(members),
            )


def _assign_cluster_labels(
    centers: list[tuple[float, float]], n_clusters: int
) -> list[str]:
    """Assign human-readable labels to clusters ranked by cost dimension."""
    center_costs = [(k, centers[k][0]) for k in range(n_clusters)]
    center_costs.sort(key=lambda x: x[1])

    label_names = ["low-cost", "medium-cost", "high-cost"]
    labels = [""] * n_clusters
    for rank, (k, _) in enumerate(center_costs):
        if n_clusters <= len(label_names):
            labels[k] = label_names[rank * (len(label_names) - 1) // max(n_clusters - 1, 1)]
        else:
            labels[k] = f"cluster-{rank}"
    return labels
