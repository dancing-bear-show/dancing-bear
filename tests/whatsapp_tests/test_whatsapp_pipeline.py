"""Tests for whatsapp pipeline module."""
from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from whatsapp.pipeline import (
    SearchRequest,
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
        self.assertFalse(req.emit_json)

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
            emit_json=True,
        )
        self.assertEqual(req.db_path, "/path/to/db.sqlite")
        self.assertEqual(req.contains, ["hello", "world"])
        self.assertTrue(req.match_all)
        self.assertEqual(req.contact, "Alice")
        self.assertTrue(req.from_me)
        self.assertEqual(req.since_days, 7)
        self.assertEqual(req.limit, 100)
        self.assertTrue(req.emit_json)


class TestSearchResult(unittest.TestCase):
    """Tests for SearchResult dataclass."""

    def test_default_emit_json(self):
        """Test emit_json defaults to False."""
        result = SearchResult(rows=[])
        self.assertFalse(result.emit_json)

    def test_with_rows(self):
        """Test with message rows."""
        rows = [
            MessageRow(ts="2024-01-02", partner="Alice", from_me=1, text="Hello"),
        ]
        result = SearchResult(rows=rows, emit_json=True)
        self.assertEqual(len(result.rows), 1)
        self.assertTrue(result.emit_json)


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
        envelope = processor.process(req)

        self.assertEqual(envelope.status, "success")
        self.assertIsNotNone(envelope.payload)
        self.assertEqual(len(envelope.payload.rows), 1)

    @patch("whatsapp.pipeline.search_messages")
    def test_process_file_not_found(self, mock_search):
        """Test handling of FileNotFoundError."""
        mock_search.side_effect = FileNotFoundError("DB not found")

        req = SearchRequest()
        processor = SearchProcessor()
        envelope = processor.process(req)

        self.assertEqual(envelope.status, "error")
        self.assertIsNone(envelope.payload)
        self.assertEqual(envelope.diagnostics["code"], 2)
        self.assertEqual(envelope.diagnostics["hint"], "db_not_found")

    @patch("whatsapp.pipeline.search_messages")
    def test_process_generic_error(self, mock_search):
        """Test handling of generic exceptions."""
        mock_search.side_effect = Exception("Some error")

        req = SearchRequest()
        processor = SearchProcessor()
        envelope = processor.process(req)

        self.assertEqual(envelope.status, "error")
        self.assertIsNone(envelope.payload)
        self.assertEqual(envelope.diagnostics["code"], 1)
        self.assertIn("Some error", envelope.diagnostics["error"])

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
        processor.process(req)

        mock_search.assert_called_once_with(
            db_path="/custom/path",
            contains=["test"],
            match_all=True,
            contact="Bob",
            from_me=False,
            since_days=30,
            limit=25,
        )


class TestSearchProducer(unittest.TestCase):
    """Tests for SearchProducer."""

    def test_produce_text_output(self):
        """Test producing text output."""
        rows = [
            MessageRow(ts="2024-01-02 10:00", partner="Alice", from_me=1, text="Hello"),
        ]
        result = SearchResult(rows=rows, emit_json=False)

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
        result = SearchResult(rows=rows, emit_json=True)

        producer = SearchProducer()

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            producer._produce_success(result, None)

        output = captured.getvalue()
        self.assertIn('"partner": "Alice"', output)
        self.assertIn('"from_me": true', output)


if __name__ == "__main__":
    unittest.main()
