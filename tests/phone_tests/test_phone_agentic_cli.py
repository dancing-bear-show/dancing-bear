"""CLI --agentic contract for phone.

This app had no coverage of its `--agentic` CLI surface: the flag, the JSON
schema, and `--agentic-compact` were all untested even though CLAUDE.md
documents them as supported on every app.
"""

import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_separator_contract import SeparatorContractMixin
from tests.cli_no_subcommand_contract import NoSubcommandContractMixin


class TestPhoneAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract."""

    MODULE_PATH = "phone.__main__"
    APP_ID = "phone"


class TestPhoneSeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    """The shared ``--`` separator contract."""

    MODULE_PATH = "phone.cli.main"
    APP_ID = "phone"



class TestPhoneNoSubcommand(NoSubcommandContractMixin, unittest.TestCase):
    """Rule A7 — the no-subcommand exit code is deliberate."""

    MODULE_PATH = "phone.cli.main"
    EXPECTED_RC = 0
    EXPECTED_STREAM = "stdout"

if __name__ == "__main__":
    unittest.main()
