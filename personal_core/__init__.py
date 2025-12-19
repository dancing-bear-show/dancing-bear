"""Shared helpers for personal assistant CLIs.

This lightweight package hosts reusable utilities (agentic helpers,
YAML shims, etc.) so individual assistants can stay focused on their
domain logic without duplicating boilerplate.
"""

from . import agentic, yamlio, textio  # noqa: F401

__all__ = ["agentic", "yamlio", "textio"]
