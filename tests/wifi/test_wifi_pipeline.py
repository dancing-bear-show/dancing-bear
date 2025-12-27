import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from core.pipeline import ResultEnvelope
from wifi.diagnostics import DiagnoseConfig, DnsResult, Report
from wifi.pipeline import (
    DiagnoseProcessor,
    DiagnoseProducer,
    DiagnoseRequest,
    DiagnoseRequestConsumer,
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
        condition="ok",
    )


class WifiPipelineTests(TestCase):
    def test_processor_success(self):
        report = _sample_report()
        with patch("wifi.pipeline.run_diagnosis", return_value=report) as fake_run:
            request = DiagnoseRequest(config=DiagnoseConfig(ping_targets=["1.1.1.1"]))
            env = DiagnoseProcessor().process(DiagnoseRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIs(env.payload.report, report)  # type: ignore[union-attr]
        fake_run.assert_called_once()

    def test_producer_writes_json(self):
        report = _sample_report()
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "wifi.json"
            payload = DiagnoseResult(report=report, emit_json=True, out_path=out_path)
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                DiagnoseProducer().produce(env)
            self.assertTrue(out_path.exists())
            content = out_path.read_text(encoding="utf-8")
            self.assertIn('"condition": "ok"', content)
            self.assertIn('"condition": "ok"', buf.getvalue())


if __name__ == "__main__":
    import unittest

    unittest.main()
