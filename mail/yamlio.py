"""Compatibility shim that re-exports shared YAML helpers."""
from __future__ import annotations

from core.yamlio import dump_config, load_config  # noqa: F401

__all__ = ["load_config", "dump_config"]
