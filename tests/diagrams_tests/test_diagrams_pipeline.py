"""Tests for RenderDiagramProcessor, RenderDiagramProducer, and LocalRenderer._run().

C8 coverage targets:
  - RenderDiagramProcessor: happy-path (full consumer → processor → producer chain)
    and sad-path (each distinct raise site in _process_safe).
  - RenderDiagramProducer: success path and error path.
  - LocalRenderer._run(): subprocess.TimeoutExpired and non-zero returncode paths
    (both were previously untested per the audit).
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from tests.diagrams_tests._renderer_helpers import make_failed_result, make_renderer

if TYPE_CHECKING:
    from diagrams.renderers import LocalRenderer, RenderRequest


# ---------------------------------------------------------------------------
# LocalRenderer._run — subprocess error paths (audit gap)
# ---------------------------------------------------------------------------


class TestLocalRendererRunTimeout(unittest.TestCase):
    """LocalRenderer._run() raises LocalRendererError on TimeoutExpired."""

    def _make_renderer(self) -> "LocalRenderer":
        return make_renderer(timeout=5)

    def test_timeout_expired_raises_local_renderer_error(self):
        from diagrams.renderers import LocalRendererError

        renderer = self._make_renderer()
        exc = subprocess.TimeoutExpired(cmd=["mmdc"], timeout=5)
        with patch("subprocess.run", side_effect=exc):
            with self.assertRaises(LocalRendererError) as ctx:
                renderer._run(["mmdc", "-i", "in.mmd", "-o", "out.svg"])
        self.assertIn("timed out", str(ctx.exception))

    def test_timeout_message_includes_timeout_value(self):
        from diagrams.renderers import LocalRendererError

        renderer = self._make_renderer()
        exc = subprocess.TimeoutExpired(cmd=["mmdc"], timeout=5)
        with patch("subprocess.run", side_effect=exc):
            with self.assertRaises(LocalRendererError) as ctx:
                renderer._run(["mmdc"])
        # Message should mention the configured timeout
        self.assertIn("5", str(ctx.exception))


class TestLocalRendererRunNonZeroExit(unittest.TestCase):
    """LocalRenderer._run() raises LocalRendererError when mmdc exits non-zero."""

    def _make_renderer(self) -> "LocalRenderer":
        return make_renderer()

    def _make_failed_result(self, stderr: bytes = b"mmdc error output") -> MagicMock:
        return make_failed_result(stderr)

    def test_nonzero_returncode_raises_local_renderer_error(self):
        from diagrams.renderers import LocalRendererError

        renderer = self._make_renderer()
        with patch("subprocess.run", return_value=self._make_failed_result()):
            with self.assertRaises(LocalRendererError):
                renderer._run(["mmdc", "-i", "in.mmd", "-o", "out.svg"])

    def test_nonzero_returncode_includes_stderr_in_message(self):
        from diagrams.renderers import LocalRendererError

        renderer = self._make_renderer()
        stderr_text = b"Parse error: unexpected token"
        with patch("subprocess.run", return_value=self._make_failed_result(stderr=stderr_text)):
            with self.assertRaises(LocalRendererError) as ctx:
                renderer._run(["mmdc"])
        self.assertIn("Parse error", str(ctx.exception))

    def test_zero_returncode_does_not_raise(self):
        renderer = self._make_renderer()
        success = MagicMock()
        success.returncode = 0
        success.stderr = b""
        with patch("subprocess.run", return_value=success):
            # _run should complete without raising
            renderer._run(["mmdc", "-i", "in.mmd", "-o", "out.svg"])


# ---------------------------------------------------------------------------
# RenderDiagramProcessor — _process_safe raise sites
# ---------------------------------------------------------------------------


class TestRenderDiagramProcessorSadPaths(unittest.TestCase):
    """Each distinct raise site in _process_safe surfaces as a CLIError envelope."""

    def _make_request(self, output: str = "/tmp/out.svg") -> "RenderRequest":  # nosec B108 - test string only
        from diagrams.renderers import RenderRequest

        return RenderRequest(source="flowchart LR\n    A-->B", output=output)

    def test_mmdc_not_found_produces_error_envelope(self):
        """LocalRendererError on construction → error ResultEnvelope."""
        from diagrams.renderers import LocalRendererError, RenderDiagramProcessor

        with patch("diagrams.renderers.LocalRenderer", side_effect=LocalRendererError("mmdc not found")):
            envelope = RenderDiagramProcessor().process(self._make_request())

        self.assertFalse(envelope.ok())
        self.assertIn("mmdc not found", (envelope.diagnostics or {}).get("message", ""))

    def test_render_to_file_failure_produces_error_envelope(self):
        """LocalRendererError from render_to_file → error ResultEnvelope."""
        from diagrams.renderers import LocalRendererError, RenderDiagramProcessor

        mock_renderer = MagicMock()
        mock_renderer.render_to_file.side_effect = LocalRendererError("mmdc failed: bad syntax")
        with patch("diagrams.renderers.LocalRenderer", return_value=mock_renderer):
            envelope = RenderDiagramProcessor().process(self._make_request())

        self.assertFalse(envelope.ok())
        self.assertIn("mmdc failed", (envelope.diagnostics or {}).get("message", ""))

    def test_local_renderer_error_is_cli_error_subtype(self):
        """LocalRendererError is a CLIError subclass (C5 invariant)."""
        from core.cli_errors import CLIError, ExitCode
        from diagrams.renderers import LocalRendererError

        err = LocalRendererError("test")
        self.assertIsInstance(err, CLIError)
        self.assertEqual(err.code, ExitCode.ERROR)


# ---------------------------------------------------------------------------
# RenderDiagramProcessor — happy path (consumer → processor → producer chain)
# ---------------------------------------------------------------------------


class TestRenderDiagramProcessorHappyPath(unittest.TestCase):
    """Full pipeline: process() returns a success envelope with RenderResult."""

    def test_successful_render_returns_success_envelope_with_result(self):
        from diagrams.renderers import RenderDiagramProcessor, RenderRequest, RenderResult

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = str(Path(tmpdir) / "out.svg")
            # Write a dummy output file so stat() succeeds
            Path(output_path).write_text("<svg/>")

            request = RenderRequest(source="flowchart LR\n    A-->B", output=output_path)

            mock_renderer = MagicMock()
            mock_renderer.render_to_file.return_value = output_path
            with patch("diagrams.renderers.LocalRenderer", return_value=mock_renderer):
                envelope = RenderDiagramProcessor().process(request)

        self.assertTrue(envelope.ok())
        self.assertIsInstance(envelope.payload, RenderResult)
        self.assertEqual(envelope.payload.output_path, output_path)
        self.assertGreater(envelope.payload.size_bytes, 0)
        from diagrams.renderers import RenderOptions
        mock_renderer.render_to_file.assert_called_once_with(
            "flowchart LR\n    A-->B",
            output_path,
            RenderOptions(output_format=None, background=None, theme=None, width=None, height=None),
        )

    def test_render_request_fields_forwarded_to_renderer(self):
        """All RenderRequest fields are forwarded to render_to_file."""
        from diagrams.renderers import RenderDiagramProcessor, RenderRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = str(Path(tmpdir) / "out.png")
            Path(output_path).write_text("PNG")

            request = RenderRequest(
                source="flowchart LR\n    A-->B",
                output=output_path,
                output_format="png",
                background="white",
                theme="default",
                width=800,
                height=600,
                timeout=30,
            )

            mock_renderer = MagicMock()
            mock_renderer.render_to_file.return_value = output_path
            with patch("diagrams.renderers.LocalRenderer", return_value=mock_renderer):
                envelope = RenderDiagramProcessor().process(request)

        self.assertTrue(envelope.ok())
        from diagrams.renderers import RenderOptions
        mock_renderer.render_to_file.assert_called_once_with(
            "flowchart LR\n    A-->B",
            output_path,
            RenderOptions(output_format="png", background="white", theme="default", width=800, height=600),
        )


# ---------------------------------------------------------------------------
# RenderDiagramProducer — success and error paths
# ---------------------------------------------------------------------------


class TestRenderDiagramProducerSuccessPath(unittest.TestCase):
    """RenderDiagramProducer.produce() emits 'Rendered to:' on success."""

    def test_produce_success_prints_rendered_to_path(self):
        from core.pipeline import ResultEnvelope
        from diagrams.renderers import RenderDiagramProducer, RenderResult

        payload = RenderResult(output_path="/out/diagram.svg", size_bytes=1024)
        envelope = ResultEnvelope(status="success", payload=payload)

        buf = StringIO()
        with patch("sys.stdout", buf):
            RenderDiagramProducer().produce(envelope)

        self.assertIn("Rendered to:", buf.getvalue())
        self.assertIn("/out/diagram.svg", buf.getvalue())

    def test_produce_success_does_not_print_to_stderr(self):
        from core.pipeline import ResultEnvelope
        from diagrams.renderers import RenderDiagramProducer, RenderResult

        payload = RenderResult(output_path="/out/diagram.svg", size_bytes=512)
        envelope = ResultEnvelope(status="success", payload=payload)

        err_buf = StringIO()
        with patch("sys.stderr", err_buf):
            RenderDiagramProducer().produce(envelope)

        self.assertEqual(err_buf.getvalue(), "")


class TestRenderDiagramProducerErrorPath(unittest.TestCase):
    """RenderDiagramProducer.produce() emits error message on failure envelope."""

    def test_produce_error_prints_error_message(self):
        from core.pipeline import ResultEnvelope
        from diagrams.renderers import RenderDiagramProducer

        envelope = ResultEnvelope(
            status="error",
            diagnostics={"message": "mmdc failed: render error"},
        )

        err_buf = StringIO()
        with patch("sys.stderr", err_buf):
            RenderDiagramProducer().produce(envelope)

        self.assertIn("mmdc failed", err_buf.getvalue())

    def test_produce_error_with_no_message_does_not_crash(self):
        """Envelope with empty diagnostics should not raise."""
        from core.pipeline import ResultEnvelope
        from diagrams.renderers import RenderDiagramProducer

        envelope = ResultEnvelope(status="error", diagnostics={})
        # Should complete without exception
        RenderDiagramProducer().produce(envelope)


# ---------------------------------------------------------------------------
# Full consumer → processor → producer integration (via run_pipeline)
# ---------------------------------------------------------------------------


class TestRenderPipelineIntegration(unittest.TestCase):
    """run_pipeline(request, RenderDiagramProcessor, RenderDiagramProducer) returns 0 on success."""

    def test_run_pipeline_returns_0_on_success(self):
        from core.pipeline import run_pipeline
        from diagrams.renderers import RenderDiagramProcessor, RenderDiagramProducer, RenderRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = str(Path(tmpdir) / "out.svg")
            Path(output_path).write_text("<svg/>")

            request = RenderRequest(source="flowchart LR\n    A-->B", output=output_path)

            mock_renderer = MagicMock()
            mock_renderer.render_to_file.return_value = output_path
            with patch("diagrams.renderers.LocalRenderer", return_value=mock_renderer):
                buf = StringIO()
                with patch("sys.stdout", buf):
                    rc = run_pipeline(request, RenderDiagramProcessor, RenderDiagramProducer)

        self.assertEqual(rc, 0)
        self.assertIn("Rendered to:", buf.getvalue())

    def test_run_pipeline_returns_nonzero_on_failure(self):
        from core.pipeline import run_pipeline
        from diagrams.renderers import LocalRendererError, RenderDiagramProcessor, RenderDiagramProducer, RenderRequest

        request = RenderRequest(source="flowchart LR\n    A-->B", output="/tmp/out.svg")  # nosec B108 - test string only

        with patch("diagrams.renderers.LocalRenderer", side_effect=LocalRendererError("mmdc missing")):
            err_buf = StringIO()
            with patch("sys.stderr", err_buf):
                rc = run_pipeline(request, RenderDiagramProcessor, RenderDiagramProducer)

        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
