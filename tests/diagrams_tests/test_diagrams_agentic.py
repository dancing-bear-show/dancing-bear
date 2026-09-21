"""Tests for diagrams agentic capsule and --agentic flag integration.

Adopts both shared contracts:
- AgenticBuilderContractMixin: covers build_agentic_capsule / emit_agentic_context
- AgenticCLIContractMixin: covers main(["--agentic"]) / --agentic-format / --agentic-compact

diagrams hand-writes its capsule (no build_domain_map, no CLI tree), so both
EXPECT_DOMAIN_MAP and EXPECT_CLI_TREE are set False. The mixin asserts that
build_domain_map is genuinely absent, so the flags cannot silently mask a
regression.

diagrams wires agentic manually (to preserve its legacy no-subcommand exit code
of 0), so AgenticCLIContractMixin targets diagrams.cli rather than a __main__
shim.
"""

import unittest
from io import StringIO
from unittest.mock import patch

from tests.agentic_builder_contract import AgenticBuilderContractMixin
from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_separator_contract import SeparatorContractMixin
from tests.cli_no_subcommand_contract import NoSubcommandContractMixin
from tests.fixtures import capture_stdout


class TestDiagramsAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    """The shared agentic builder contract."""

    MODULE_PATH = "diagrams.agentic"
    APP_ID = "diagrams"
    EXPECT_CLI_TREE = False
    EXPECT_DOMAIN_MAP = False


class TestDiagramsAgenticCLIContract(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract.

    diagrams wires agentic manually to preserve its legacy no-subcommand exit
    code (0), so the contract targets diagrams.cli directly.
    """

    MODULE_PATH = "diagrams.cli"
    APP_ID = "diagrams"


class TestDiagramsCapsuleContent(unittest.TestCase):
    """diagrams-specific capsule content not covered by the shared contract."""

    def test_contains_from_yaml_command(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertIn("from-yaml", build_agentic_capsule())

    def test_contains_render_command(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertIn("render", build_agentic_capsule())

    def test_contains_validate_command(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertIn("validate", build_agentic_capsule())

    def test_contains_embed_command(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertIn("embed", build_agentic_capsule())

    def test_contains_telemetry_command(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertIn("telemetry", build_agentic_capsule())

    def test_idempotent(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertEqual(build_agentic_capsule(), build_agentic_capsule())


class TestDiagramsAgenticFlagExtra(unittest.TestCase):
    """diagrams-specific flag behaviour not covered by the shared contract."""

    def test_agentic_flag_yaml_format(self):
        """YAML format output still announces the app."""
        from diagrams.cli import main
        with capture_stdout() as buf:
            rc = main(["--agentic", "--agentic-format", "yaml", "--agentic-compact"])
        self.assertEqual(rc, 0)
        self.assertIn("agentic: diagrams", buf.getvalue())

    def test_no_subcommand_exits_zero(self):
        """Legacy exit code must remain 0 when no subcommand given."""
        from diagrams.cli import main
        with patch("sys.stdout", StringIO()):
            rc = main([])
        self.assertEqual(rc, 0)



class TestDiagramsSeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    """The shared ``--`` separator contract."""

    MODULE_PATH = "diagrams.cli"
    APP_ID = "diagrams"


class TestDiagramsNoSubcommand(NoSubcommandContractMixin, unittest.TestCase):
    """Rule A7 — the no-subcommand exit code is deliberate."""

    MODULE_PATH = "diagrams.cli"
    EXPECTED_RC = 0
    EXPECTED_STREAM = "stdout"

if __name__ == "__main__":
    unittest.main()
