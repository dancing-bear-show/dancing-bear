import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin


class TestCalendarAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """The shared --agentic CLI contract.

    APP_ID is "calendar" (singular) -- the capsule does not echo the package
    name.
    """

    MODULE_PATH = "calendars.__main__"
    APP_ID = "calendar"


if __name__ == "__main__":
    unittest.main(verbosity=2)
