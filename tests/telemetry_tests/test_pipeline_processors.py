"""Tests for SafeProcessor/BaseProducer pipeline pairs introduced in normalize-domains.

Covers:
  - CostScanProcessor / CostScanProducer  (src/telemetry/otel/cli/cost.py)
  - TranscriptParseProcessor / TranscriptParseProducer  (src/telemetry/parse_transcripts.py)

Each pair has:
  - One happy-path test: consumer -> processor -> producer, asserting on actual output.
  - One sad-path test per distinct raise site in _process_safe, asserting the correct
    CLIError subtype or error envelope surfaces via ResultEnvelope.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.cli_output import OutputWriter
from core.pipeline import RequestConsumer, ResultEnvelope


# ---------------------------------------------------------------------------
# Shared helpers — use shared_fixtures where applicable, avoid local duplication
# ---------------------------------------------------------------------------

def _make_output_writer() -> tuple[OutputWriter, io.StringIO]:
    """Return an OutputWriter backed by a StringIO for inspection."""
    from core.cli_output import OutputConfig
    buf = io.StringIO()
    writer = OutputWriter(config=OutputConfig(file=buf))
    return writer, buf


# ---------------------------------------------------------------------------
# CostScanProcessor / CostScanProducer
# ---------------------------------------------------------------------------

class TestCostScanProcessorHappyPath(unittest.TestCase):
    """Consumer -> CostScanProcessor -> CostScanProducer happy path."""

    def _make_request(self, data_dir_path: Path) -> "CostScanRequest":  # noqa: F821
        from telemetry.otel.cli.cost import CostScanRequest
        from telemetry.otel.reader import OTLPDataDir
        return CostScanRequest(
            data_dir=OTLPDataDir(path=data_dir_path),
            since=None,
            breakdown="none",
            sort_key="time",
            fmt="table",
        )

    def test_happy_path_returns_success_envelope(self) -> None:
        """CostScanProcessor returns a success envelope when get_all_costs succeeds."""
        from telemetry.otel.cli.cost import CostScanProcessor
        from telemetry.otel.cost_models import CostMetrics

        fake_metrics = CostMetrics(
            total_api_calls=5,
            total_input_tokens=1000,
            total_output_tokens=400,
            total_cache_creation_tokens=50,
            total_cache_read_tokens=200,
            total_cost=0.05,
            total_cache_savings=0.01,
            efficiency_ratio=0.4,
            by_session=[],
            by_model=[],
        )
        with tempfile.TemporaryDirectory() as td:
            request = self._make_request(Path(td))
            with patch("telemetry.otel.cli.cost.get_all_costs", return_value=fake_metrics):
                envelope = CostScanProcessor().process(RequestConsumer(request).consume())

        self.assertTrue(envelope.ok())
        result = envelope.unwrap()
        self.assertIsNotNone(result)
        self.assertEqual(result.metrics.total_api_calls, 5)
        self.assertAlmostEqual(result.metrics.total_cost, 0.05)

    def test_happy_path_producer_renders_cost_summary(self) -> None:
        """CostScanProducer._produce_success writes cost summary to OutputWriter."""
        from telemetry.otel.cli.cost import CostScanProducer, CostScanResult
        from telemetry.otel.cost_models import CostMetrics

        metrics = CostMetrics(
            total_api_calls=3,
            total_input_tokens=800,
            total_output_tokens=300,
            total_cache_creation_tokens=20,
            total_cache_read_tokens=100,
            total_cost=0.03,
            total_cache_savings=0.005,
            efficiency_ratio=0.375,
            by_session=[],
            by_model=[],
        )
        result = CostScanResult(metrics=metrics)
        writer, buf = _make_output_writer()
        producer = CostScanProducer(writer=writer)
        producer._produce_success(result, {"fmt": "table", "breakdown": "none", "sort_key": "time"})  # noqa: SLF001

        output = buf.getvalue()
        self.assertIn("0.03", output)
        self.assertIn("800", output)  # input tokens

    def test_sad_path_processor_returns_error_envelope_on_exception(self) -> None:
        """When get_all_costs raises, CostScanProcessor returns an error envelope."""
        from telemetry.otel.cli.cost import CostScanProcessor

        with tempfile.TemporaryDirectory() as td:
            request = self._make_request(Path(td))
            with patch(
                "telemetry.otel.cli.cost.get_all_costs",
                side_effect=RuntimeError("disk read failed"),
            ):
                envelope = CostScanProcessor().process(RequestConsumer(request).consume())

        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.status, "error")
        msg = (envelope.diagnostics or {}).get("message", "")
        self.assertIn("disk read failed", msg)

    def test_sad_path_producer_prints_error_message(self) -> None:
        """When envelope has error status, BaseProducer.produce prints the error to stderr."""
        from telemetry.otel.cli.cost import CostScanProducer

        writer, _ = _make_output_writer()
        producer = CostScanProducer(writer=writer)
        bad_envelope: ResultEnvelope = ResultEnvelope(
            status="error",
            diagnostics={"message": "something went wrong"},
        )
        err_buf = io.StringIO()
        with patch("sys.stderr", err_buf):
            producer.produce(bad_envelope)
        self.assertIn("something went wrong", err_buf.getvalue())


# ---------------------------------------------------------------------------
# TranscriptParseProcessor / TranscriptParseProducer
# ---------------------------------------------------------------------------

class TestTranscriptParseProcessorHappyPath(unittest.TestCase):
    """Consumer -> TranscriptParseProcessor -> TranscriptParseProducer happy path."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmpdir = Path(self._td.name)
        self.projects_dir = self.tmpdir / "projects"
        self.projects_dir.mkdir()
        self.index_dir = self.tmpdir / "index"

    def _write_jsonl(self, rel: str, records: list[dict]) -> Path:
        p = self.projects_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
        return p

    def _make_request(self, **kwargs: object) -> "TranscriptParseRequest":  # noqa: F821
        from telemetry.parse_transcripts import TranscriptParseRequest

        defaults = {
            "since": "all",
            "projects_dir": self.projects_dir,
            "index_dir": self.index_dir,
            "force": False,
            "limit": 0,
        }
        defaults.update(kwargs)  # type: ignore[arg-type]
        return TranscriptParseRequest(**defaults)  # type: ignore[arg-type]

    def test_happy_path_processor_returns_success_envelope(self) -> None:
        """TranscriptParseProcessor returns a success envelope for valid input."""
        from telemetry.parse_transcripts import TranscriptParseProcessor, TranscriptParseResult

        self._write_jsonl("proj/session1.jsonl", [
            {"message": {"role": "user", "content": "Hello world"}}
        ])
        request = self._make_request()
        envelope = TranscriptParseProcessor().process(RequestConsumer(request).consume())

        self.assertTrue(envelope.ok())
        result = envelope.unwrap()
        self.assertIsInstance(result, TranscriptParseResult)
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].prompts_added, 1)
        self.assertEqual(result.results[0].status, "ok")

    def test_happy_path_producer_renders_table(self) -> None:
        """TranscriptParseProducer._produce_success renders a table via _emit_rows (stdout)."""
        from telemetry.parse_transcripts import (
            ParseResult,
            TranscriptParseProducer,
            TranscriptParseResult,
        )

        parse_results = [
            ParseResult(
                session_id="abc123",
                prompts_added=3,
                bash_added=1,
                bytes_processed=500,
                status="ok",
            )
        ]
        result = TranscriptParseResult(results=parse_results)
        writer, _ = _make_output_writer()
        producer = TranscriptParseProducer(writer=writer)
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            producer._produce_success(result, {"fmt": "table"})  # noqa: SLF001

        output = stdout_buf.getvalue()
        self.assertIn("abc123", output)

    def test_happy_path_producer_renders_json(self) -> None:
        """TranscriptParseProducer._produce_success renders JSON rows when fmt=json."""
        from telemetry.parse_transcripts import (
            ParseResult,
            TranscriptParseProducer,
            TranscriptParseResult,
        )

        parse_results = [
            ParseResult(
                session_id="xyz789",
                prompts_added=2,
                bash_added=0,
                bytes_processed=200,
                status="ok",
            )
        ]
        result = TranscriptParseResult(results=parse_results)
        # _produce_success with fmt=json writes to sys.stdout (legacy _emit_rows path)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            from telemetry.parse_transcripts import TranscriptParseProducer
            writer, _ = _make_output_writer()
            producer = TranscriptParseProducer(writer=writer)
            producer._produce_success(result, {"fmt": "json"})  # noqa: SLF001

        output = buf.getvalue()
        data = json.loads(output)
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["session_id"], "xyz789")
        self.assertEqual(data[0]["prompts_added"], 2)

    def test_happy_path_empty_results_prints_no_sessions(self) -> None:
        """TranscriptParseProducer renders 'No sessions processed' when results list is empty."""
        from telemetry.parse_transcripts import TranscriptParseProducer, TranscriptParseResult

        result = TranscriptParseResult(results=[])
        writer, buf = _make_output_writer()
        producer = TranscriptParseProducer(writer=writer)
        producer._produce_success(result, {"fmt": "table"})  # noqa: SLF001

        self.assertIn("No sessions processed", buf.getvalue())

    def test_sad_path_invalid_since_surfaces_as_error_envelope(self) -> None:
        """When since= is invalid, TranscriptParseProcessor returns an error envelope."""
        from telemetry.parse_transcripts import TranscriptParseProcessor

        request = self._make_request(since="badvalue")
        envelope = TranscriptParseProcessor().process(RequestConsumer(request).consume())

        # BadParameter is caught by SafeProcessor's broad except, returned as error envelope
        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.status, "error")
        msg = (envelope.diagnostics or {}).get("message", "")
        self.assertIn("badvalue", msg)

    def test_sad_path_os_error_on_index_dir_creation(self) -> None:
        """When index_dir cannot be created, the processor returns an error envelope."""
        from telemetry.parse_transcripts import TranscriptParseProcessor

        # Point index_dir to a path under a non-existent root that can't be created
        request = self._make_request(
            index_dir=Path("/proc/no-such-dir/deep/index"),
        )
        envelope = TranscriptParseProcessor().process(RequestConsumer(request).consume())

        # Should be an error envelope (PermissionError or OSError propagates)
        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.status, "error")

    def test_sad_path_producer_prints_error_from_bad_envelope(self) -> None:
        """TranscriptParseProducer.produce writes error message for a failed envelope to stderr."""
        from telemetry.parse_transcripts import TranscriptParseProducer

        writer, _ = _make_output_writer()
        producer = TranscriptParseProducer(writer=writer)
        bad_envelope: ResultEnvelope = ResultEnvelope(
            status="error",
            diagnostics={"message": "parse error occurred"},
        )
        err_buf = io.StringIO()
        with patch("sys.stderr", err_buf):
            producer.produce(bad_envelope)
        self.assertIn("parse error occurred", err_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
