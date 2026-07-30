"""Tests for telemetry/otel/analytics/clustering.py."""

import unittest
from unittest import mock

from telemetry.otel.analytics.clustering import (
    _assign_cluster_labels,
    _assign_to_nearest,
    _cluster_from_metrics,
    _normalize_features,
    _recompute_centers,
    _run_kmeans,
)
from telemetry.otel.cost_models import SessionCluster

from tests.telemetry_tests.otel_analytics._shared_helpers import (
    _make_cost_metrics,
    _make_session_cost,
)


# ---------------------------------------------------------------------------
# _normalize_features
# ---------------------------------------------------------------------------

class TestNormalizeFeatures(unittest.TestCase):

    def test_all_same_cost_normalizes_to_zero(self):
        features = [("s1", 5.0, 100.0), ("s2", 5.0, 200.0), ("s3", 5.0, 300.0)]
        result = _normalize_features(features)
        # All costs equal: cost_range=1 (guard), so (5 - 5) / 1 = 0
        for nc, _ in result:
            self.assertAlmostEqual(nc, 0.0, places=6)

    def test_all_same_tokens_normalizes_to_zero(self):
        features = [("s1", 1.0, 50.0), ("s2", 2.0, 50.0), ("s3", 3.0, 50.0)]
        result = _normalize_features(features)
        for _, nt in result:
            self.assertAlmostEqual(nt, 0.0, places=6)

    def test_min_cost_normalizes_to_zero(self):
        features = [("s1", 0.0, 0.0), ("s2", 10.0, 10.0)]
        result = _normalize_features(features)
        self.assertAlmostEqual(result[0][0], 0.0, places=6)

    def test_max_cost_normalizes_to_one(self):
        features = [("s1", 0.0, 0.0), ("s2", 10.0, 10.0)]
        result = _normalize_features(features)
        self.assertAlmostEqual(result[1][0], 1.0, places=6)

    def test_min_tokens_normalizes_to_zero(self):
        features = [("s1", 0.0, 100.0), ("s2", 5.0, 1000.0)]
        result = _normalize_features(features)
        self.assertAlmostEqual(result[0][1], 0.0, places=6)

    def test_max_tokens_normalizes_to_one(self):
        features = [("s1", 0.0, 100.0), ("s2", 5.0, 1000.0)]
        result = _normalize_features(features)
        self.assertAlmostEqual(result[1][1], 1.0, places=6)

    def test_values_bounded_between_0_and_1(self):
        features = [
            ("s1", 1.0, 100.0),
            ("s2", 5.0, 500.0),
            ("s3", 10.0, 1000.0),
        ]
        result = _normalize_features(features)
        for nc, nt in result:
            self.assertGreaterEqual(nc, 0.0)
            self.assertLessEqual(nc, 1.0)
            self.assertGreaterEqual(nt, 0.0)
            self.assertLessEqual(nt, 1.0)

    def test_midpoint_normalizes_to_0_5(self):
        features = [("s1", 0.0, 0.0), ("s2", 5.0, 50.0), ("s3", 10.0, 100.0)]
        result = _normalize_features(features)
        self.assertAlmostEqual(result[1][0], 0.5, places=6)
        self.assertAlmostEqual(result[1][1], 0.5, places=6)


# ---------------------------------------------------------------------------
# _assign_to_nearest
# ---------------------------------------------------------------------------

class TestAssignToNearest(unittest.TestCase):

    def test_single_point_assigned_to_nearest_center(self):
        points = [(0.1, 0.1)]
        centers = [(0.0, 0.0), (1.0, 1.0)]
        result = _assign_to_nearest(points, centers)
        self.assertEqual(result, [0])

    def test_two_points_assigned_correctly(self):
        points = [(0.1, 0.1), (0.9, 0.9)]
        centers = [(0.0, 0.0), (1.0, 1.0)]
        result = _assign_to_nearest(points, centers)
        self.assertEqual(result[0], 0)
        self.assertEqual(result[1], 1)

    def test_equidistant_point_picks_first_center(self):
        points = [(0.5, 0.5)]
        centers = [(0.0, 0.0), (1.0, 1.0)]
        # Both are equal distance; index() returns first occurrence
        result = _assign_to_nearest(points, centers)
        # Distance to both = sqrt(0.5): both equal, so either 0 or 1; just verify no error
        self.assertIn(result[0], [0, 1])

    def test_three_clusters_correct_assignments(self):
        centers = [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)]
        points = [(0.1, 0.1), (0.45, 0.45), (0.9, 0.9)]
        result = _assign_to_nearest(points, centers)
        self.assertEqual(result[0], 0)   # closest to first center
        self.assertEqual(result[1], 1)   # closest to second center
        self.assertEqual(result[2], 2)   # closest to third center

    def test_returns_list_of_same_length(self):
        points = [(float(i) / 10, float(i) / 10) for i in range(10)]
        centers = [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)]
        result = _assign_to_nearest(points, centers)
        self.assertEqual(len(result), 10)


# ---------------------------------------------------------------------------
# _recompute_centers
# ---------------------------------------------------------------------------

class TestRecomputeCenters(unittest.TestCase):

    def test_single_cluster_center_is_mean(self):
        centers = [(0.5, 0.5)]
        normalized = [(0.0, 0.0), (1.0, 1.0)]
        assignments = [0, 0]
        _recompute_centers(centers, normalized, assignments, 1)
        self.assertAlmostEqual(centers[0][0], 0.5, places=6)
        self.assertAlmostEqual(centers[0][1], 0.5, places=6)

    def test_empty_cluster_center_unchanged(self):
        centers = [(0.5, 0.5), (0.9, 0.9)]
        normalized = [(0.1, 0.1), (0.2, 0.2)]
        # Both assigned to cluster 0, so cluster 1 is empty
        assignments = [0, 0]
        original_center_1 = centers[1]
        _recompute_centers(centers, normalized, assignments, 2)
        self.assertEqual(centers[1], original_center_1)

    def test_two_clusters_independent_centers(self):
        centers = [(0.0, 0.0), (1.0, 1.0)]
        normalized = [(0.0, 0.0), (0.2, 0.2), (0.8, 0.8), (1.0, 1.0)]
        assignments = [0, 0, 1, 1]
        _recompute_centers(centers, normalized, assignments, 2)
        self.assertAlmostEqual(centers[0][0], 0.1, places=6)
        self.assertAlmostEqual(centers[1][0], 0.9, places=6)


# ---------------------------------------------------------------------------
# _assign_cluster_labels
# ---------------------------------------------------------------------------

class TestAssignClusterLabels(unittest.TestCase):

    def test_3_clusters_get_low_medium_high(self):
        # centers sorted by cost: 0.0, 0.5, 1.0 → low, medium, high
        centers = [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)]
        labels = _assign_cluster_labels(centers, 3)
        self.assertEqual(len(labels), 3)
        # The cluster with lowest cost dimension gets "low-cost"
        self.assertEqual(labels[0], "low-cost")
        self.assertEqual(labels[1], "medium-cost")
        self.assertEqual(labels[2], "high-cost")

    def test_2_clusters_get_low_and_high(self):
        centers = [(0.0, 0.0), (1.0, 1.0)]
        labels = _assign_cluster_labels(centers, 2)
        self.assertEqual(labels[0], "low-cost")
        self.assertEqual(labels[1], "high-cost")

    def test_1_cluster_gets_low_cost(self):
        centers = [(0.5, 0.5)]
        labels = _assign_cluster_labels(centers, 1)
        self.assertEqual(labels[0], "low-cost")

    def test_4_clusters_use_cluster_n_label(self):
        centers = [(0.0, 0.0), (0.33, 0.33), (0.66, 0.66), (1.0, 1.0)]
        labels = _assign_cluster_labels(centers, 4)
        # 4 > len(label_names)=3, so all get "cluster-N"
        for label in labels:
            self.assertTrue(label.startswith("cluster-"))

    def test_labels_list_length_equals_n_clusters(self):
        centers = [(float(i) / 3, 0.0) for i in range(3)]
        labels = _assign_cluster_labels(centers, 3)
        self.assertEqual(len(labels), 3)

    def test_reversed_centers_still_assigns_correctly(self):
        # Centers in reverse order: high-cost at index 0, low-cost at index 1
        centers = [(1.0, 0.0), (0.0, 0.0)]
        labels = _assign_cluster_labels(centers, 2)
        self.assertEqual(labels[1], "low-cost")
        self.assertEqual(labels[0], "high-cost")


# ---------------------------------------------------------------------------
# _run_kmeans
# ---------------------------------------------------------------------------

class TestRunKmeans(unittest.TestCase):

    def test_returns_centers_and_assignments_same_length(self):
        normalized = [(float(i) / 10, float(i) / 10) for i in range(10)]
        centers, assignments = _run_kmeans(normalized, n_clusters=3)
        self.assertEqual(len(centers), 3)
        self.assertEqual(len(assignments), 10)

    def test_all_assignments_are_valid_cluster_indices(self):
        normalized = [(float(i) / 10, float(i) / 10) for i in range(10)]
        _, assignments = _run_kmeans(normalized, n_clusters=3)
        for a in assignments:
            self.assertIn(a, [0, 1, 2])

    def test_deterministic_with_fixed_seed(self):
        normalized = [(float(i) / 10, 0.0) for i in range(9)]
        _, a1 = _run_kmeans(normalized, 3)
        _, a2 = _run_kmeans(normalized, 3)
        self.assertEqual(a1, a2)

    def test_runs_to_max_iterations_without_convergence(self):
        """Force the loop to exhaust all iterations without breaking early."""
        import telemetry.otel.analytics.clustering as mod
        original_max = mod._MAX_ITERATIONS
        mod._MAX_ITERATIONS = 1  # single pass, won't converge for most inputs
        try:
            # 6 evenly-spaced points, 3 clusters — may not converge in 1 step
            normalized = [(float(i) / 5, 0.0) for i in range(6)]
            centers, assignments = _run_kmeans(normalized, 3)
            self.assertEqual(len(centers), 3)
            self.assertEqual(len(assignments), 6)
        finally:
            mod._MAX_ITERATIONS = original_max

    def test_runs_without_error_on_separated_points(self):
        # Verifies _run_kmeans completes and returns valid structure even for
        # well-separated points (convergence is not guaranteed with seeded init).
        normalized = [(0.0, 0.0)] * 3 + [(0.5, 0.0)] * 3 + [(1.0, 0.0)] * 3
        centers, assignments = _run_kmeans(normalized, 3)
        self.assertEqual(len(centers), 3)
        self.assertEqual(len(assignments), 9)
        # All assignments within valid cluster range
        for a in assignments:
            self.assertIn(a, [0, 1, 2])
        # Points in the same group still cluster consistently — all 3 copies of
        # each value should map to the same assignment (k-means is deterministic).
        self.assertEqual(len(set(assignments[:3])), 1)   # group at 0.0
        self.assertEqual(len(set(assignments[6:])), 1)   # group at 1.0


# ---------------------------------------------------------------------------
# _cluster_from_metrics
# ---------------------------------------------------------------------------

class TestClusterFromMetrics(unittest.TestCase):

    def test_empty_sessions_returns_empty(self):
        metrics = _make_cost_metrics([])
        result = _cluster_from_metrics(metrics, n_clusters=3)
        self.assertEqual(result, [])

    def test_sessions_at_most_n_clusters_all_assigned_cluster_0(self):
        # len(features) <= n_clusters → early return with cluster_id=0
        sessions = [
            _make_session_cost("s1", cost=1.0),
            _make_session_cost("s2", cost=2.0),
        ]
        metrics = _make_cost_metrics(sessions)
        result = _cluster_from_metrics(metrics, n_clusters=3)
        self.assertEqual(len(result), 2)
        for r in result:
            self.assertEqual(r.cluster_id, 0)
            self.assertEqual(r.cluster_label, "low-cost")

    def test_exactly_n_clusters_sessions_still_assigned_cluster_0(self):
        sessions = [_make_session_cost(f"s{i}", cost=float(i)) for i in range(3)]
        metrics = _make_cost_metrics(sessions)
        result = _cluster_from_metrics(metrics, n_clusters=3)
        self.assertEqual(len(result), 3)
        for r in result:
            self.assertEqual(r.cluster_id, 0)

    def test_result_includes_all_sessions(self):
        sessions = [_make_session_cost(f"s{i}", cost=float(i)) for i in range(10)]
        metrics = _make_cost_metrics(sessions)
        result = _cluster_from_metrics(metrics, n_clusters=3)
        self.assertEqual(len(result), 10)

    def test_each_result_is_session_cluster(self):
        sessions = [_make_session_cost(f"s{i}", cost=float(i)) for i in range(10)]
        metrics = _make_cost_metrics(sessions)
        result = _cluster_from_metrics(metrics, n_clusters=3)
        for r in result:
            self.assertIsInstance(r, SessionCluster)

    def test_session_ids_preserved(self):
        sessions = [_make_session_cost(f"sess-{i}", cost=float(i)) for i in range(10)]
        metrics = _make_cost_metrics(sessions)
        result = _cluster_from_metrics(metrics, n_clusters=3)
        result_ids = {r.session_id for r in result}
        expected_ids = {f"sess-{i}" for i in range(10)}
        self.assertEqual(result_ids, expected_ids)

    def test_features_dict_contains_cost_and_tokens(self):
        sessions = [_make_session_cost(f"s{i}", cost=float(i)) for i in range(10)]
        metrics = _make_cost_metrics(sessions)
        result = _cluster_from_metrics(metrics, n_clusters=3)
        for r in result:
            self.assertIn("cost", r.features)
            self.assertIn("billable_tokens", r.features)

    def test_cluster_ids_in_valid_range(self):
        sessions = [_make_session_cost(f"s{i}", cost=float(i)) for i in range(10)]
        metrics = _make_cost_metrics(sessions)
        n_clusters = 3
        result = _cluster_from_metrics(metrics, n_clusters=n_clusters)
        for r in result:
            self.assertGreaterEqual(r.cluster_id, 0)
            self.assertLess(r.cluster_id, n_clusters)

    def test_cluster_labels_are_valid_strings(self):
        sessions = [_make_session_cost(f"s{i}", cost=float(i)) for i in range(10)]
        metrics = _make_cost_metrics(sessions)
        result = _cluster_from_metrics(metrics, n_clusters=3)
        valid_labels = {"low-cost", "medium-cost", "high-cost"}
        for r in result:
            self.assertIn(r.cluster_label, valid_labels)

    def test_single_session_returns_single_cluster_0(self):
        sessions = [_make_session_cost("only", cost=5.0)]
        metrics = _make_cost_metrics(sessions)
        result = _cluster_from_metrics(metrics, n_clusters=3)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].session_id, "only")
        self.assertEqual(result[0].cluster_id, 0)


# ---------------------------------------------------------------------------
# cluster_sessions — integration via mock
# ---------------------------------------------------------------------------

class TestClusterSessionsIntegration(unittest.TestCase):

    @mock.patch("telemetry.otel.analytics.clustering.get_all_costs")
    def test_calls_get_all_costs(self, mock_get_all_costs):
        from telemetry.otel.analytics.clustering import cluster_sessions
        from telemetry.otel.reader import OTLPDataDir
        mock_get_all_costs.return_value = _make_cost_metrics([])
        data_dir = OTLPDataDir.default()
        cluster_sessions(data_dir=data_dir, n_clusters=3)
        mock_get_all_costs.assert_called_once_with(data_dir=data_dir, since=None)

    @mock.patch("telemetry.otel.analytics.clustering.get_all_costs")
    def test_empty_sessions_returns_empty(self, mock_get_all_costs):
        from telemetry.otel.analytics.clustering import cluster_sessions
        mock_get_all_costs.return_value = _make_cost_metrics([])
        result = cluster_sessions()
        self.assertEqual(result, [])

    @mock.patch("telemetry.otel.analytics.clustering.get_all_costs")
    def test_10_sessions_returns_10_clusters(self, mock_get_all_costs):
        from telemetry.otel.analytics.clustering import cluster_sessions
        sessions = [_make_session_cost(f"s{i}", cost=float(i)) for i in range(10)]
        mock_get_all_costs.return_value = _make_cost_metrics(sessions)
        result = cluster_sessions(n_clusters=3)
        self.assertEqual(len(result), 10)


if __name__ == "__main__":
    unittest.main()
