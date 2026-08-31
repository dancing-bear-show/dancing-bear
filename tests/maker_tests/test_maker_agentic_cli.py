"""CLI --agentic contract for maker.

This app had no coverage of its `--agentic` CLI surface: the flag, the JSON
schema, and `--agentic-compact` were all untested even though CLAUDE.md
documents them as supported on every app.
"""

import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_separator_contract import SeparatorContractMixin


class TestMakerAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract."""

    MODULE_PATH = "maker.__main__"
    APP_ID = "maker"


class TestMakerSeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    """The shared ``--`` separator contract."""

    MODULE_PATH = "maker.cli.main"
    APP_ID = "maker"


if __name__ == "__main__":
    unittest.main()
