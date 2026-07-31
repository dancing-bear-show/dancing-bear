"""Tests covering normalize-domains changes to src/phone/:

C2 — ExportProcessor._process_safe no longer wraps exceptions in ValueError;
     LayoutLoadError now propagates through SafeProcessor unchanged.
C5 — LayoutLoadError subclasses CLIError; isinstance check must hold.
C6 — UnusedProducer routes output through OutputWriter, not bare print.
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.cli_errors import CLIError
from core.cli_output import OutputWriter, OutputConfig
from core.pipeline import ResultEnvelope



# ---------------------------------------------------------------------------
# C5: LayoutLoadError subclasses CLIError
# ---------------------------------------------------------------------------


class TestLayoutLoadErrorHierarchy(unittest.TestCase):
    """C5: LayoutLoadError must subclass CLIError."""

    def test_layout_load_error_is_cli_error(self):
        from phone.helpers import LayoutLoadError

        err = LayoutLoadError(2, "no backup found")
        self.assertIsInstance(err, CLIError)

    def test_layout_load_error_is_exception(self):
        from phone.helpers import LayoutLoadError

        err = LayoutLoadError(3, "iconstate not found")
        self.assertIsInstance(err, Exception)

    def test_layout_load_error_code_2_maps_to_usage(self):
        """ExitCode(2) == ExitCode.USAGE — int constructor round-trip."""
        from core.cli_errors import ExitCode
        from phone.helpers import LayoutLoadError

        err = LayoutLoadError(2, "missing backup")
        self.assertEqual(err.code, ExitCode.USAGE)

    def test_layout_load_error_code_3_maps_to_config_error(self):
        """ExitCode(3) == ExitCode.CONFIG_ERROR."""
        from core.cli_errors import ExitCode
        from phone.helpers import LayoutLoadError

        err = LayoutLoadError(3, "no iconstate")
        self.assertEqual(err.code, ExitCode.CONFIG_ERROR)

    def test_layout_load_error_message_preserved(self):
        from phone.helpers import LayoutLoadError

        err = LayoutLoadError(2, "original message")
        self.assertEqual(err.message, "original message")


# ---------------------------------------------------------------------------
# C2: LayoutLoadError propagates through _process_safe — not re-raised as
#     ValueError — SafeProcessor wraps it in the ResultEnvelope as-is.
# ---------------------------------------------------------------------------


class TestExportProcessorLayoutLoadErrorPropagation(unittest.TestCase):
    """C2: LayoutLoadError (not ValueError) is the error type that propagates."""

    def test_layout_load_error_becomes_error_envelope(self):
        """LayoutLoadError raised in _process_safe must produce an error envelope."""
        from phone.helpers import LayoutLoadError
        from phone.pipeline import ExportProcessor, ExportRequest, ExportRequestConsumer

        err = LayoutLoadError(2, "no backup")
        with patch("phone.pipeline_export.load_layout", side_effect=err):
            request = ExportRequest(backup=None, out_path=Path("out.yaml"))
            env = ExportProcessor().process(ExportRequestConsumer(request).consume())

        self.assertFalse(env.ok())
        self.assertIn("no backup", (env.diagnostics or {}).get("message", ""))

    def test_layout_load_error_not_masked_as_value_error(self):
        """The error envelope message must not be empty (old code swallowed type info)."""
        from phone.helpers import LayoutLoadError
        from phone.pipeline import ExportProcessor, ExportRequest, ExportRequestConsumer

        err = LayoutLoadError(2, "sentinel-message")
        with patch("phone.pipeline_export.load_layout", side_effect=err):
            request = ExportRequest(backup=None, out_path=Path("out.yaml"))
            env = ExportProcessor().process(ExportRequestConsumer(request).consume())

        # The original exception message must surface in diagnostics
        self.assertEqual((env.diagnostics or {}).get("message"), "sentinel-message")

    def test_plan_processor_layout_load_error_propagates(self):
        """PlanProcessor also goes through SafeProcessor; LayoutLoadError must surface."""
        from phone.helpers import LayoutLoadError
        from phone.pipeline import PlanProcessor, PlanRequest, PlanRequestConsumer

        err = LayoutLoadError(3, "iconstate missing")
        with patch("phone.pipeline_export.load_layout", side_effect=err):
            request = PlanRequest(layout=None, backup=None, out_path=Path("plan.yaml"))
            env = PlanProcessor().process(PlanRequestConsumer(request).consume())

        self.assertFalse(env.ok())
        self.assertIn("iconstate missing", (env.diagnostics or {}).get("message", ""))

    def test_unused_processor_layout_load_error_propagates(self):
        """UnusedProcessor: LayoutLoadError must reach the envelope, not be lost."""
        from phone.helpers import LayoutLoadError
        from phone.pipeline import (
            UnusedProcessor,
            UnusedRequest,
            UnusedRequestConsumer,
        )

        err = LayoutLoadError(2, "no backup for unused")
        with patch("phone.pipeline_export.load_layout", side_effect=err):
            request = UnusedRequest(
                layout=None,
                backup=None,
                recent_path=None,
                keep_path=None,
                limit=10,
                threshold=0.0,
                format="text",
            )
            env = UnusedProcessor().process(UnusedRequestConsumer(request).consume())

        self.assertFalse(env.ok())
        self.assertIn("no backup for unused", (env.diagnostics or {}).get("message", ""))


# ---------------------------------------------------------------------------
# C6: UnusedProducer routes output through OutputWriter, not bare print
# ---------------------------------------------------------------------------


class TestUnusedProducerOutputWriter(unittest.TestCase):
    """C6: UnusedProducer._produce_success must write via self._writer.print."""

    def _make_text_env(self, rows=None):
        from phone.pipeline import UnusedResult

        if rows is None:
            rows = [("com.example.app", 0.9, "Page 1")]
        payload = UnusedResult(rows=rows, format="text")
        return ResultEnvelope(status="success", payload=payload)

    def _make_csv_env(self, rows=None):
        from phone.pipeline import UnusedResult

        if rows is None:
            rows = [("com.example.app", 0.9, "Page 1")]
        payload = UnusedResult(rows=rows, format="csv")
        return ResultEnvelope(status="success", payload=payload)

    def test_unused_producer_uses_injected_writer_text(self):
        """Injecting a custom OutputWriter redirects text output to its stream."""
        from phone.pipeline import UnusedProducer

        buf = io.StringIO()
        writer = OutputWriter(OutputConfig(file=buf))
        env = self._make_text_env()
        UnusedProducer(writer=writer).produce(env)
        output = buf.getvalue()
        self.assertIn("com.example.app", output)
        self.assertIn("Likely unused", output)

    def test_unused_producer_uses_injected_writer_csv(self):
        """CSV branch also routes through the injected OutputWriter."""
        from phone.pipeline import UnusedProducer

        buf = io.StringIO()
        writer = OutputWriter(OutputConfig(file=buf))
        env = self._make_csv_env()
        UnusedProducer(writer=writer).produce(env)
        output = buf.getvalue()
        self.assertIn("app,score,location", output)
        self.assertIn("com.example.app", output)

    def test_unused_producer_default_writer_does_not_raise(self):
        """Default construction (no injected writer) must not raise."""
        from phone.pipeline import UnusedProducer

        env = self._make_text_env()
        # Just confirm produce() completes; we cannot easily capture stdout here
        # without redirect_stdout, but the absence of exception is the contract.
        try:
            with patch("sys.stdout", new_callable=io.StringIO):
                UnusedProducer().produce(env)
        except Exception as exc:  # nosec B110 - explicit guard: test must not swallow silently
            self.fail(f"UnusedProducer.produce() raised unexpectedly: {exc}")

    def test_unused_producer_calls_writer_print_not_builtin_print(self):
        """OutputWriter.print is called, not the builtin print directly."""
        from phone.pipeline import UnusedProducer

        mock_writer = MagicMock(spec=OutputWriter)
        env = self._make_text_env(rows=[("app1", 1.0, "Dock")])
        UnusedProducer(writer=mock_writer).produce(env)
        # _writer.print must have been called at least once
        self.assertTrue(mock_writer.print.called)

    def test_unused_producer_csv_writer_print_called_per_row(self):
        """CSV: header + one data row = at least 2 writer.print calls."""
        from phone.pipeline import UnusedProducer

        mock_writer = MagicMock(spec=OutputWriter)
        rows = [("app1", 0.9, "Page 1"), ("app2", 0.8, "Page 2")]
        from phone.pipeline import UnusedResult

        payload = UnusedResult(rows=rows, format="csv")
        env = ResultEnvelope(status="success", payload=payload)
        UnusedProducer(writer=mock_writer).produce(env)
        # header line + 2 data rows = 3 calls minimum
        self.assertGreaterEqual(mock_writer.print.call_count, 3)

    def test_unused_producer_empty_rows(self):
        """Empty rows should not raise; only headers printed."""
        from phone.pipeline import UnusedProducer

        buf = io.StringIO()
        writer = OutputWriter(OutputConfig(file=buf))
        from phone.pipeline import UnusedResult

        payload = UnusedResult(rows=[], format="text")
        env = ResultEnvelope(status="success", payload=payload)
        UnusedProducer(writer=writer).produce(env)
        output = buf.getvalue()
        # Headers still printed even with no data rows
        self.assertIn("Likely unused", output)

    def test_unused_producer_error_envelope_not_written(self):
        """Error envelopes must not call _produce_success / writer at all."""
        from phone.pipeline import UnusedProducer

        mock_writer = MagicMock(spec=OutputWriter)
        env = ResultEnvelope(status="error", payload=None, diagnostics={"message": "fail"})
        UnusedProducer(writer=mock_writer).produce(env)
        # _produce_success not called — writer.print should not be invoked
        mock_writer.print.assert_not_called()


if __name__ == "__main__":
    unittest.main()
