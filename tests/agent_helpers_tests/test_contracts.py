"""Shared CLIApp and agentic contracts for agent_helpers."""

from __future__ import annotations

import unittest.mock

from agent_helpers.repo import resolve_repo_root
from core.process import CompletedRun
from tests.agentic_builder_contract import AgenticBuilderContractMixin
from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_no_subcommand_contract import NoSubcommandContractMixin
from tests.cli_separator_contract import SeparatorContractMixin


class TestAgentHelpersAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    MODULE_PATH = "agent_helpers.agentic"
    APP_ID = "agent-helpers"


class TestAgentHelpersAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "agent_helpers.cli"
    APP_ID = "agent-helpers"


class TestAgentHelpersSeparator(SeparatorContractMixin, unittest.TestCase):
    MODULE_PATH = "agent_helpers.cli"
    APP_ID = "agent-helpers"


class TestAgentHelpersNoSubcommand(NoSubcommandContractMixin, unittest.TestCase):
    MODULE_PATH = "agent_helpers.cli"
    EXPECTED_RC = 0
    EXPECTED_STREAM = "stdout"


class TestResolveRepoRoot(unittest.TestCase):
    def test_success_strips_newline(self):
        run = CompletedRun(stdout="/some/repo\n", stderr="", returncode=0)
        with unittest.mock.patch("agent_helpers.repo.run_binary", return_value=run):
            self.assertEqual(resolve_repo_root(), ("/some/repo", None))

    def test_outside_repo(self):
        run = CompletedRun(stdout="", stderr="fatal", returncode=128)
        with unittest.mock.patch("agent_helpers.repo.run_binary", return_value=run):
            self.assertEqual(resolve_repo_root(), ("", "not inside a git repository"))

    def test_timeout(self):
        run = CompletedRun(stdout="", stderr="timeout", returncode=124, timed_out=True)
        with unittest.mock.patch("agent_helpers.repo.run_binary", return_value=run):
            root, error = resolve_repo_root()
        self.assertEqual(root, "")
        self.assertIn("timed out", error or "")


if __name__ == "__main__":
    unittest.main()
