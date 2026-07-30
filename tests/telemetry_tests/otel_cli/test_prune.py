"""Tests for telemetry/otel/cli/prune.py."""

from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, patch

from telemetry.otel.cli.prune import main
from telemetry.otel.retention import PruneResult


def _make_prune_result(
    *,
    data_type: str = "metrics",
    records_before: int = 100,
    records_after: int = 50,
    records_removed: int = 50,
    bytes_before: int = 10000,
    bytes_after: int = 5000,
    bytes_removed: int = 5000,
    dry_run: bool = True,
) -> PruneResult:
    return PruneResult(
        data_type=data_type,
        records_before=records_before,
        records_after=records_after,
        records_removed=records_removed,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
        bytes_removed=bytes_removed,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestPruneMain(unittest.TestCase):
    def _run_prune(
        self,
        argv: list[str],
        results: list[PruneResult] | None = None,
    ) -> tuple[int, str]:
        if results is None:
            results = [_make_prune_result()]
        mock_reader = MagicMock()
        mock_pruner = MagicMock()
        mock_pruner.prune_all.return_value = results
        mock_pruner.prune.return_value = results[0]

        with patch("telemetry.otel.cli.prune.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.prune.OTLPReader", return_value=mock_reader):
                with patch("telemetry.otel.cli.prune.load_retention_config"):
                    with patch("telemetry.otel.cli.prune.TelemetryPruner", return_value=mock_pruner):
                        buf = io.StringIO()
                        with patch("sys.stdout", buf):
                            result = main(argv)
        return result, buf.getvalue()

    def test_dry_run_default_returns_0(self):
        result, _ = self._run_prune([])
        self.assertEqual(result, 0)

    def test_dry_run_shows_dry_run_message(self):
        _, output = self._run_prune([])
        self.assertIn("DRY RUN", output)

    def test_apply_flag_not_dry_run(self):
        result = _make_prune_result(dry_run=False)
        rc, output = self._run_prune(["--apply"], results=[result])
        self.assertEqual(rc, 0)
        self.assertNotIn("DRY RUN", output)

    def test_older_than_flag_overrides_config(self):
        result, _ = self._run_prune(["--older-than", "7"])
        self.assertEqual(result, 0)

    def test_prune_type_metrics(self):
        result, output = self._run_prune(["--type", "metrics"])
        self.assertEqual(result, 0)
        self.assertIn("METRICS", output)

    def test_prune_type_events(self):
        event_result = _make_prune_result(data_type="events")
        result, output = self._run_prune(["--type", "events"], results=[event_result])
        self.assertEqual(result, 0)
        self.assertIn("EVENTS", output)

    def test_prune_all_shows_each_type(self):
        results = [
            _make_prune_result(data_type="metrics"),
            _make_prune_result(data_type="events"),
            _make_prune_result(data_type="spans"),
        ]
        rc, output = self._run_prune([], results=results)
        self.assertEqual(rc, 0)
        self.assertIn("METRICS", output)
        self.assertIn("EVENTS", output)
        self.assertIn("SPANS", output)

    def test_shows_before_after_counts(self):
        result = _make_prune_result(records_before=100, records_after=50, records_removed=50)
        _, output = self._run_prune([], results=[result])
        self.assertIn("100", output)
        self.assertIn("50", output)

    def test_prune_validation_error_returns_2(self):
        mock_reader = MagicMock()
        mock_pruner = MagicMock()
        mock_pruner.prune_all.side_effect = ValueError("bad config")

        with patch("telemetry.otel.cli.prune.OTLPDataDir.from_env"):
            with patch("telemetry.otel.cli.prune.OTLPReader", return_value=mock_reader):
                with patch("telemetry.otel.cli.prune.load_retention_config"):
                    with patch("telemetry.otel.cli.prune.TelemetryPruner", return_value=mock_pruner):
                        result = main([])
        self.assertEqual(result, 2)

    def test_data_dir_flag(self):
        import tempfile
        mock_reader = MagicMock()
        mock_pruner = MagicMock()
        mock_pruner.prune_all.return_value = [_make_prune_result()]

        with tempfile.TemporaryDirectory() as td:
            with patch("telemetry.otel.cli.prune.OTLPReader", return_value=mock_reader):
                with patch("telemetry.otel.cli.prune.load_retention_config"):
                    with patch("telemetry.otel.cli.prune.TelemetryPruner", return_value=mock_pruner):
                        result = main(["--data-dir", td])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
