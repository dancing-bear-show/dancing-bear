"""Contract tests for desk.llm_cli."""

import unittest

from desk import llm_cli
from tests.llm_cli_contract import LLMCLIContractMixin


class TestDeskLLMCLI(LLMCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "desk.llm_cli"
    APP_ID = "desk"
    DOC_SUFFIX = "DESK"
    EXPECTED_PROG = "llm-desk"


class TestFamiliarStepsUseRealWrapper(unittest.TestCase):
    """The ./bin/llm --app desk route dispatches to desk.llm_cli, whose
    familiarization steps must reference the wrapper that actually ships
    (./bin/desk) rather than the nonexistent ./bin/desk-assistant.
    """

    def test_familiar_compact_uses_bin_desk(self):
        result = llm_cli.CONFIG.familiar_compact()
        self.assertIn("./bin/desk --help", result)
        self.assertNotIn("desk-assistant", result)

    def test_familiar_extended_uses_bin_desk(self):
        result = llm_cli.CONFIG.familiar_extended()
        self.assertIn("./bin/desk scan", result)
        self.assertNotIn("desk-assistant", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
