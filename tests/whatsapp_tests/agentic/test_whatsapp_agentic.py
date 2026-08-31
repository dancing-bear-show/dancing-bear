"""Tests for whatsapp agentic module."""
from __future__ import annotations

import unittest

from tests.agentic_builder_contract import AgenticBuilderContractMixin

from whatsapp import agentic


class TestWhatsappAgenticContract(AgenticBuilderContractMixin, unittest.TestCase):
    """The shared agentic builder contract."""

    MODULE_PATH = "whatsapp.agentic"
    APP_ID = "whatsapp"


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


class TestWhatsappDomainMapContent(unittest.TestCase):
    """whatsapp-specific domain map content."""

    def test_contains_search_module(self):
        """Test mentions search module."""
        result = agentic.build_domain_map()
        self.assertIn("search", result.lower())


if __name__ == "__main__":
    unittest.main()
