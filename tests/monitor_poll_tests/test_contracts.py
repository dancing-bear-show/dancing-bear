"""Shared CLIApp and agentic contracts for monitor_poll."""

from __future__ import annotations

import unittest

from tests.agentic_builder_contract import AgenticBuilderContractMixin
from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_no_subcommand_contract import NoSubcommandContractMixin
from tests.cli_separator_contract import SeparatorContractMixin


class TestMonitorPollSeparator(SeparatorContractMixin, unittest.TestCase):
    """``main(["--", "--agentic"])`` must equal ``main(["--agentic"])``."""

    MODULE_PATH = "monitor_poll.cli"
    APP_ID = "monitor-poll"


class TestMonitorPollNoSubcommand(NoSubcommandContractMixin, unittest.TestCase):
    """Framework default: print help to stdout, exit 0."""

    MODULE_PATH = "monitor_poll.cli"
    EXPECTED_RC = 0
    EXPECTED_STREAM = "stdout"


class TestMonitorPollAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    MODULE_PATH = "monitor_poll.agentic"
    APP_ID = "monitor-poll"


class TestMonitorPollAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "monitor_poll.cli"
    APP_ID = "monitor-poll"


if __name__ == "__main__":
    unittest.main()
