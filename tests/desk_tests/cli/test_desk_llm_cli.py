"""Contract tests for desk.llm_cli."""

import unittest

from tests.llm_cli_contract import LLMCLIContractMixin


class TestDeskLLMCLI(LLMCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "desk.llm_cli"
    APP_ID = "desk"
    DOC_SUFFIX = "DESK"
    EXPECTED_PROG = "llm-desk"


if __name__ == "__main__":
    unittest.main(verbosity=2)
