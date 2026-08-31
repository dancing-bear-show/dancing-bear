import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_separator_contract import SeparatorContractMixin


class TestMailAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract."""

    MODULE_PATH = "mail.__main__"
    APP_ID = "mail"


class TestMailSeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    """The shared ``--`` separator contract."""

    MODULE_PATH = "mail.cli.main"
    APP_ID = "mail"


if __name__ == "__main__":
    unittest.main(verbosity=2)
