"""Contract tests for resume.llm_cli."""

import unittest

from tests.llm_cli_contract import LLMCLIContractMixin


class TestResumeLLMCLI(LLMCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "resume.llm_cli"
    APP_ID = "resume"
    DOC_SUFFIX = "RESUME"
    EXPECTED_PROG = "llm-resume"


if __name__ == "__main__":
    unittest.main(verbosity=2)
