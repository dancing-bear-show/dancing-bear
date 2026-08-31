"""Tests for workflow agentic capsule and --agentic flag support.

Adopts both shared contracts:
- AgenticBuilderContractMixin: covers build_agentic_capsule / emit_agentic_context
- AgenticCLIContractMixin: covers main(["--agentic"]) / --agentic-format / --agentic-compact

workflow hand-writes its capsule (no build_domain_map, no CLI tree), so both
EXPECT_DOMAIN_MAP and EXPECT_CLI_TREE are set False. The mixin asserts that
build_domain_map is genuinely absent.

workflow wires agentic manually via on_no_command= (to preserve its legacy
no-subcommand exit code of ExitCode.USAGE == 2), so AgenticCLIContractMixin
targets workflow.cli directly.
"""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from tests.agentic_builder_contract import AgenticBuilderContractMixin
from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_separator_contract import SeparatorContractMixin
from tests.cli_no_subcommand_contract import NoSubcommandContractMixin


class TestWorkflowAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    """The shared agentic builder contract."""

    MODULE_PATH = "workflow.agentic"
    APP_ID = "workflow"
    EXPECT_CLI_TREE = False
    EXPECT_DOMAIN_MAP = False


class TestWorkflowAgenticCLIContract(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract.

    workflow wires agentic manually via on_no_command= to preserve its legacy
    no-subcommand exit code (ExitCode.USAGE == 2), so the contract targets
    workflow.cli directly.
    """

    MODULE_PATH = "workflow.cli"
    APP_ID = "workflow"


class TestWorkflowCapsuleContent(unittest.TestCase):
    """workflow-specific capsule content not covered by the shared contract."""

    def test_build_agentic_capsule_contains_subcommands(self):
        from workflow.agentic import build_agentic_capsule

        capsule = build_agentic_capsule()
        for cmd in ("run", "list", "lint", "parse", "compile", "status", "resume"):
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, capsule)

    def test_build_agentic_capsule_contains_params_form(self):
        from workflow.agentic import build_agentic_capsule

        self.assertIn("--params", build_agentic_capsule())


class TestWorkflowMainAgenticExtra(unittest.TestCase):
    """workflow-specific CLI behaviour not covered by the shared contract."""

    def test_no_subcommand_preserves_legacy_exit_code(self):
        """The legacy no-subcommand exit code (ExitCode.USAGE == 2) must be unchanged."""
        from core.cli_errors import ExitCode
        from workflow.cli import main

        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            rc = main([])
        self.assertEqual(rc, ExitCode.USAGE)

    def test_no_subcommand_preserves_legacy_message(self):
        """The legacy no-subcommand message must contain 'Usage: workflow'."""
        from workflow.cli import main

        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            main([])
        self.assertIn("Usage: workflow", stderr_buf.getvalue())



class TestWorkflowSeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    """The shared ``--`` separator contract."""

    MODULE_PATH = "workflow.cli"
    APP_ID = "workflow"


class TestWorkflowNoSubcommand(NoSubcommandContractMixin, unittest.TestCase):
    """Rule A7 — the no-subcommand exit code is deliberate."""

    # One-line usage to STDERR with rc=2.
    MODULE_PATH = "workflow.cli"
    EXPECTED_RC = 2
    EXPECTED_STREAM = "stderr"

if __name__ == "__main__":
    unittest.main()
