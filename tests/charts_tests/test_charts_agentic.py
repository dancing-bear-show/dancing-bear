"""Tests for charts agentic capsule and --agentic flag integration.

Adopts both shared contracts:
- AgenticBuilderContractMixin: covers build_agentic_capsule / emit_agentic_context
- AgenticCLIContractMixin: covers main(["--agentic"]) / --agentic-format / --agentic-compact
  (already adopted; retained here unchanged)

charts hand-writes its capsule (no build_domain_map, no CLI tree), so both
EXPECT_DOMAIN_MAP and EXPECT_CLI_TREE are set False. The mixin asserts that
build_domain_map is genuinely absent.

charts wires agentic manually (to preserve its legacy no-subcommand exit code
of 1), so both contracts target charts.cli rather than a __main__ shim.
"""

import unittest
from unittest.mock import patch

from tests.agentic_builder_contract import AgenticBuilderContractMixin
from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_separator_contract import SeparatorContractMixin
from tests.cli_no_subcommand_contract import NoSubcommandContractMixin
from tests.fixtures import capture_stdout


class TestChartsAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    """The shared agentic builder contract."""

    MODULE_PATH = "charts.agentic"
    APP_ID = "charts"
    EXPECT_CLI_TREE = False
    EXPECT_DOMAIN_MAP = False


class TestChartsAgenticCLIContract(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract.

    charts wires agentic manually to preserve its legacy no-subcommand exit
    code, so it goes through charts.cli rather than a __main__ shim.
    """

    MODULE_PATH = "charts.cli"
    APP_ID = "charts"


class TestChartsCapsuleContent(unittest.TestCase):
    """charts-specific capsule content not covered by the shared contract."""

    def test_contains_render_command(self):
        from charts.agentic import build_agentic_capsule
        self.assertIn("render", build_agentic_capsule())

    def test_contains_grid_command(self):
        from charts.agentic import build_agentic_capsule
        self.assertIn("grid", build_agentic_capsule())

    def test_contains_reshape_command(self):
        from charts.agentic import build_agentic_capsule
        self.assertIn("reshape", build_agentic_capsule())

    def test_idempotent(self):
        from charts.agentic import build_agentic_capsule
        self.assertEqual(build_agentic_capsule(), build_agentic_capsule())


class TestChartsAgenticFlag(unittest.TestCase):
    """charts-specific flag behaviour not covered by the shared contract."""

    def test_agentic_flag_yaml_format(self):
        from charts.cli import main
        with capture_stdout() as buf:
            rc = main(["--agentic", "--agentic-format", "yaml", "--agentic-compact"])
        self.assertEqual(rc, 0)
        self.assertIn("agentic: charts", buf.getvalue())

    def test_no_subcommand_prints_help_and_exits_zero(self):
        """Rule A7: help + 0, matching the framework default.

        Previously pinned at 1 as a "legacy exit code", but nothing in the
        source stated why and the value predates the src/ move (#147). Aligned
        with the other 15 apps; worker and workflow keep their non-zero codes,
        which ARE documented and print a one-line usage to stderr.
        """
        from charts.cli import main
        with patch("argparse.ArgumentParser.print_help"):
            rc = main([])
        self.assertEqual(rc, 0)



class TestChartsSeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    """The shared ``--`` separator contract."""

    MODULE_PATH = "charts.cli"
    APP_ID = "charts"


class TestChartsNoSubcommand(NoSubcommandContractMixin, unittest.TestCase):
    """Rule A7 — the no-subcommand exit code is deliberate."""

    MODULE_PATH = "charts.cli"
    EXPECTED_RC = 0
    EXPECTED_STREAM = "stdout"

if __name__ == "__main__":
    unittest.main()
