"""Tests for telemetry/otel/health.py."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from telemetry.otel.health import (
    _print_no_infrastructure_message,
    check_otel_infrastructure,
    require_otel_infrastructure,
)
from telemetry.otel.reader import OTLPDataDir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _data_dir(path: str | Path) -> OTLPDataDir:
    return OTLPDataDir(path=Path(path))


# ---------------------------------------------------------------------------
# check_otel_infrastructure
# ---------------------------------------------------------------------------

class TestCheckOtelInfrastructure(unittest.TestCase):
    def test_directory_does_not_exist_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            # Point to a non-existent sub-directory
            missing = Path(td) / "nonexistent"
            with patch("telemetry.otel.health.OTLPDataDir.from_env", return_value=_data_dir(missing)):
                buf = io.StringIO()
                with redirect_stderr(buf):
                    result = check_otel_infrastructure()
                self.assertFalse(result)

    def test_directory_exists_but_no_telemetry_files_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            # Directory exists but none of metrics/events/spans.jsonl present
            with patch("telemetry.otel.health.OTLPDataDir.from_env", return_value=_data_dir(td)):
                buf = io.StringIO()
                with redirect_stderr(buf):
                    result = check_otel_infrastructure()
                self.assertFalse(result)

    def test_directory_with_metrics_file_returns_true(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "metrics.jsonl").write_text("")
            with patch("telemetry.otel.health.OTLPDataDir.from_env", return_value=_data_dir(td)):
                result = check_otel_infrastructure()
            self.assertTrue(result)

    def test_directory_with_events_file_returns_true(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "events.jsonl").write_text("")
            with patch("telemetry.otel.health.OTLPDataDir.from_env", return_value=_data_dir(td)):
                result = check_otel_infrastructure()
            self.assertTrue(result)

    def test_directory_with_spans_file_returns_true(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "spans.jsonl").write_text("")
            with patch("telemetry.otel.health.OTLPDataDir.from_env", return_value=_data_dir(td)):
                result = check_otel_infrastructure()
            self.assertTrue(result)

    def test_directory_with_multiple_files_returns_true(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "metrics.jsonl").write_text("")
            (Path(td) / "events.jsonl").write_text("")
            with patch("telemetry.otel.health.OTLPDataDir.from_env", return_value=_data_dir(td)):
                result = check_otel_infrastructure()
            self.assertTrue(result)

    def test_unrelated_file_does_not_satisfy_check(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "other.log").write_text("")
            with patch("telemetry.otel.health.OTLPDataDir.from_env", return_value=_data_dir(td)):
                buf = io.StringIO()
                with redirect_stderr(buf):
                    result = check_otel_infrastructure()
                self.assertFalse(result)

    def test_missing_dir_prints_to_stderr(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "nonexistent"
            with patch("telemetry.otel.health.OTLPDataDir.from_env", return_value=_data_dir(missing)):
                buf = io.StringIO()
                with redirect_stderr(buf):
                    check_otel_infrastructure()
                output = buf.getvalue()
                self.assertIn("OpenTelemetry infrastructure not found", output)

    def test_no_files_prints_to_stderr(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("telemetry.otel.health.OTLPDataDir.from_env", return_value=_data_dir(td)):
                buf = io.StringIO()
                with redirect_stderr(buf):
                    check_otel_infrastructure()
                output = buf.getvalue()
                self.assertIn("OpenTelemetry infrastructure not found", output)


# ---------------------------------------------------------------------------
# _print_no_infrastructure_message
# ---------------------------------------------------------------------------

class TestPrintNoInfrastructureMessage(unittest.TestCase):
    def test_message_contains_data_dir_path(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir_path = Path(td)
            buf = io.StringIO()
            with redirect_stderr(buf):
                _print_no_infrastructure_message(data_dir_path)
            output = buf.getvalue()
            self.assertIn(str(data_dir_path), output)

    def test_message_contains_infrastructure_not_found(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            _print_no_infrastructure_message(Path("/some/path"))
        output = buf.getvalue()
        self.assertIn("OpenTelemetry infrastructure not found", output)

    def test_message_mentions_docker_compose_command(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            _print_no_infrastructure_message(Path("/some/path"))
        output = buf.getvalue()
        self.assertIn("docker compose -f docker-compose.otel.yaml up -d", output)

    def test_message_specifies_grpc_protocol_and_concrete_endpoint(self):
        """Regression test: the endpoint hint must name the gRPC protocol and
        a concrete port, not just vaguely say "matching the collector's port"
        (that ambiguity let a user configure the HTTP port for a gRPC client).
        """
        buf = io.StringIO()
        with redirect_stderr(buf):
            _print_no_infrastructure_message(Path("/some/path"))
        output = buf.getvalue()
        self.assertIn("OTEL_EXPORTER_OTLP_PROTOCOL=grpc", output)
        self.assertIn("OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4327", output)
        self.assertIn("gRPC", output)
        self.assertNotIn("OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4328", output)

    def test_message_written_to_stderr_not_stdout(self):
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf), patch("sys.stderr", stderr_buf):
            _print_no_infrastructure_message(Path("/some/dir"))
        self.assertEqual(stdout_buf.getvalue(), "")
        self.assertIn("OpenTelemetry", stderr_buf.getvalue())

    def test_message_mentions_data_files(self):
        """Message should list the expected telemetry file names."""
        buf = io.StringIO()
        with redirect_stderr(buf):
            _print_no_infrastructure_message(Path("/some/path"))
        output = buf.getvalue()
        self.assertIn("metrics.jsonl", output)
        self.assertIn("events.jsonl", output)
        self.assertIn("spans.jsonl", output)


# ---------------------------------------------------------------------------
# require_otel_infrastructure
# ---------------------------------------------------------------------------

class TestRequireOtelInfrastructure(unittest.TestCase):
    def test_returns_normally_when_infrastructure_present(self):
        with patch("telemetry.otel.health.check_otel_infrastructure", return_value=True) as mock_check:
            # Should not raise
            require_otel_infrastructure()
        mock_check.assert_called_once()

    def test_raises_system_exit_when_infrastructure_missing(self):
        with patch("telemetry.otel.health.check_otel_infrastructure", return_value=False):
            with self.assertRaises(SystemExit) as ctx:
                require_otel_infrastructure()
            self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
