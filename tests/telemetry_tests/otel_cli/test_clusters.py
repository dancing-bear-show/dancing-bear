"""Tests for telemetry/otel/cli/clusters.py."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from telemetry.otel.cli.clusters import main
from telemetry.otel.cost_models import SessionCluster


def _make_cluster(
    *,
    session_id: str = "abc123",
    cluster_id: int = 0,
    cluster_label: str = "low-cost",
    features: dict | None = None,
) -> SessionCluster:
    return SessionCluster(
        session_id=session_id,
        cluster_id=cluster_id,
        cluster_label=cluster_label,
        features=features or {"cost": 0.05, "billable_tokens": 1000},
    )


class TestClustersMain(unittest.TestCase):
    def _run(self, argv: list[str], results: list | None = None) -> tuple[int, str, str]:
        if results is None:
            results = []
        with patch("telemetry.otel.cli.clusters.cluster_sessions", return_value=results):
            with patch("telemetry.otel.cli.clusters.resolve_data_dir", return_value=None):
                with patch("telemetry.otel.cli.clusters.resolve_since", return_value=(None, None)):
                    stdout_buf = io.StringIO()
                    stderr_buf = io.StringIO()
                    with patch("sys.stdout", stdout_buf):
                        with patch("sys.stderr", stderr_buf):
                            result = main(argv)
        return result, stdout_buf.getvalue(), stderr_buf.getvalue()

    def test_no_data_returns_0_with_message_on_stderr(self):
        result, _, stderr = self._run([])
        self.assertEqual(result, 0)
        self.assertIn("No session data", stderr)

    def test_with_data_returns_0(self):
        result, _, _ = self._run([], results=[_make_cluster()])
        self.assertEqual(result, 0)

    def test_json_format(self):
        clusters = [_make_cluster(cluster_label="low-cost")]
        result, stdout, _ = self._run(["--format", "json"], results=clusters)
        self.assertEqual(result, 0)
        data = json.loads(stdout)
        self.assertIsInstance(data, list)
        self.assertIn("cluster", data[0])

    def test_invalid_since_returns_error(self):
        with patch("telemetry.otel.cli.clusters.resolve_data_dir", return_value=None):
            with patch("telemetry.otel.cli.clusters.resolve_since", return_value=(None, 2)):
                result = main(["--since", "bad"])
        self.assertEqual(result, 2)

    def test_clusters_flag_passed(self):
        with patch("telemetry.otel.cli.clusters.cluster_sessions", return_value=[]) as mock_cluster:
            with patch("telemetry.otel.cli.clusters.resolve_data_dir", return_value=None):
                with patch("telemetry.otel.cli.clusters.resolve_since", return_value=(None, None)):
                    main(["--clusters", "5"])
        call_kwargs = mock_cluster.call_args[1]
        self.assertEqual(call_kwargs["n_clusters"], 5)


if __name__ == "__main__":
    unittest.main()
