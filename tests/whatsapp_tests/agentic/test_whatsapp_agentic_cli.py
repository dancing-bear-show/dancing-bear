"""CLI --agentic contract for whatsapp.

This app had no coverage of its `--agentic` CLI surface: the flag, the JSON
schema, and `--agentic-compact` were all untested even though CLAUDE.md
documents them as supported on every app.
"""

import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin


class TestWhatsappAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract."""

    MODULE_PATH = "whatsapp.__main__"
    APP_ID = "whatsapp"


if __name__ == "__main__":
    unittest.main()
