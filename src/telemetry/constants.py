"""Shared constants for the telemetry package."""
from __future__ import annotations

from pathlib import Path

__all__ = ["CONFIG_PATH"]

# Menubar/pricing config file — cost_multiplier, budget, and display settings.
CONFIG_PATH = Path.home() / ".claude" / "claudestats.json"
