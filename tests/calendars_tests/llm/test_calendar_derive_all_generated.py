"""Derive-all coverage for calendars.llm_cli.

Previously contained a standalone derive-all test. That contract is now
fully covered by TestCalendarLLMCLI in test_calendar_llm_cli.py, which
inherits LLMCLIContractMixin and includes test_derive_all_outputs_files.
"""
