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


#: Subcommands a workflow stage branches on by exit status. Their flags are
#: derived from the parser below; only the command names are listed.
_GUARD_COMMANDS = (
    "check-params", "check-finding-keys", "thread-fingerprints", "check-thread-ids",
    "aggregate-fix-results",
)


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

    def test_capsule_lists_every_registered_subcommand(self):
        """Derived from the real parser, not a hand-listed set.

        A hand-written capsule drifts silently: check-params shipped with two
        workflows depending on it and no capsule entry, so an agent reading
        ./bin/workflow --agentic could not discover it. Enumerating the
        parser's own subcommands means the next addition fails here instead.
        """
        from workflow.agentic import build_agentic_capsule
        from workflow.cli import app

        capsule = build_agentic_capsule()
        registered = sorted(app._commands)
        self.assertIn("check-params", registered, "parser wiring changed; fix this test")
        for cmd in registered:
            with self.subTest(cmd=cmd):
                self.assertIn(f"  - {cmd}:", capsule)

    def test_capsule_documents_every_guard_command_flag(self):
        """Every option of every guard subcommand is on that command's own
        capsule line, derived from the parser.

        This was a hand-written assertIn("--print") and it let --top-level ship
        undocumented even though the demo workflow needs it to validate
        handler.json — the same drift the subcommand test above exists to
        prevent, one level down. Enumerating the registered arguments means
        the next flag added to any of these commands fails here instead.
        Asserting on the command's own line (not anywhere in the capsule)
        stops one command's flag from being "documented" by another's.
        """
        from workflow.agentic import build_agentic_capsule
        from workflow.cli import app

        lines = build_agentic_capsule().splitlines()
        seen_flags: set[str] = set()
        for cmd in _GUARD_COMMANDS:
            self.assertIn(cmd, app._commands, "parser wiring changed; fix this test")
            line = next((ln for ln in lines if ln.startswith(f"  - {cmd}:")), "")
            flags = sorted(
                flag
                for arg in app._commands[cmd].arguments
                for flag in arg.name_or_flags
                if flag.startswith("--")
            )
            seen_flags.update(flags)
            for flag in flags:
                with self.subTest(cmd=cmd, flag=flag):
                    self.assertIn(flag, line)
        # Canaries: prove the derivation reaches real flags on each shape.
        for flag in ("--print", "--top-level", "--repair"):
            self.assertIn(flag, seen_flags, "parser wiring changed; fix this test")


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
