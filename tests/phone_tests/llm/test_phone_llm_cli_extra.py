"""Tests for phone/llm_cli.py — LLM utilities CLI."""
from __future__ import annotations

import unittest


class TestPhoneLlmCliConfig(unittest.TestCase):
    def test_config_exists(self):
        from phone.llm_cli import CONFIG

        self.assertIsNotNone(CONFIG)
        self.assertEqual(CONFIG.prog, "llm")

    def test_agentic_function_returns_string(self):
        from phone.llm_cli import CONFIG

        result = CONFIG.agentic()
        self.assertIsInstance(result, str)
        self.assertIn("phone", result)

    def test_domain_map_function_returns_string(self):
        from phone.llm_cli import CONFIG

        result = CONFIG.domain_map()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_inventory_function_returns_string(self):
        from phone.llm_cli import CONFIG

        result = CONFIG.inventory()
        self.assertIsInstance(result, str)

    def test_familiar_compact_returns_string(self):
        from phone.llm_cli import CONFIG

        result = CONFIG.familiar_compact()
        self.assertIsInstance(result, str)

    def test_familiar_extended_returns_string(self):
        from phone.llm_cli import CONFIG

        result = CONFIG.familiar_extended()
        self.assertIsInstance(result, str)
        self.assertIn("phone", result)

    def test_policies_returns_string(self):
        from phone.llm_cli import CONFIG

        result = CONFIG.policies()
        self.assertIsInstance(result, str)


class TestPhoneLlmCliBuildParser(unittest.TestCase):
    def test_build_parser_returns_parser(self):
        from phone.llm_cli import build_parser
        import argparse

        parser = build_parser()
        self.assertIsInstance(parser, argparse.ArgumentParser)


class TestPhoneLlmCliMain(unittest.TestCase):
    def test_main_with_agentic_returns_zero(self):
        from phone.llm_cli import main

        result = main(["agentic"])
        self.assertEqual(result, 0)

    def test_main_with_domain_map_returns_zero(self):
        from phone.llm_cli import main

        result = main(["domain-map"])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
