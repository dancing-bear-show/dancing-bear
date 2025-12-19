import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from core.pipeline import ResultEnvelope
from phone.layout import NormalizedLayout
from phone.helpers import LayoutLoadError
from phone.pipeline import (
    ChecklistProducer,
    ChecklistProcessor,
    ChecklistResult,
    ChecklistRequest,
    ChecklistRequestConsumer,
    ExportProducer,
    ExportProcessor,
    ExportResult,
    ExportRequest,
    ExportRequestConsumer,
    PlanProducer,
    PlanProcessor,
    PlanResult,
    PlanRequest,
    PlanRequestConsumer,
)


class PhonePipelineTests(TestCase):
    def setUp(self):
        self.layout = NormalizedLayout(dock=["app1"], pages=[[{"kind": "app", "id": "app2"}]])

    def test_export_processor_success(self):
        with patch("phone.pipeline.load_layout", return_value=self.layout):
            request = ExportRequest(backup=None, out_path=Path("out.yaml"))
            env = ExportProcessor().process(ExportRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIn("dock", env.payload.document)  # type: ignore[union-attr]

    def test_export_processor_failure(self):
        err = LayoutLoadError(code=2, message="no backup")
        with patch("phone.pipeline.load_layout", side_effect=err):
            request = ExportRequest(backup=None, out_path=Path("out.yaml"))
            env = ExportProcessor().process(ExportRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertEqual(env.diagnostics["code"], 2)

    def test_export_producer_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "export.yaml"
            payload = ExportResult(document={"dock": []}, out_path=path)
            result = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                ExportProducer().produce(result)
            self.assertTrue(path.exists())
            self.assertIn("Wrote layout export", buf.getvalue())

    def test_plan_processor_generates_plan(self):
        with patch("phone.pipeline.load_layout", return_value=self.layout):
            request = PlanRequest(layout=None, backup=None, out_path=Path("plan.yaml"))
            env = PlanProcessor().process(PlanRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIn("pins", env.payload.document)  # type: ignore[union-attr]

    def test_plan_producer_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.yaml"
            payload = PlanResult(document={"pins": []}, out_path=path)
            result = ResultEnvelope(status="success", payload=payload)
            PlanProducer().produce(result)
            self.assertTrue(path.exists())

    def test_checklist_processor(self):
        plan_data = {"pins": [], "folders": {"Work": ["app2"]}}
        with patch("phone.pipeline.load_layout", return_value=self.layout), patch(
            "phone.pipeline.read_yaml", return_value=plan_data
        ):
            req = ChecklistRequest(
                plan_path=Path("plan.yaml"),
                layout=None,
                backup=None,
                out_path=Path("checklist.txt"),
            )
            env = ChecklistProcessor().process(ChecklistRequestConsumer(req).consume())
        self.assertTrue(env.ok())
        self.assertGreater(len(env.payload.steps), 0)  # type: ignore[union-attr]

    def test_checklist_producer_writes_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checklist.txt"
            payload = ChecklistResult(steps=["step1"], out_path=path)
            env = ResultEnvelope(status="success", payload=payload)
            ChecklistProducer().produce(env)
            self.assertTrue(path.exists())
            self.assertIn("step1", path.read_text())
