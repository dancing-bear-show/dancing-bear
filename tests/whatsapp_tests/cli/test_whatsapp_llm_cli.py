"""Tests for whatsapp.llm_cli.

Includes:
1. The shared LLM CLI contract via LLMCLIContractMixin.
2. Assertions on the values whatsapp feeds into the shared builders. The
   builder implementations come from core.llm_builders and are common to
   every domain; only the configuration they are constructed with is
   whatsapp-specific.
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
# Domain-specific tests for CONFIG builder callables.
# The private helpers were removed when the module was migrated to
# make_domain_llm_module; these tests now call through CONFIG.
# ------------------------------------------------------------------


class TestAgenticBuilder(unittest.TestCase):
    """Tests for CONFIG.agentic builder."""

    def test_returns_string(self):
        result = llm_cli.CONFIG.agentic()
        self.assertIsInstance(result, str)

    def test_contains_whatsapp(self):
        result = llm_cli.CONFIG.agentic()
        self.assertIn("whatsapp", result.lower())

    def test_result_is_nonempty(self):
        result = llm_cli.CONFIG.agentic()
        self.assertGreater(len(result), 0)


class TestDomainMapBuilder(unittest.TestCase):
    """Tests for CONFIG.domain_map builder."""

    def test_returns_string(self):
        result = llm_cli.CONFIG.domain_map()
        self.assertIsInstance(result, str)


class TestInventoryBuilder(unittest.TestCase):
    """Tests for CONFIG.inventory builder."""

    def test_returns_string(self):
        result = llm_cli.CONFIG.inventory()
        self.assertIsInstance(result, str)

    def test_contains_content(self):
        result = llm_cli.CONFIG.inventory()
        self.assertGreater(len(result), 0)


class TestFamiliarCompactBuilder(unittest.TestCase):
    """Tests for CONFIG.familiar_compact builder."""

    def test_returns_string(self):
        result = llm_cli.CONFIG.familiar_compact()
        self.assertIsInstance(result, str)

    def test_contains_yaml_structure(self):
        result = llm_cli.CONFIG.familiar_compact()
        self.assertGreater(len(result), 0)
        # Both keys are required: a capsule with steps but no meta block, or
        # vice versa, is not a valid familiarization capsule.
        self.assertIn("meta:", result)
        self.assertIn("steps:", result)


class TestFamiliarExtendedBuilder(unittest.TestCase):
    """Tests for CONFIG.familiar_extended builder."""

    def test_returns_string(self):
        result = llm_cli.CONFIG.familiar_extended()
        self.assertIsInstance(result, str)

    def test_returns_fallback(self):
        from whatsapp.meta import META

        result = llm_cli.CONFIG.familiar_extended()
        self.assertEqual(result, META.familiar_extended_fallback)


class TestPoliciesBuilder(unittest.TestCase):
    """Tests for CONFIG.policies builder."""

    def test_returns_string(self):
        result = llm_cli.CONFIG.policies()
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
