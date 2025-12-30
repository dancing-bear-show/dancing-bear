import io
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from core.pipeline import ResultEnvelope
from maker.pipeline import (
    ConsoleProducer,
    ToolCatalogConsumer,
    ToolCatalogFormatter,
    ToolRequest,
    ToolRequestConsumer,
    ToolResult,
    ToolRunnerProcessor,
    ToolResultProducer,
    ToolSpec,
)
from tests.fixtures import repo_root


class MakerPipelineTests(TestCase):
    def setUp(self):
        self.tools_root = repo_root() / "maker"

    def test_catalog_consumer_discovers_tools(self):
        catalog = ToolCatalogConsumer(self.tools_root).consume()
        self.assertTrue(any(spec.relative_path.match("card/*.py") for spec in catalog))

    def test_catalog_formatter_outputs_rows(self):
        catalog = ToolCatalogConsumer(self.tools_root).consume()
        output = ToolCatalogFormatter().process(catalog[:2])
        self.assertIn("maker/", output)

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
        self.assertIn("no callable", envelope.payload.error)

    def test_tool_runner_handles_exception(self):
        req = ToolRequest(module="test_module")
        processor = ToolRunnerProcessor()

        with patch("maker.pipeline.import_module", side_effect=ImportError("No such module")):
            envelope = processor.process(ToolRequestConsumer(req).consume())

        self.assertFalse(envelope.ok())
        self.assertIn("No such module", envelope.payload.error)

    def test_tool_result_producer_reports_failure(self):
        buf = io.StringIO()
        result = ToolResult(module="test.module", return_code=2, error="Something went wrong")
        envelope = ResultEnvelope(status="error", payload=result)
        with redirect_stdout(buf):
            ToolResultProducer().produce(envelope)
        self.assertIn("Something went wrong", buf.getvalue())

    def test_console_producer_prints_text(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ConsoleProducer().produce("hello")
        self.assertEqual("hello\n", buf.getvalue())

    # ToolSpec tests
    def test_tool_spec_display_row(self):
        spec = ToolSpec(relative_path=Path("card/gen_snug_variants.py"), module="maker.card.gen_snug_variants")
        self.assertEqual("- maker/card/gen_snug_variants.py", spec.display_row())

    def test_tool_spec_display_row_nested_path(self):
        spec = ToolSpec(relative_path=Path("foo/bar/baz.py"), module="maker.foo.bar.baz")
        self.assertEqual("- maker/foo/bar/baz.py", spec.display_row())

    # ToolCatalogFormatter tests
    def test_catalog_formatter_empty_list(self):
        output = ToolCatalogFormatter().process([])
        self.assertEqual("No maker tools found.", output)

    def test_catalog_formatter_single_item(self):
        specs = [ToolSpec(relative_path=Path("card/gen.py"), module="maker.card.gen")]
        output = ToolCatalogFormatter().process(specs)
        self.assertIn("Available maker tools:", output)
        self.assertIn("- maker/card/gen.py", output)

    # ToolRequest tests
    def test_tool_request_defaults(self):
        req = ToolRequest(module="test.module")
        self.assertEqual("test.module", req.module)
        self.assertEqual("main", req.entry_point)

    def test_tool_request_custom_entry_point(self):
        req = ToolRequest(module="test.module", entry_point="run")
        self.assertEqual("run", req.entry_point)

    # ToolRequestConsumer tests
    def test_tool_request_consumer_returns_request(self):
        req = ToolRequest(module="test.module", entry_point="execute")
        consumer = ToolRequestConsumer(req)
        result = consumer.consume()
        self.assertEqual(req, result)
        self.assertEqual("execute", result.entry_point)

    # ToolResult tests
    def test_tool_result_success(self):
        result = ToolResult(module="test.module", return_code=0)
        self.assertEqual("test.module", result.module)
        self.assertEqual(0, result.return_code)
        self.assertIsNone(result.error)

    def test_tool_result_with_error(self):
        result = ToolResult(module="test.module", return_code=1, error="Failed")
        self.assertEqual(1, result.return_code)
        self.assertEqual("Failed", result.error)

    # ToolRunnerProcessor tests
    def test_tool_runner_with_non_zero_return_code(self):
        req = ToolRequest(module="test_module", entry_point="main")
        processor = ToolRunnerProcessor()

        mock_module = SimpleNamespace(main=MagicMock(return_value=42))
        with patch("maker.pipeline.import_module", return_value=mock_module):
            envelope = processor.process(ToolRequestConsumer(req).consume())

        self.assertTrue(envelope.ok())
        self.assertEqual(42, envelope.payload.return_code)

    def test_tool_runner_with_none_return_value(self):
        req = ToolRequest(module="test_module", entry_point="main")
        processor = ToolRunnerProcessor()

        mock_module = SimpleNamespace(main=MagicMock(return_value=None))
        with patch("maker.pipeline.import_module", return_value=mock_module):
            envelope = processor.process(ToolRequestConsumer(req).consume())

        self.assertTrue(envelope.ok())
        self.assertEqual(0, envelope.payload.return_code)

    def test_tool_runner_with_custom_entry_point(self):
        req = ToolRequest(module="test_module", entry_point="execute")
        processor = ToolRunnerProcessor()

        mock_module = SimpleNamespace(execute=MagicMock(return_value=0))
        with patch("maker.pipeline.import_module", return_value=mock_module):
            envelope = processor.process(ToolRequestConsumer(req).consume())

        mock_module.execute.assert_called_once()
        self.assertTrue(envelope.ok())

    # ToolResultProducer tests
    def test_tool_result_producer_success_silent(self):
        buf = io.StringIO()
        result = ToolResult(module="test.module", return_code=0)
        envelope = ResultEnvelope(status="success", payload=result)
        with redirect_stdout(buf):
            ToolResultProducer().produce(envelope)
        self.assertEqual("", buf.getvalue())

    def test_tool_result_producer_non_zero_exit_code(self):
        buf = io.StringIO()
        result = ToolResult(module="test.module", return_code=2)
        envelope = ResultEnvelope(status="error", payload=result)
        with redirect_stdout(buf):
            ToolResultProducer().produce(envelope)
        self.assertIn("test.module", buf.getvalue())
        self.assertIn("exited with code 2", buf.getvalue())

    def test_tool_result_producer_error_with_message(self):
        buf = io.StringIO()
        result = ToolResult(module="test.module", return_code=1, error="Import failed")
        envelope = ResultEnvelope(status="error", payload=result)
        with redirect_stdout(buf):
            ToolResultProducer().produce(envelope)
        self.assertIn("Import failed", buf.getvalue())
        self.assertIn("test.module", buf.getvalue())
