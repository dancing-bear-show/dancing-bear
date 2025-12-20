"""Mail assistant LLM CLI shim.

Delegates to the shared repo-level LLM CLI implementation so tests that import
`mail_assistant.llm_cli` can exercise inventory, familiar, flows, and other
subcommands without duplicating logic.
"""

from core import llm_cli as _core_llm_cli

# Re-export primary entrypoints from the shared implementation.
LlmConfig = _core_llm_cli.LlmConfig
build_parser = _core_llm_cli.build_parser
run = _core_llm_cli.run
main = _core_llm_cli.main

__all__ = ["LlmConfig", "build_parser", "run", "main"]
