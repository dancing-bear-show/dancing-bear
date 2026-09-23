"""Shared CLIApp contracts for github_assistant.

* ``SeparatorContractMixin`` — bare ``--`` is optional and byte-transparent.
* ``NoSubcommandContractMixin`` — a bare invocation must print full help to
  stdout and exit 0 (the framework default; github inherits it).
"""

from __future__ import annotations

import unittest

from tests.cli_no_subcommand_contract import NoSubcommandContractMixin
from tests.cli_separator_contract import SeparatorContractMixin


class TestGithubSeparator(SeparatorContractMixin, unittest.TestCase):
    """``main(["--", "--agentic"])`` must equal ``main(["--agentic"])``."""

    MODULE_PATH = "github_assistant.cli"
    APP_ID = "github"


class TestGithubNoSubcommand(NoSubcommandContractMixin, unittest.TestCase):
    """Framework default: print help to stdout, exit 0."""

    MODULE_PATH = "github_assistant.cli"
    EXPECTED_RC = 0
    EXPECTED_STREAM = "stdout"


if __name__ == "__main__":
    unittest.main()
