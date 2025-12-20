"""Compatibility shim for assistant helpers (migrated to core)."""

from core.assistant import BaseAssistant  # noqa: F401

__all__ = ["BaseAssistant"]
