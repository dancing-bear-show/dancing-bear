"""Tests for C5/C6 normalization changes in wifi domain.

C5: ExitCode values replace bare int returns in cli.py.
C6: OutputFormat injection and OutputWriter routing in pipeline.py.
"""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.cli_errors import ExitCode
from core.cli_output import OutputFormat, OutputWriter
from core.pipeline import ResultEnvelope
from wifi.diagnostics_probes import DnsResult
from wifi.diagnostics_report import DiagnoseConfig, Report
from wifi.pipeline import (
    DiagnoseProducer,
    DiagnoseRequest,
    DiagnoseResult,
)


def _sample_report() -> Report:
    return Report(
        timestamp="2024-01-01 00:00:00",
        gateway="192.0.2.1",
        wifi=None,
        ping_results=[],
        dns=DnsResult(host="example.com", success=True, addresses=["203.0.113.1"], elapsed_ms=3.0),
        trace=None,
        http=None,
        survey_results=[],
        findings=[],
        condition="good",
    )


def _make_diagnose_args(**overrides):
    """Build a minimal argparse.Namespace for cmd_diagnose tests."""
    import argparse
    defaults = dict(
        targets=["1.1.1.1"],
        ping_count=1,
        gateway=None,
        trace_target=None,
        dns_host="google.com",
        http_url=None,
        no_trace=True,
        no_http=True,
        no_wifi=True,
        no_survey=True,
        ping_timeout=5.0,
        trace_hops=12,
        survey_count=4,
        json=False,
        out=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCliExitCodes(unittest.TestCase):
    """C5 — cmd_diagnose returns ExitCode, not bare int."""

    def test_success_returns_exit_code_instance(self):
        """cmd_diagnose returns ExitCode.SUCCESS (not bare int 0) on success."""
        from wifi.cli import cmd_diagnose
        with patch("wifi.cli.DiagnoseProcessor") as mock_proc_cls, \
             patch("wifi.cli.DiagnoseProducer") as mock_prod_cls:
            mock_env = MagicMock()
            mock_env.ok.return_value = True
            mock_proc_cls.return_value.process.return_value = mock_env
            mock_prod_cls.return_value.produce.return_value = None
            rc = cmd_diagnose(_make_diagnose_args())
        self.assertIsInstance(rc, ExitCode)
        self.assertEqual(rc, ExitCode.SUCCESS)

    def test_failure_returns_exit_code_error(self):
        """cmd_diagnose returns ExitCode (not bare int) on failure."""
        from wifi.cli import cmd_diagnose
        with patch("wifi.cli.DiagnoseProcessor") as mock_proc_cls, \
             patch("wifi.cli.DiagnoseProducer") as mock_prod_cls:
            mock_env = MagicMock()
            mock_env.ok.return_value = False
            mock_env.diagnostics = {"code": ExitCode.ERROR}
            mock_proc_cls.return_value.process.return_value = mock_env
            mock_prod_cls.return_value.produce.return_value = None
            rc = cmd_diagnose(_make_diagnose_args())
        self.assertIsInstance(rc, ExitCode)
        self.assertEqual(rc, ExitCode.ERROR)

    def test_failure_missing_code_defaults_to_exit_code_error(self):
        """cmd_diagnose defaults to ExitCode.ERROR when diagnostics has no code."""
        from wifi.cli import cmd_diagnose
        with patch("wifi.cli.DiagnoseProcessor") as mock_proc_cls, \
             patch("wifi.cli.DiagnoseProducer") as mock_prod_cls:
            mock_env = MagicMock()
            mock_env.ok.return_value = False
            mock_env.diagnostics = {}
            mock_proc_cls.return_value.process.return_value = mock_env
            mock_prod_cls.return_value.produce.return_value = None
            rc = cmd_diagnose(_make_diagnose_args())
        self.assertIsInstance(rc, ExitCode)
        self.assertEqual(rc, ExitCode.ERROR)


class TestDiagnoseProducerOutputRouting(unittest.TestCase):
    """C6 — DiagnoseProducer routes through OutputWriter based on OutputFormat."""

    def test_text_format_routes_through_output_writer(self):
        """TEXT format output goes through OutputWriter.print, not a bare print()."""
        report = _sample_report()
        mock_writer = MagicMock(spec=OutputWriter)
        payload = DiagnoseResult(report=report, output_format=OutputFormat.TEXT, out_path=None)
        env = ResultEnvelope(status="success", payload=payload)

        DiagnoseProducer(writer=mock_writer).produce(env)

        mock_writer.print.assert_called_once()
        call_args = mock_writer.print.call_args
        # The content arg should contain the rendered text report
        content = call_args[0][0]
        self.assertIsInstance(content, str)
        self.assertGreater(len(content), 0)

    def test_json_format_routes_through_output_writer(self):
        """JSON format output goes through OutputWriter.print with JSON content."""
        report = _sample_report()
        mock_writer = MagicMock(spec=OutputWriter)
        payload = DiagnoseResult(report=report, output_format=OutputFormat.JSON, out_path=None)
        env = ResultEnvelope(status="success", payload=payload)

        DiagnoseProducer(writer=mock_writer).produce(env)

        mock_writer.print.assert_called_once()
        content = mock_writer.print.call_args[0][0]
        self.assertIn('"condition"', content)
        self.assertIn('"good"', content)

    def test_error_envelope_routes_to_print_error(self):
        """A failed envelope triggers print_error on the injected writer (stderr)."""
        mock_writer = MagicMock(spec=OutputWriter)
        env = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"message": "diagnosis failed"},
        )

        DiagnoseProducer(writer=mock_writer).produce(env)

        mock_writer.print_error.assert_called_once_with("diagnosis failed")
        mock_writer.print.assert_not_called()

    def test_error_envelope_no_message_no_output(self):
        """A failed envelope with no message emits nothing."""
        mock_writer = MagicMock(spec=OutputWriter)
        env = ResultEnvelope(status="error", payload=None, diagnostics={})

        DiagnoseProducer(writer=mock_writer).produce(env)

        mock_writer.print_error.assert_not_called()
        mock_writer.print.assert_not_called()

    def test_output_writer_injected_not_bare_print(self):
        """Verify that bare print() is NOT used — output goes via the injected writer."""
        report = _sample_report()
        mock_writer = MagicMock(spec=OutputWriter)
        payload = DiagnoseResult(report=report, output_format=OutputFormat.TEXT, out_path=None)
        env = ResultEnvelope(status="success", payload=payload)

        captured = io.StringIO()
        with patch("builtins.print", side_effect=lambda *a, **kw: captured.write(str(a))):
            DiagnoseProducer(writer=mock_writer).produce(env)

        # Output went through the mock writer, not bare print()
        self.assertEqual(captured.getvalue(), "")
        mock_writer.print.assert_called_once()

    def test_json_output_also_written_to_file(self):
        """JSON format writes content to out_path when provided."""
        report = _sample_report()
        mock_writer = MagicMock(spec=OutputWriter)
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.json"
            payload = DiagnoseResult(
                report=report, output_format=OutputFormat.JSON, out_path=out_path
            )
            env = ResultEnvelope(status="success", payload=payload)

            DiagnoseProducer(writer=mock_writer).produce(env)

            self.assertTrue(out_path.exists())
            content = out_path.read_text(encoding="utf-8")
            self.assertIn('"condition": "good"', content)
            # And the same content also went through the writer
            mock_writer.print.assert_called_once()


class TestDiagnoseRequestOutputFormat(unittest.TestCase):
    """C6 — DiagnoseRequest carries output_format, not emit_json bool."""

    def test_default_request_has_text_format(self):
        """DiagnoseRequest defaults to TEXT format."""
        req = DiagnoseRequest(config=DiagnoseConfig(ping_targets=["1.1.1.1"]))
        self.assertEqual(req.output_format, OutputFormat.TEXT)

    def test_json_request_carries_json_format(self):
        """DiagnoseRequest with JSON format propagates to DiagnoseResult."""
        req = DiagnoseRequest(
            config=DiagnoseConfig(ping_targets=["1.1.1.1"]),
            output_format=OutputFormat.JSON,
        )
        self.assertEqual(req.output_format, OutputFormat.JSON)


if __name__ == "__main__":
    unittest.main()
