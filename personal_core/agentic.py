"""Compatibility shim for agentic helpers (migrated to core)."""

from core.agentic import (  # noqa: F401
    build_capsule,
    build_cli_tree,
    cli_path_exists,
    list_subcommands,
    read_text,
    section,
)

__all__ = [
    "read_text",
    "section",
    "build_capsule",
    "build_cli_tree",
    "cli_path_exists",
    "list_subcommands",
]
