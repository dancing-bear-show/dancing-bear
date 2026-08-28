"""Tests for qlty/agentic.py agentic capsule and domain map.

This module had no agentic tests at all: `build_agentic_capsule` and
`build_domain_map` were entirely uncovered, which the shared-contract sweep
surfaced. qlty is one of two domains (with maker) that deliberately builds no
CLI tree, hence EXPECT_CLI_TREE = False.
"""

import unittest

from tests.agentic_builder_contract import AgenticBuilderContractMixin

from qlty.agentic import build_agentic_capsule, build_domain_map


class TestQltyAgenticContract(AgenticBuilderContractMixin, unittest.TestCase):
    """The shared agentic builder contract."""

    MODULE_PATH = "qlty.agentic"
    APP_ID = "qlty"
    EXPECT_CLI_TREE = False


class TestQltyCapsuleContent(unittest.TestCase):
    """qlty-specific curated content, not part of the shared contract."""

    def test_lists_the_wrapper_commands(self):
        capsule = build_agentic_capsule()
        self.assertIn("./bin/qlty-assistant scan", capsule)
        self.assertIn("triage", capsule)
        self.assertIn("rules", capsule)

    def test_records_the_scan_defaults_note(self):
        """scan defaults to --all; the diff-only default is the known trap."""
        self.assertIn("--changed is opt-in", build_agentic_capsule())

    def test_records_that_check_and_smells_are_disjoint(self):
        """Running one hides the other -- the reason scan merges them."""
        self.assertIn("neither is a superset", build_agentic_capsule())

    def test_records_that_counts_are_not_completeness(self):
        self.assertIn("not completeness", build_agentic_capsule())


class TestQltyDomainMapContent(unittest.TestCase):
    """qlty-specific domain map entries."""

    def test_warns_against_the_bin_qlty_name(self):
        """bin/qlty would shadow the real binary; the map says so."""
        domain_map = build_domain_map()
        self.assertIn("bin/qlty-assistant", domain_map)
        self.assertIn("would shadow the real binary", domain_map)

    def test_lists_the_core_modules(self):
        domain_map = build_domain_map()
        for module in (
            "qlty/cli.py",
            "qlty/runner.py",
            "qlty/scanner.py",
            "qlty/strategies.py",
            "qlty/report.py",
            "qlty/models.py",
        ):
            with self.subTest(module=module):
                self.assertIn(module, domain_map)

    def test_domain_map_modules_still_exist(self):
        """The map is a hardcoded string, so it can drift from the package.

        Every path it names must resolve to a real file.
        """
        from pathlib import Path

        import qlty

        package_root = Path(qlty.__file__).resolve().parent.parent
        for line in build_domain_map().splitlines():
            if "qlty/" not in line or "bin/" in line:
                continue
            path = line.lstrip("- ").split(" ")[0]
            with self.subTest(path=path):
                self.assertTrue(
                    (package_root / path).exists(), f"{path} named in domain map but missing"
                )


if __name__ == "__main__":
    unittest.main()
