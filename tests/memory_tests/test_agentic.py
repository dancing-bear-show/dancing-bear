"""Shared agentic and CLIApp contracts for the memory CLI."""

from __future__ import annotations

import unittest

from tests.agentic_builder_contract import AgenticBuilderContractMixin
from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_no_subcommand_contract import NoSubcommandContractMixin
from tests.cli_separator_contract import SeparatorContractMixin


class TestMemoryAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    MODULE_PATH = "memory.agentic"
    APP_ID = "memory"


class TestMemoryAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "memory.cli"
    APP_ID = "memory"


class TestMemorySeparator(SeparatorContractMixin, unittest.TestCase):
    MODULE_PATH = "memory.cli"
    APP_ID = "memory"


class TestMemoryNoSubcommand(NoSubcommandContractMixin, unittest.TestCase):
    MODULE_PATH = "memory.cli"
    EXPECTED_RC = 0
    EXPECTED_STREAM = "stdout"


if __name__ == "__main__":
    unittest.main()
