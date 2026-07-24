import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from core.pipeline import ResultEnvelope
from maker.pipeline import (
    ToolCatalogProcessor,
    ToolCatalogRequest,
    ToolCatalogRequestConsumer,
    ToolRequest,
    ToolRequestConsumer,
    ToolRunnerProcessor,
    ToolResultProducer,
)
from tests.fixtures import repo_root


class MakerPipelineTests(TestCase):
    def setUp(self):
        self.tools_root = repo_root() / "maker"

    def test_catalog_processor_discovers_tools(self):
        req = ToolCatalogRequest(tools_root=self.tools_root)
        envelope = ToolCatalogProcessor().process(ToolCatalogRequestConsumer(req).consume())
        self.assertTrue(envelope.ok())
        self.assertTrue(any(spec.relative_path.match("card/*.py") for spec in envelope.payload.specs))

    def test_catalog_processor_formats_text(self):
        req = ToolCatalogRequest(tools_root=self.tools_root)
        envelope = ToolCatalogProcessor().process(ToolCatalogRequestConsumer(req).consume())
        self.assertTrue(envelope.ok())
        self.assertIn("maker/", envelope.payload.text)

    def test_tool_runner_imports_and_calls_entry_point(self):
        req = ToolRequest(module="test_module", entry_point="main")
        consumer = ToolRequestConsumer(req)
        processor = ToolRunnerProcessor()

        mock_module = SimpleNamespace(main=MagicMock(return_value=0))
        with patch("maker.pipeline.import_module", return_value=mock_module) as fake_import:
            envelope = processor.process(consumer.consume())

        fake_import.assert_called_once_with("test_module")
        mock_module.main.assert_called_once()
        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload.return_code, 0)

    def test_tool_runner_handles_missing_entry_point(self):
        req = ToolRequest(module="test_module", entry_point="nonexistent")
        processor = ToolRunnerProcessor()

        mock_module = SimpleNamespace()  # No 'nonexistent' attribute
        with patch("maker.pipeline.import_module", return_value=mock_module):
            envelope = processor.process(ToolRequestConsumer(req).consume())

        self.assertFalse(envelope.ok())
        self.assertIn("no callable", envelope.diagnostics["message"])

    def test_tool_runner_handles_exception(self):
        req = ToolRequest(module="test_module")
        processor = ToolRunnerProcessor()

        with patch("maker.pipeline.import_module", side_effect=ImportError("No such module")):
            envelope = processor.process(ToolRequestConsumer(req).consume())

        self.assertFalse(envelope.ok())
        self.assertIn("No such module", envelope.diagnostics["message"])

    def test_tool_result_producer_reports_failure(self):
        buf = io.StringIO()
        envelope = ResultEnvelope(status="error", diagnostics={"message": "Something went wrong"})
        with redirect_stdout(buf):
            ToolResultProducer().produce(envelope)
        self.assertIn("Something went wrong", buf.getvalue())
