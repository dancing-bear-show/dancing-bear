"""Derive-all coverage for maker.llm_cli.

Previously contained a standalone derive-all test. That contract is now
fully covered by TestMakerLLMCLI in tests/maker_tests/cli/test_maker_llm_cli.py,
which inherits LLMCLIContractMixin and includes test_derive_all_outputs_files.
"""
