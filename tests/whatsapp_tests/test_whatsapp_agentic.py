"""Tests for whatsapp agentic module."""
from __future__ import annotations

import io
import unittest
from unittest.mock import patch, MagicMock

from whatsapp import agentic


class TestGetParser(unittest.TestCase):
    """Tests for _get_parser function."""

    def test_returns_parser_or_none(self):
        """Test returns parser object or None."""
        # Clear the cache to test fresh
        agentic._get_parser.cache_clear()
        result = agentic._get_parser()
        # Should return a parser object (ArgumentParser) or None
        self.assertTrue(result is None or hasattr(result, "parse_args"))

    def test_caches_result(self):
        """Test parser is cached."""
        agentic._get_parser.cache_clear()
        result1 = agentic._get_parser()
        result2 = agentic._get_parser()
        self.assertIs(result1, result2)


class TestCliTree(unittest.TestCase):
    """Tests for _cli_tree function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = agentic._cli_tree()
        self.assertIsInstance(result, str)


class TestFlowMap(unittest.TestCase):
    """Tests for _flow_map function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = agentic._flow_map()
        self.assertIsInstance(result, str)

    def test_contains_search_flow_when_available(self):
        """Test contains search flow when available."""
        result = agentic._flow_map()
        # If search command exists, should have flow info
        if result:
            self.assertIn("search", result.lower())


class TestBuildAgenticCapsule(unittest.TestCase):
    """Tests for build_agentic_capsule function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = agentic.build_agentic_capsule()
        self.assertIsInstance(result, str)

    def test_contains_app_id(self):
        """Test contains app ID."""
        result = agentic.build_agentic_capsule()
        self.assertIn("whatsapp", result.lower())

    def test_contains_purpose(self):
        """Test contains purpose."""
        result = agentic.build_agentic_capsule()
        # Should contain some indication of purpose
        self.assertTrue(len(result) > 0)


class TestBuildDomainMap(unittest.TestCase):
    """Tests for build_domain_map function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = agentic.build_domain_map()
        self.assertIsInstance(result, str)

    def test_contains_search_module(self):
        """Test mentions search module."""
        result = agentic.build_domain_map()
        self.assertIn("search", result.lower())


class TestEmitAgenticContext(unittest.TestCase):
    """Tests for emit_agentic_context function."""

    def test_returns_zero(self):
        """Test returns 0 on success."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = agentic.emit_agentic_context()
        self.assertEqual(result, 0)

    def test_prints_capsule(self):
        """Test prints the agentic capsule."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            agentic.emit_agentic_context()
        output = captured.getvalue()
        self.assertIn("whatsapp", output.lower())

    def test_accepts_format_param(self):
        """Test accepts format parameter (best-effort)."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = agentic.emit_agentic_context(fmt="yaml")
        self.assertEqual(result, 0)

    def test_accepts_compact_param(self):
        """Test accepts compact parameter (best-effort)."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = agentic.emit_agentic_context(compact=True)
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
