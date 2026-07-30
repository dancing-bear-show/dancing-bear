"""Tests for telemetry/otel/cli/anomalies.py."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from telemetry.otel.cli.anomalies import main
from telemetry.otel.cost_models import AnomalyFlag


def _make_flag(
    *,
    session_id: str = "abc123",
    metric: str = "cost",
    value: float = 5.0,
    mean: float = 1.0,
    std_dev: float = 1.0,
    z_score: float = 4.0,
) -> AnomalyFlag:
    return AnomalyFlag(
        session_id=session_id,
        metric=metric,
        value=value,
        mean=mean,
        std_dev=std_dev,
        z_score=z_score,
    )


class TestAnomaliesMain(unittest.TestCase):
    def _run(self, argv: list[str], flags: list | None = None) -> tuple[int, str, str]:
        if flags is None:
            flags = []
        with patch("telemetry.otel.cli.anomalies.detect_anomalies", return_value=flags):
            with patch("telemetry.otel.cli.anomalies.resolve_data_dir", return_value=None):
                with patch("telemetry.otel.cli.anomalies.resolve_since", return_value=(None, None)):
                    stdout_buf = io.StringIO()
                    stderr_buf = io.StringIO()
                    with patch("sys.stdout", stdout_buf):
                        with patch("sys.stderr", stderr_buf):
                            result = main(argv)
        return result, stdout_buf.getvalue(), stderr_buf.getvalue()

    def test_no_data_returns_0_with_message_on_stderr(self):
        result, _, stderr = self._run([])
        self.assertEqual(result, 0)
        self.assertIn("No anomalies detected", stderr)

    def test_with_data_returns_0(self):
        flags = [_make_flag()]
        result, _, _ = self._run([], flags=flags)
        self.assertEqual(result, 0)

    def test_json_format(self):
        flags = [_make_flag()]
        result, stdout, _ = self._run(["--format", "json"], flags=flags)
        self.assertEqual(result, 0)
        data = json.loads(stdout)
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["metric"], "cost")

    def test_invalid_since_returns_error(self):
        with patch("telemetry.otel.cli.anomalies.resolve_data_dir", return_value=None):
            with patch("telemetry.otel.cli.anomalies.resolve_since", return_value=(None, 2)):
                result = main(["--since", "bad"])
        self.assertEqual(result, 2)

    def test_threshold_flag_passed_to_detect(self):
        with patch("telemetry.otel.cli.anomalies.detect_anomalies", return_value=[]) as mock_detect:
            with patch("telemetry.otel.cli.anomalies.resolve_data_dir", return_value=None):
                with patch("telemetry.otel.cli.anomalies.resolve_since", return_value=(None, None)):
                    main(["--threshold", "3.0"])
        call_kwargs = mock_detect.call_args[1]
        self.assertAlmostEqual(call_kwargs["threshold"], 3.0)


if __name__ == "__main__":
    unittest.main()
