"""Claude auto-memory CLI: inspect, validate, and move ~/.claude/projects/*/memory stores.

Domain modules (parser, discovery, validation, ...) are imported directly by
path; this package re-exports only the CLI entry point.
"""

__all__ = [
    "main",
]

from .__main__ import main
