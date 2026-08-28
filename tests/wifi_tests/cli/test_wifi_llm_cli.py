"""Contract tests for wifi.llm_cli."""

import unittest

from tests.llm_cli_contract import LLMCLIContractMixin


class TestWifiLLMCLI(LLMCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "wifi.llm_cli"
    APP_ID = "wifi"
    DOC_SUFFIX = "WIFI"
    EXPECTED_PROG = "llm-wifi"


if __name__ == "__main__":
    unittest.main(verbosity=2)
