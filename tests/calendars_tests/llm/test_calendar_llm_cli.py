"""Contract tests for calendars.llm_cli."""

import unittest

from tests.llm_cli_contract import LLMCLIContractMixin


class TestCalendarLLMCLI(LLMCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "calendars.llm_cli"
    APP_ID = "calendar"
    DOC_SUFFIX = "CALENDAR"
    EXPECTED_PROG = "llm-calendar"


if __name__ == "__main__":
    unittest.main(verbosity=2)
