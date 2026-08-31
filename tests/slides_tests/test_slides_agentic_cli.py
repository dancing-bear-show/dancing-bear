"""CLI --agentic contract for slides.

This app had no coverage of its `--agentic` CLI surface: the flag, the JSON
schema, and `--agentic-compact` were all untested even though CLAUDE.md
documents them as supported on every app.
"""

import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_separator_contract import SeparatorContractMixin


class TestSlidesAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract."""

    MODULE_PATH = "slides.__main__"
    APP_ID = "slides"


class TestSlidesSeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    """The shared ``--`` separator contract."""

    MODULE_PATH = "slides.cli"
    APP_ID = "slides"


if __name__ == "__main__":
    unittest.main()
