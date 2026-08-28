"""Contract tests for phone.llm_cli.

Note: phone.llm_cli uses ``prog="llm"`` rather than ``prog="llm-phone"``.
This is intentional — the phone assistant shares the top-level ``llm`` prog
name. The EXPECTED_PROG override reflects that.
"""

import unittest

from tests.llm_cli_contract import LLMCLIContractMixin


class TestPhoneLLMCLI(LLMCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "phone.llm_cli"
    APP_ID = "phone"
    DOC_SUFFIX = "PHONE"
    EXPECTED_PROG = "llm"  # phone uses "llm" not "llm-phone"


if __name__ == "__main__":
    unittest.main(verbosity=2)
