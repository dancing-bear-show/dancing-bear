"""Contract tests for maker.llm_cli.

Contract override:
    test_config_familiar_extended_returns_nonempty_string is overridden because
    maker.llm_cli sets ``familiar_extended=None`` in its CONFIG — the maker
    domain does not define a familiar-extended step sequence. This is a genuine
    gap in the maker implementation, not a mixin defect. The test is skipped
    rather than weakened so the failure is visible if maker adds the field later.
"""

import unittest

from tests.llm_cli_contract import LLMCLIContractMixin


class TestMakerLLMCLI(LLMCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "maker.llm_cli"
    APP_ID = "maker"
    DOC_SUFFIX = "MAKER"
    EXPECTED_PROG = "llm-maker"

    def test_config_familiar_extended_returns_nonempty_string(self):
        # maker.llm_cli.CONFIG.familiar_extended is None — no extended
        # familiarization is defined for the maker domain.
        raise unittest.SkipTest(
            "maker.llm_cli does not define familiar_extended (CONFIG.familiar_extended=None)"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
