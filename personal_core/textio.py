"""Compatibility shim for text IO helpers (migrated to core)."""

from core.textio import read_text, write_text  # noqa: F401

__all__ = ["read_text", "write_text"]
