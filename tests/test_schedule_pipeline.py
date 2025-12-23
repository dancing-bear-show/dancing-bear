import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase

from core.pipeline import ResultEnvelope
from schedule.pipeline import (
    PlanProducer,
    PlanProcessor,
    PlanRequest,
    PlanRequestConsumer,
    PlanResult,
)


class SchedulePipelineTests(TestCase):
    def test_plan_processor_success(self):
        request = PlanRequest(sources=["src"], kind=None, out_path=Path("plan.yaml"))

        def fake_loader(src, kind):
            return [{"subject": "Event", "start": "2025-01-01T10:00:00", "end": "2025-01-01T11:00:00"}]

        env = PlanProcessor(loader=fake_loader).process(PlanRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.document["events"]), 1)  # type: ignore[union-attr]

    def test_plan_processor_handles_error(self):
        request = PlanRequest(sources=["bad"], kind=None, out_path=Path("plan.yaml"))

        def boom(src, kind):
            raise RuntimeError("load failure")

        env = PlanProcessor(loader=boom).process(PlanRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertIn("load failure", env.diagnostics["message"])

    def test_plan_producer_writes_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "plan.yaml"
            payload = PlanResult(document={"events": []}, out_path=out_path)
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                PlanProducer().produce(env)
            self.assertTrue(out_path.exists())
            self.assertIn("Wrote plan", buf.getvalue())
