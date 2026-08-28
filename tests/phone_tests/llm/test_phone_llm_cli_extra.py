"""Additional phone.llm_cli tests beyond the shared contract.

The shared contract (LLMCLIContractMixin) is exercised by TestPhoneLLMCLI in
test_phone_llm_cli.py. This file keeps domain-specific assertions that are not
part of the shared contract.
"""

from __future__ import annotations

import unittest


class TestPhoneLlmCliMain(unittest.TestCase):
    """Smoke-tests for main() subcommands not in the contract mixin."""

    def test_main_with_domain_map_returns_zero(self):
        from phone.llm_cli import main

        result = main(["domain-map"])
        self.assertEqual(result, 0)

    def test_main_with_agentic_no_stdout_returns_zero(self):
        from phone.llm_cli import main

        result = main(["agentic"])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
