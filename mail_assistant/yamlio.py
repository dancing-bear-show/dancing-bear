from __future__ import annotations

"""Compatibility shim that re-exports shared YAML helpers."""

from core.yamlio import dump_config, load_config  # noqa: F401

__all__ = ["load_config", "dump_config"]
