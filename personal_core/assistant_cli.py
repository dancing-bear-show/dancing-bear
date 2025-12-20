"""Compatibility shim for assistant dispatcher (migrated to core)."""

from core.assistant_cli import main  # noqa: F401

__all__ = ["main"]
