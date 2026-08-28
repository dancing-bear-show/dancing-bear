"""Tests for whatsapp.llm_cli.

Includes:
1. The shared LLM CLI contract via LLMCLIContractMixin.
2. Domain-specific tests for the private helper functions (_agentic,
   _domain_map, etc.) that are unique to the whatsapp implementation
   and are not part of the shared contract.
"""

from __future__ import annotations

import unittest

from tests.llm_cli_contract import LLMCLIContractMixin
from whatsapp import llm_cli


class TestWhatsappLLMCLI(LLMCLIContractMixin, unittest.TestCase):
    """Shared contract tests for whatsapp.llm_cli."""

    MODULE_PATH = "whatsapp.llm_cli"
    APP_ID = "whatsapp"
    DOC_SUFFIX = "WHATSAPP"
    EXPECTED_PROG = "llm-whatsapp"


# ------------------------------------------------------------------
# Domain-specific tests for private helpers
# These test whatsapp's internal implementation helpers, which are not
# part of the shared contract and should not be in the mixin.
# ------------------------------------------------------------------


class TestAgenticFunction(unittest.TestCase):
    """Tests for _agentic function."""

    def test_returns_string(self):
        result = llm_cli._agentic()
        self.assertIsInstance(result, str)

    def test_contains_whatsapp(self):
        result = llm_cli._agentic()
        self.assertIn("whatsapp", result.lower())

    def test_result_is_nonempty(self):
        result = llm_cli._agentic()
        self.assertGreater(len(result), 0)


class TestDomainMapFunction(unittest.TestCase):
    """Tests for _domain_map function."""

    def test_returns_string(self):
        result = llm_cli._domain_map()
        self.assertIsInstance(result, str)


class TestInventoryFunction(unittest.TestCase):
    """Tests for _inventory function."""

    def test_returns_string(self):
        result = llm_cli._inventory()
        self.assertIsInstance(result, str)

    def test_contains_content(self):
        result = llm_cli._inventory()
        self.assertGreater(len(result), 0)


class TestFamiliarCompactFunction(unittest.TestCase):
    """Tests for _familiar_compact function."""

    def test_returns_string(self):
        result = llm_cli._familiar_compact()
        self.assertIsInstance(result, str)

    def test_contains_yaml_structure(self):
        result = llm_cli._familiar_compact()
        self.assertGreater(len(result), 0)
        self.assertTrue("meta:" in result or "steps:" in result)


class TestFamiliarExtendedFunction(unittest.TestCase):
    """Tests for _familiar_extended function."""

    def test_returns_string(self):
        result = llm_cli._familiar_extended()
        self.assertIsInstance(result, str)

    def test_returns_fallback(self):
        from whatsapp.meta import META

        result = llm_cli._familiar_extended()
        self.assertEqual(result, META.familiar_extended_fallback)


class TestPoliciesFunction(unittest.TestCase):
    """Tests for _policies function."""

    def test_returns_string(self):
        result = llm_cli._policies()
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
