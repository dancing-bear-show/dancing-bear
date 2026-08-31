"""Tests for wifi/agentic.py agentic capsule and domain map."""

import unittest

from tests.agentic_builder_contract import AgenticBuilderContractMixin

from wifi.agentic import build_agentic_capsule, build_domain_map


class TestWifiAgenticContract(AgenticBuilderContractMixin, unittest.TestCase):
    """The shared agentic builder contract."""

    MODULE_PATH = "wifi.agentic"
    APP_ID = "wifi"


class TestCoreAgenticSection(unittest.TestCase):
    """Verify wifi/agentic uses core.agentic.section (== Title == format)."""

    def test_probes_section_uses_core_format(self):
        result = build_agentic_capsule()
        self.assertIn("== Probes ==", result)

    def test_cli_tree_section_uses_core_format(self):
        result = build_agentic_capsule()
        self.assertIn("== CLI Tree ==", result)

    def test_domain_map_cli_tree_uses_core_format(self):
        result = build_domain_map()
        self.assertIn("== CLI Tree ==", result)


class TestWifiCapsuleContent(unittest.TestCase):
    """wifi-specific curated content, not part of the shared contract."""

    def test_purpose_names_wifi(self):
        self.assertIn("Wi-Fi", build_agentic_capsule())

    def test_contains_commands(self):
        result = build_agentic_capsule()
        self.assertIn("commands:", result)
        self.assertIn("./bin/wifi", result)

    def test_contains_probes_section(self):
        result = build_agentic_capsule()
        self.assertIn("Probes", result)
        self.assertIn("gateway detection", result)
        self.assertIn("ping sweep", result)
        self.assertIn("DNS timing", result)

    def test_contains_json_output_command(self):
        self.assertIn("--json", build_agentic_capsule())


class TestWifiDomainMapContent(unittest.TestCase):
    """wifi-specific domain map entries."""

    def test_contains_bin_wrapper(self):
        self.assertIn("bin/wifi", build_domain_map())

    def test_contains_core_modules(self):
        result = build_domain_map()
        self.assertIn("wifi/cli.py", result)
        self.assertIn("wifi/pipeline.py", result)
        self.assertIn("wifi/diagnostics_probes.py", result)
        self.assertIn("wifi/agentic.py", result)
        self.assertIn("wifi/llm_cli.py", result)


if __name__ == "__main__":
    unittest.main()
