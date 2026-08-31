"""Tests for charts agentic capsule and --agentic flag integration."""

import unittest
from unittest.mock import patch

from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.fixtures import capture_stdout


class TestChartsAgenticCapsule(unittest.TestCase):
    """Tests for charts/agentic.py."""

    def test_build_returns_string(self):
        from charts.agentic import build_agentic_capsule
        result = build_agentic_capsule()
        self.assertIsInstance(result, str)

    def test_contains_agentic_header(self):
        from charts.agentic import build_agentic_capsule
        self.assertIn("agentic: charts", build_agentic_capsule())

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

    def test_emit_returns_zero(self):
        from charts.agentic import emit_agentic_context
        with capture_stdout():
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)

    def test_emit_accepts_fmt_and_compact(self):
        from charts.agentic import emit_agentic_context
        for fmt in ("text", "yaml", "json"):
            with capture_stdout():
                rc = emit_agentic_context(fmt, False)
            self.assertEqual(rc, 0)

    def test_emit_prints_capsule(self):
        from charts.agentic import build_agentic_capsule, emit_agentic_context
        with capture_stdout() as buf:
            emit_agentic_context()
        self.assertEqual(buf.getvalue(), build_agentic_capsule() + "\n")


class TestChartsAgenticCLIContract(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract.

    charts wires agentic manually to preserve its legacy no-subcommand exit
    code, so it goes through charts.cli rather than a __main__ shim.
    """

    MODULE_PATH = "charts.cli"
    APP_ID = "charts"


class TestChartsAgenticFlag(unittest.TestCase):
    """charts-specific flag behaviour not covered by the shared contract."""

    def test_agentic_flag_yaml_format(self):
        from charts.cli import main
        with capture_stdout() as buf:
            rc = main(["--agentic", "--agentic-format", "yaml", "--agentic-compact"])
        self.assertEqual(rc, 0)
        self.assertIn("agentic: charts", buf.getvalue())

    def test_no_subcommand_exits_one(self):
        """Legacy exit code must remain 1 when no subcommand given."""
        from charts.cli import main
        with patch("argparse.ArgumentParser.print_help"):
            rc = main([])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
