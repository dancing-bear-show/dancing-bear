"""CLI --agentic contract for qlty.

qlty had no coverage of its ``--agentic`` CLI surface: the flag, the JSON
schema, and ``--agentic-compact`` were untested even though CLAUDE.md documents
them as supported on every app. The shared builder contract in test_qlty_agentic.py
covered the builder module; this file covers the other end.

qlty routes its CLI through qlty.cli (not a __main__ shim), so MODULE_PATH
points there directly.
"""

import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin


class TestQltyAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract."""

    MODULE_PATH = "qlty.cli"
    APP_ID = "qlty"


if __name__ == "__main__":
    unittest.main()
