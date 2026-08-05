"""Tests for whatsapp pipeline module."""
from __future__ import annotations

import importlib
import io
import unittest
from unittest.mock import patch

from core.cli_output import OutputFormat
from whatsapp.pipeline import (
    SearchRequest,
    SearchRequestConsumer,
    SearchResult,
    SearchProcessor,
    SearchProducer,
)
from whatsapp.search import MessageRow


class TestSearchRequest(unittest.TestCase):
    """Tests for SearchRequest dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        req = SearchRequest()
        self.assertIsNone(req.db_path)
        self.assertIsNone(req.contains)
        self.assertFalse(req.match_all)
        self.assertIsNone(req.contact)
        self.assertIsNone(req.from_me)
        self.assertIsNone(req.since_days)
        self.assertEqual(req.limit, 50)
        self.assertEqual(req.output_format, OutputFormat.TEXT)

    def test_custom_values(self):
        """Test custom values are set correctly."""
        req = SearchRequest(
            db_path="/path/to/db.sqlite",
            contains=["hello", "world"],
            match_all=True,
            contact="Alice",
            from_me=True,
            since_days=7,
            limit=100,
            output_format=OutputFormat.JSON,
        )
        self.assertEqual(req.db_path, "/path/to/db.sqlite")
        self.assertEqual(req.contains, ["hello", "world"])
        self.assertTrue(req.match_all)
        self.assertEqual(req.contact, "Alice")
        self.assertTrue(req.from_me)
        self.assertEqual(req.since_days, 7)
        self.assertEqual(req.limit, 100)
        self.assertEqual(req.output_format, OutputFormat.JSON)


class TestSearchResult(unittest.TestCase):
    """Tests for SearchResult dataclass."""

    def test_default_output_format(self):
        """Test output_format defaults to OutputFormat.TEXT."""
        result = SearchResult(rows=[])
        self.assertEqual(result.output_format, OutputFormat.TEXT)

    def test_with_rows(self):
        """Test with message rows."""
        rows = [
            MessageRow(ts="2024-01-02", partner="Alice", from_me=1, text="Hello"),
        ]
        result = SearchResult(rows=rows, output_format=OutputFormat.JSON)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.output_format, OutputFormat.JSON)


class TestSearchProcessor(unittest.TestCase):
    """Tests for SearchProcessor."""

    @patch("whatsapp.pipeline.search_messages")
    def test_process_success(self, mock_search):
        """Test successful processing."""
        mock_search.return_value = [
            MessageRow(ts="2024-01-02", partner="Alice", from_me=1, text="Hello"),
        ]

        req = SearchRequest(contains=["hello"])
        processor = SearchProcessor()
        envelope = processor.process(SearchRequestConsumer(req).consume())

        self.assertEqual(envelope.status, "success")
        self.assertIsNotNone(envelope.payload)
        self.assertEqual(len(envelope.payload.rows), 1)

    @patch("whatsapp.pipeline.search_messages")
    def test_process_file_not_found(self, mock_search):
        """Test handling of FileNotFoundError."""
        mock_search.side_effect = FileNotFoundError("DB not found")

        req = SearchRequest()
        processor = SearchProcessor()
        envelope = processor.process(SearchRequestConsumer(req).consume())

        self.assertEqual(envelope.status, "error")
        self.assertIsNone(envelope.payload)
        self.assertIn("DB not found", envelope.diagnostics["message"])

    @patch("whatsapp.pipeline.search_messages")
    def test_process_generic_error(self, mock_search):
        """Test handling of generic exceptions."""
        mock_search.side_effect = Exception("Some error")

        req = SearchRequest()
        processor = SearchProcessor()
        envelope = processor.process(SearchRequestConsumer(req).consume())

        self.assertEqual(envelope.status, "error")
        self.assertIsNone(envelope.payload)
        self.assertIn("Some error", envelope.diagnostics["message"])

    @patch("whatsapp.pipeline.search_messages")
    def test_process_passes_parameters(self, mock_search):
        """Test that parameters are passed correctly."""
        mock_search.return_value = []

        req = SearchRequest(
            db_path="/custom/path",
            contains=["test"],
            match_all=True,
            contact="Bob",
            from_me=False,
            since_days=30,
            limit=25,
        )
        processor = SearchProcessor()
        processor.process(SearchRequestConsumer(req).consume())

        from whatsapp.search import MessageQuery

        mock_search.assert_called_once_with(
            db_path="/custom/path",
            query=MessageQuery(
                contains=["test"],
                match_all=True,
                contact="Bob",
                from_me=False,
                since_days=30,
                limit=25,
            ),
        )


class TestSearchProducer(unittest.TestCase):
    """Tests for SearchProducer."""

    def test_produce_text_output(self):
        """Test producing text output."""
        rows = [
            MessageRow(ts="2024-01-02 10:00", partner="Alice", from_me=1, text="Hello"),
        ]
        result = SearchResult(rows=rows, output_format=OutputFormat.TEXT)

        producer = SearchProducer()

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            producer._produce_success(result, None)

        output = captured.getvalue()
        self.assertIn("2024-01-02 10:00", output)
        self.assertIn("Alice", output)
        self.assertIn("Hello", output)

    def test_produce_json_output(self):
        """Test producing JSON output."""
        rows = [
            MessageRow(ts="2024-01-02 10:00", partner="Alice", from_me=1, text="Hello"),
        ]
        result = SearchResult(rows=rows, output_format=OutputFormat.JSON)

        producer = SearchProducer()

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            producer._produce_success(result, None)

        output = captured.getvalue()
        self.assertIn('"partner": "Alice"', output)
        self.assertIn('"from_me": true', output)


class TestNotFoundErrorSurfaces(unittest.TestCase):
    """C8: NotFoundError (not FileNotFoundError) is raised when DB is missing."""

    @patch("whatsapp.pipeline.search_messages")
    def test_not_found_error_surfaces_as_error_envelope(self, mock_search):
        """NotFoundError from search_messages produces an error-status envelope."""
        from core.cli_errors import NotFoundError

        mock_search.side_effect = NotFoundError("WhatsApp ChatStorage not found: /missing/path")

        req = SearchRequest()
        processor = SearchProcessor()
        envelope = processor.process(SearchRequestConsumer(req).consume())

        self.assertEqual(envelope.status, "error")
        self.assertIsNone(envelope.payload)
        self.assertIn("ChatStorage not found", envelope.diagnostics["message"])

    @patch("whatsapp.pipeline.search_messages")
    def test_success_still_works_when_db_present(self, mock_search):
        """Happy path: SearchProcessor succeeds when search_messages returns rows."""
        mock_search.return_value = [
            MessageRow(ts="2024-06-01 12:00", partner="Bob", from_me=0, text="Hey"),
        ]

        req = SearchRequest(contains=["Hey"])
        processor = SearchProcessor()
        envelope = processor.process(SearchRequestConsumer(req).consume())

        self.assertEqual(envelope.status, "success")
        self.assertIsNotNone(envelope.payload)
        self.assertEqual(len(envelope.payload.rows), 1)


class TestSearchQueryRemoved(unittest.TestCase):
    """C8: SearchQuery no longer exists; domain uses SearchRequest consistently."""

    def test_search_query_not_in_search_module(self):
        """Confirm SearchQuery dataclass was deleted from whatsapp.search."""
        search_mod = importlib.import_module(MessageRow.__module__)
        self.assertFalse(
            hasattr(search_mod, "SearchQuery"),
            "SearchQuery should have been removed from whatsapp.search (C1 deduplication)",
        )

    def test_search_query_not_in_pipeline_module(self):
        """Confirm SearchQuery is not re-exported from whatsapp.pipeline."""
        pipeline_mod = importlib.import_module(SearchRequest.__module__)
        self.assertFalse(
            hasattr(pipeline_mod, "SearchQuery"),
            "SearchQuery should not be present in whatsapp.pipeline",
        )

    def test_search_request_is_canonical_input_type(self):
        """SearchRequest is the canonical search input and is importable."""
        from whatsapp.pipeline import SearchRequest
        req = SearchRequest()
        self.assertIsInstance(req, SearchRequest)
        self.assertEqual(req.output_format, OutputFormat.TEXT)


if __name__ == "__main__":
    unittest.main()
