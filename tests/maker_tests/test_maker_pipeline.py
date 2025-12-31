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
    ToolCatalogProcessor,
    ToolCatalogProducer,
    ToolCatalogRequest,
    ToolCatalogRequestConsumer,
    ToolCatalogResult,
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
        # With BaseProducer pattern, error messages go in diagnostics
        envelope = ResultEnvelope(status="error", diagnostics={"message": "Something went wrong"})
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
        # With BaseProducer pattern, error messages go in diagnostics
        envelope = ResultEnvelope(status="error", diagnostics={"message": "[maker] test.module exited with code 2"})
        with redirect_stdout(buf):
            ToolResultProducer().produce(envelope)
        self.assertIn("test.module", buf.getvalue())
        self.assertIn("exited with code 2", buf.getvalue())

    def test_tool_result_producer_error_with_message(self):
        buf = io.StringIO()
        # With BaseProducer pattern, error messages go in diagnostics
        envelope = ResultEnvelope(status="error", diagnostics={"message": "[maker] test.module: Import failed"})
        with redirect_stdout(buf):
            ToolResultProducer().produce(envelope)
        self.assertIn("Import failed", buf.getvalue())
        self.assertIn("test.module", buf.getvalue())


class ToolCatalogProcessorTests(TestCase):
    """Tests for the new SafeProcessor-based ToolCatalogProcessor."""

    def setUp(self):
        self.tools_root = repo_root() / "maker"

    def test_processor_discovers_tools(self):
        """ToolCatalogProcessor scans directories and returns ToolCatalogResult."""
        request = ToolCatalogRequest(tools_root=self.tools_root)
        env = ToolCatalogProcessor().process(ToolCatalogRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIsInstance(env.payload, ToolCatalogResult)
        self.assertGreater(len(env.payload.specs), 0)
        self.assertIn("Available maker tools:", env.payload.text)

    def test_processor_empty_directory(self):
        """ToolCatalogProcessor handles empty directories gracefully."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            request = ToolCatalogRequest(tools_root=Path(tmp))
            env = ToolCatalogProcessor().process(ToolCatalogRequestConsumer(request).consume())
            self.assertTrue(env.ok())
            self.assertEqual(len(env.payload.specs), 0)
            self.assertEqual(env.payload.text, "No maker tools found.")

    def test_processor_handles_nonexistent_directory(self):
        """ToolCatalogProcessor raises error for nonexistent directory."""
        request = ToolCatalogRequest(tools_root=Path("/nonexistent/path"))
        env = ToolCatalogProcessor().process(ToolCatalogRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertIn("message", env.diagnostics)

    def test_request_consumer_returns_request(self):
        """ToolCatalogRequestConsumer returns the original request."""
        request = ToolCatalogRequest(tools_root=Path("/some/path"))
        consumer = ToolCatalogRequestConsumer(request)
        result = consumer.consume()
        self.assertIs(result, request)


class ToolCatalogProducerTests(TestCase):
    """Tests for the new BaseProducer-based ToolCatalogProducer."""

    def test_producer_prints_text(self):
        """ToolCatalogProducer prints the text from ToolCatalogResult."""
        specs = [ToolSpec(relative_path=Path("card/gen.py"), module="maker.card.gen")]
        result = ToolCatalogResult(specs=specs, text="Available maker tools:\n- maker/card/gen.py")
        env = ResultEnvelope(status="success", payload=result)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ToolCatalogProducer().produce(env)
        self.assertIn("Available maker tools:", buf.getvalue())
        self.assertIn("maker/card/gen.py", buf.getvalue())

    def test_producer_handles_error(self):
        """ToolCatalogProducer prints error message on failure."""
        env = ResultEnvelope(status="error", diagnostics={"message": "Failed to scan"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            ToolCatalogProducer().produce(env)
        self.assertIn("Failed to scan", buf.getvalue())

    def test_producer_empty_catalog(self):
        """ToolCatalogProducer handles empty catalog."""
        result = ToolCatalogResult(specs=[], text="No maker tools found.")
        env = ResultEnvelope(status="success", payload=result)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ToolCatalogProducer().produce(env)
        self.assertIn("No maker tools found.", buf.getvalue())


class ToolCatalogResultTests(TestCase):
    """Tests for ToolCatalogResult dataclass."""

    def test_result_attributes(self):
        """ToolCatalogResult stores specs and text."""
        specs = [ToolSpec(relative_path=Path("a/b.py"), module="maker.a.b")]
        result = ToolCatalogResult(specs=specs, text="test text")
        self.assertEqual(len(result.specs), 1)
        self.assertEqual(result.text, "test text")

    def test_result_empty(self):
        """ToolCatalogResult can be empty."""
        result = ToolCatalogResult(specs=[], text="No tools")
        self.assertEqual(result.specs, [])


class ToolCatalogRequestTests(TestCase):
    """Tests for ToolCatalogRequest dataclass."""

    def test_request_stores_path(self):
        """ToolCatalogRequest stores tools_root path."""
        path = Path("/some/maker/path")
        request = ToolCatalogRequest(tools_root=path)
        self.assertEqual(request.tools_root, path)
