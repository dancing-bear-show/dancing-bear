"""Tests for worker agentic capsule and --agentic flag support.

Adopts both shared contracts:
- AgenticBuilderContractMixin: covers build_agentic_capsule / emit_agentic_context
- AgenticCLIContractMixin: covers main(["--agentic"]) / --agentic-format / --agentic-compact

worker hand-writes its capsule (no build_domain_map, no CLI tree), so both
EXPECT_DOMAIN_MAP and EXPECT_CLI_TREE are set False. The mixin asserts that
build_domain_map is genuinely absent.

worker wires agentic manually (to preserve its legacy no-subcommand exit code
of 1), so AgenticCLIContractMixin targets worker.cli directly.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.agentic_builder_contract import AgenticBuilderContractMixin
from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_separator_contract import SeparatorContractMixin


class TestWorkerAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    """The shared agentic builder contract."""

    MODULE_PATH = "worker.agentic"
    APP_ID = "worker"
    EXPECT_CLI_TREE = False
    EXPECT_DOMAIN_MAP = False


class TestWorkerAgenticCLIContract(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract.

    worker wires agentic manually to preserve its legacy no-subcommand exit
    code (1), so the contract targets worker.cli directly.
    """

    MODULE_PATH = "worker.cli"
    APP_ID = "worker"


class TestWorkerCapsuleContent(unittest.TestCase):
    """worker-specific capsule content not covered by the shared contract."""

    def test_build_agentic_capsule_contains_subcommands(self):
        from worker.agentic import build_agentic_capsule

        capsule = build_agentic_capsule()
        for cmd in ("enqueue", "run-once", "daemon", "list", "status", "purge"):
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, capsule)


class TestWorkerMainAgenticExtra(unittest.TestCase):
    """worker-specific CLI behaviour not covered by the shared contract."""

    def test_no_subcommand_preserves_legacy_exit_code(self):
        """The legacy no-subcommand exit code (1) must be unchanged."""
        from worker.cli import main

        with patch("builtins.print") as mock_print:
            rc = main([])
        self.assertEqual(rc, 1)
        mock_print.assert_called_once()
        self.assertIn("Usage", mock_print.call_args[0][0])

    def test_no_subcommand_preserves_legacy_message(self):
        """The legacy no-subcommand message must contain the usage string."""
        from worker.cli import main

        captured = []
        with patch("builtins.print", side_effect=lambda *a, **kw: captured.append(a[0])):
            main([])
        self.assertTrue(any("worker" in line for line in captured))



class TestWorkerSeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    """The shared ``--`` separator contract."""

    MODULE_PATH = "worker.cli"
    APP_ID = "worker"

if __name__ == "__main__":
    unittest.main()
