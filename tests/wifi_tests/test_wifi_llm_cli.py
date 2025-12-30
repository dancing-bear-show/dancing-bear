"""Tests for wifi/llm_cli.py LLM CLI utilities."""

import sys
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import capture_stdout, repo_root


class TestWifiLLMCLI(unittest.TestCase):
    """Test wifi LLM CLI commands."""

    def _import_mod(self):
        root = repo_root()
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(root.parent))
        import wifi.llm_cli as mod  # type: ignore

        return mod

    def test_agentic_stdout(self):
        mod = self._import_mod()
        with capture_stdout() as buf:
            rc = mod.main(["agentic", "--stdout"])
        self.assertEqual(rc, 0)
        self.assertIn("agentic: wifi", buf.getvalue())

    def test_derive_all_outputs_files(self):
        mod = self._import_mod()
        with tempfile.TemporaryDirectory() as td:
            rc = mod.main(["derive-all", "--out-dir", td, "--include-generated", "--stdout"])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(td) / "AGENTIC_WIFI.md").exists())
            self.assertTrue((Path(td) / "DOMAIN_MAP_WIFI.md").exists())


class TestWifiLLMCLIInternals(unittest.TestCase):
    """Test internal functions and configuration of wifi.llm_cli."""

    def _import_mod(self):
        root = repo_root()
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(root.parent))
        import wifi.llm_cli as mod

        return mod

    def test_agentic_function_returns_string(self):
        mod = self._import_mod()
        result = mod._agentic()
        self.assertIsInstance(result, str)
        self.assertIn("wifi", result.lower())

    def test_domain_map_function_returns_string(self):
        mod = self._import_mod()
        result = mod._domain_map()
        self.assertIsInstance(result, str)

    def test_inventory_function_returns_string(self):
        mod = self._import_mod()
        result = mod._inventory()
        self.assertIsInstance(result, str)
        self.assertIn("Inventory", result)

    def test_familiar_compact_function_returns_string(self):
        mod = self._import_mod()
        result = mod._familiar_compact()
        self.assertIsInstance(result, str)
        # Should contain YAML-like structure
        self.assertTrue("meta:" in result or "steps:" in result or "name:" in result)

    def test_familiar_extended_function_returns_string(self):
        mod = self._import_mod()
        result = mod._familiar_extended()
        self.assertIsInstance(result, str)
        self.assertIn("meta:", result)
        self.assertIn("steps:", result)

    def test_policies_function_returns_string(self):
        mod = self._import_mod()
        result = mod._policies()
        self.assertIsInstance(result, str)
        self.assertIn("policies", result.lower())

    def test_config_has_required_fields(self):
        mod = self._import_mod()
        config = mod.CONFIG
        self.assertEqual(config.prog, "llm")
        self.assertIn("Wi-Fi", config.description)
        self.assertIsNotNone(config.agentic)
        self.assertIsNotNone(config.domain_map)
        self.assertIsNotNone(config.inventory)
        self.assertIsNotNone(config.familiar_compact)
        self.assertIsNotNone(config.familiar_extended)
        self.assertIsNotNone(config.policies)
        self.assertEqual(config.agentic_filename, "AGENTIC_WIFI.md")
        self.assertEqual(config.domain_map_filename, "DOMAIN_MAP_WIFI.md")

    def test_build_parser_returns_parser(self):
        mod = self._import_mod()
        parser = mod.build_parser()
        self.assertIsNotNone(parser)
        # Should have common subcommands
        help_text = parser.format_help()
        self.assertIn("agentic", help_text)

    def test_domain_map_stdout(self):
        mod = self._import_mod()
        with capture_stdout():
            rc = mod.main(["domain-map", "--stdout"])
        self.assertEqual(rc, 0)

    def test_inventory_stdout(self):
        mod = self._import_mod()
        with capture_stdout():
            rc = mod.main(["inventory", "--stdout"])
        self.assertEqual(rc, 0)

    def test_familiar_stdout(self):
        mod = self._import_mod()
        with capture_stdout():
            rc = mod.main(["familiar", "--stdout"])
        self.assertEqual(rc, 0)

    def test_policies_stdout(self):
        mod = self._import_mod()
        with capture_stdout():
            rc = mod.main(["policies", "--stdout"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
