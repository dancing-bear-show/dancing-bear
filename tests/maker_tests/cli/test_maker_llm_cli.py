"""Contract tests for maker.llm_cli."""

import unittest

from tests.llm_cli_contract import LLMCLIContractMixin


class TestMakerLLMCLI(LLMCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "maker.llm_cli"
    APP_ID = "maker"
    DOC_SUFFIX = "MAKER"
    EXPECTED_PROG = "llm-maker"


if __name__ == "__main__":
    unittest.main(verbosity=2)
