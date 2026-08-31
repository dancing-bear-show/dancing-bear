import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin


class TestMailAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract."""

    MODULE_PATH = "mail.__main__"
    APP_ID = "mail"


if __name__ == "__main__":
    unittest.main(verbosity=2)
