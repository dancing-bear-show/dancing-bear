import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin
from tests.cli_separator_contract import SeparatorContractMixin


class TestCalendarAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract.

    APP_ID is "calendar" (singular) -- the capsule does not echo the package
    name.
    """

    MODULE_PATH = "calendars.__main__"
    APP_ID = "calendar"


class TestCalendarSeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    """The shared ``--`` separator contract.

    APP_ID is "calendar" (singular) -- same asymmetry as the agentic contract.
    """

    MODULE_PATH = "calendars.cli.main"
    APP_ID = "calendar"


if __name__ == "__main__":
    unittest.main(verbosity=2)
