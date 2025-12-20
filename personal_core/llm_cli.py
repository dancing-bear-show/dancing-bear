"""Compatibility shim for LLM CLI helpers (migrated to core)."""

from core.llm_cli import (  # noqa: F401
    LlmConfig,
    build_parser,
    main,
    make_app_llm_config,
    run,
)

__all__ = ["LlmConfig", "build_parser", "make_app_llm_config", "run", "main"]
