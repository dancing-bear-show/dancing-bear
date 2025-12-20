"""Compatibility shim for YAML helpers (migrated to core)."""

from core.yamlio import dump_config, load_config  # noqa: F401

__all__ = ["load_config", "dump_config"]
