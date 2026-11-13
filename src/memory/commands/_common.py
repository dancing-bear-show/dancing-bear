"""Shared argument specs and error reporting for the memory subcommands."""

from __future__ import annotations

import sys
from typing import Any

ArgSpec = tuple[tuple[str, ...], dict[str, Any]]

STORE_ARG: ArgSpec = (("--store",), {"metavar": "SLUG", "default": None, "help": "Project slug of one store"})
ALL_STORES_ARG: ArgSpec = (("--all-stores",), {"action": "store_true", "help": "Use every discovered store"})
DRY_RUN_ARG: ArgSpec = (("--dry-run",), {"action": "store_true", "help": "Preview without writing"})
YES_ARG: ArgSpec = (("--yes",), {"action": "store_true", "help": "Skip confirmation"})


def format_arg(formats: list[str], default: str) -> ArgSpec:
    """``--format`` restricted to ``formats``."""
    return (("--format",), {"choices": formats, "default": default, "help": "Output format"})


def validation_error(field: str, issue: str) -> int:
    """Print a validation error to stderr and return exit code 1."""
    print(f"[memory] Validation error: {field} {issue}", file=sys.stderr)
    return 1


def exclusive_store_scope(store: str | None, all_stores: bool) -> int | None:
    """Reject ``--store`` combined with ``--all-stores``; None when the pair is valid."""
    if store and all_stores:
        return validation_error("--store", "cannot be combined with --all-stores")
    return None
