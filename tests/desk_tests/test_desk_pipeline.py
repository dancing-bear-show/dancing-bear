import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase

from desk.pipeline import (
    ApplyProcessor,
    ApplyRequest,
    ApplyResultProducer,
    PlanProcessor,
    PlanRequest,
    ReportProducer,
    ScanProcessor,
    ScanRequest,
)


class DeskPipelineTests(TestCase):
    def test_scan_processor_uses_runner(self):
        captured = {}

        def fake_runner(**kwargs):
            captured.update(kwargs)
            return {"ok": True}

        request = ScanRequest(
            paths=["~/Downloads"],
            min_size="10MB",
            older_than="7d",
            include_duplicates=True,
            top_dirs=5,
        )
        result = ScanProcessor(runner=fake_runner).process(request)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured["min_size"], "10MB")

    def test_plan_processor_returns_plan(self):
        def fake_planner(path: str):
            return {"generated_from": path}

        request = PlanRequest(config_path="~/rules.yaml")
        result = PlanProcessor(planner=fake_planner).process(request)
        self.assertEqual(result["generated_from"], "~/rules.yaml")

    def test_report_producer_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "report.json"
            ReportProducer(str(out_path)).produce({"a": 1})
            data = json.loads(out_path.read_text())
            self.assertEqual(data["a"], 1)

    def test_apply_processor_success_and_failure(self):
        request = ApplyRequest(plan_path="plan.yaml", dry_run=True)
        success = ApplyProcessor(applier=lambda p, dry_run=False: None).process(request)
        self.assertTrue(success.ok())

        def boom(_path, dry_run=False):
            raise RuntimeError("fail")

        failure = ApplyProcessor(applier=boom).process(request)
        self.assertFalse(failure.ok())
        self.assertIn("fail", failure.diagnostics["message"])

    def test_apply_result_producer_reports_error(self):
        buf = io.StringIO()
        envelope = ApplyProcessor(applier=lambda *_: None).process(
            ApplyRequest("plan.yaml", False)
        )
        envelope.status = "error"
        envelope.diagnostics = {"message": "oops"}
        with redirect_stdout(buf):
            ApplyResultProducer().produce(envelope)
        self.assertIn("oops", buf.getvalue())
