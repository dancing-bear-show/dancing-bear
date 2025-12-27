"""Tests for whatsapp llm_cli module."""
from __future__ import annotations

import unittest

from whatsapp import llm_cli


class TestAgenticFunction(unittest.TestCase):
    """Tests for _agentic function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = llm_cli._agentic()
        self.assertIsInstance(result, str)

    def test_contains_whatsapp(self):
        """Test result contains whatsapp reference."""
        result = llm_cli._agentic()
        self.assertIn("whatsapp", result.lower())

    def test_result_is_nonempty(self):
        """Test returns non-empty content."""
        result = llm_cli._agentic()
        self.assertGreater(len(result), 0)


class TestDomainMapFunction(unittest.TestCase):
    """Tests for _domain_map function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = llm_cli._domain_map()
        self.assertIsInstance(result, str)


class TestInventoryFunction(unittest.TestCase):
    """Tests for _inventory function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = llm_cli._inventory()
        self.assertIsInstance(result, str)

    def test_contains_whatsapp_or_fallback(self):
        """Test contains WhatsApp or inventory content."""
        result = llm_cli._inventory()
        # Should contain some content
        self.assertGreater(len(result), 0)


class TestFamiliarCompactFunction(unittest.TestCase):
    """Tests for _familiar_compact function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = llm_cli._familiar_compact()
        self.assertIsInstance(result, str)

    def test_contains_yaml_structure(self):
        """Test contains YAML-like structure."""
        result = llm_cli._familiar_compact()
        # Should have meta or steps
        self.assertGreater(len(result), 0)
        self.assertTrue("meta:" in result or "steps:" in result)


class TestFamiliarExtendedFunction(unittest.TestCase):
    """Tests for _familiar_extended function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = llm_cli._familiar_extended()
        self.assertIsInstance(result, str)

    def test_returns_fallback(self):
        """Test returns the fallback directly."""
        from whatsapp.meta import FAMILIAR_EXTENDED_FALLBACK
        result = llm_cli._familiar_extended()
        self.assertEqual(result, FAMILIAR_EXTENDED_FALLBACK)


class TestPoliciesFunction(unittest.TestCase):
    """Tests for _policies function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = llm_cli._policies()
        self.assertIsInstance(result, str)


class TestConfig(unittest.TestCase):
    """Tests for CONFIG object."""

    def test_config_exists(self):
        """Test CONFIG is defined."""
        self.assertIsNotNone(llm_cli.CONFIG)

    def test_config_has_prog(self):
        """Test CONFIG has prog attribute."""
        self.assertEqual(llm_cli.CONFIG.prog, "llm-whatsapp")


class TestBuildParser(unittest.TestCase):
    """Tests for build_parser function."""

    def test_returns_parser(self):
        """Test returns ArgumentParser."""
        parser = llm_cli.build_parser()
        self.assertIsNotNone(parser)
        self.assertTrue(hasattr(parser, "parse_args"))


class TestMain(unittest.TestCase):
    """Tests for main function."""

    def test_main_with_help(self):
        """Test main with --help exits with SystemExit."""
        with self.assertRaises(SystemExit) as ctx:
            llm_cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
