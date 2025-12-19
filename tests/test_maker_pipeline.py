import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from core.pipeline import ResultEnvelope
from maker.pipeline import (
    ConsoleProducer,
    ModuleResultProducer,
    ModuleRunnerProcessor,
    ToolCatalogConsumer,
    ToolCatalogFormatter,
    ToolRequest,
    ToolRequestConsumer,
)


class MakerPipelineTests(TestCase):
    def setUp(self):
        self.tools_root = Path(__file__).resolve().parents[1] / "maker"

    def test_catalog_consumer_discovers_tools(self):
        catalog = ToolCatalogConsumer(self.tools_root).consume()
        self.assertTrue(any(spec.relative_path.match("card/*.py") for spec in catalog))

    def test_catalog_formatter_outputs_rows(self):
        catalog = ToolCatalogConsumer(self.tools_root).consume()
        output = ToolCatalogFormatter().process(catalog[:2])
        self.assertIn("maker/", output)

    def test_module_runner_invokes_python_module(self):
        req = ToolRequest(module="maker.card.gen_snug_variants", args=["--dry-run"])
        consumer = ToolRequestConsumer(req)
        processor = ModuleRunnerProcessor()
        with patch("maker.pipeline.subprocess.call", return_value=0) as fake_call:
            with patch("maker.pipeline.sys.executable", "python"):
                envelope = processor.process(consumer.consume())
        fake_call.assert_called_once_with(["python", "-m", req.module, "--dry-run"])
        self.assertTrue(envelope.ok())

    def test_module_result_producer_reports_failure(self):
        buf = io.StringIO()
        envelope = ResultEnvelope(status="error", payload=2)
        with redirect_stdout(buf):
            ModuleResultProducer().produce(envelope)
        self.assertIn("tool exited with code 2", buf.getvalue())

    def test_console_producer_prints_text(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ConsoleProducer().produce("hello")
        self.assertEqual("hello\n", buf.getvalue())
