"""CLI --agentic contract for wifi.

This app had no coverage of its `--agentic` CLI surface: the flag, the JSON
schema, and `--agentic-compact` were all untested even though CLAUDE.md
documents them as supported on every app.
"""

import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_separator_contract import SeparatorContractMixin


class TestWifiAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract."""

    MODULE_PATH = "wifi.__main__"
    APP_ID = "wifi"


class TestWifiSeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    """The shared ``--`` separator contract."""

    MODULE_PATH = "wifi.cli"
    APP_ID = "wifi"


if __name__ == "__main__":
    unittest.main()
