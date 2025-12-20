"""Lightweight YAML I/O wrapper delegating to shared helpers."""

from core.yamlio import dump_config, load_config  # noqa: F401

__all__ = ["load_config", "dump_config"]
