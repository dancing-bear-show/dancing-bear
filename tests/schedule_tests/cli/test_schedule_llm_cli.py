"""Contract tests for schedule.llm_cli."""

import unittest

from tests.llm_cli_contract import LLMCLIContractMixin


class TestScheduleLLMCLI(LLMCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "schedule.llm_cli"
    APP_ID = "schedule"
    DOC_SUFFIX = "SCHEDULE"
    EXPECTED_PROG = "llm-schedule"


if __name__ == "__main__":
    unittest.main(verbosity=2)
