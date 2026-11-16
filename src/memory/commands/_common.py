"""Shared argument specs and error reporting for the memory subcommands."""

from __future__ import annotations

import sys
from typing import Any

from memory.discovery import discover_stores, load_store, resolve_current_store
from memory.models import MemoryStore

ArgSpec = tuple[tuple[str, ...], dict[str, Any]]

STORE_ARG: ArgSpec = (
    ("--store",),
    {
        "metavar": "SLUG",
        "default": None,
        "help": "Project slug of one store; write --store=SLUG (slugs start with -)",
    },
)
ALL_STORES_ARG: ArgSpec = (
    ("--all-stores",),
    {"action": "store_true", "help": "Use every discovered store"},
)
DRY_RUN_ARG: ArgSpec = (("--dry-run",), {"action": "store_true", "help": "Preview without writing"})
YES_ARG: ArgSpec = (("--yes",), {"action": "store_true", "help": "Skip confirmation"})


def format_arg(formats: list[str], default: str) -> ArgSpec:
    """``--format`` restricted to ``formats``."""
    return (("--format",), {"choices": formats, "default": default, "help": "Output format"})


def validation_error(field: str, issue: str) -> int:
    """Print a validation error to stderr and return exit code 1."""
    print(f"[memory] Validation error: {field} {issue}", file=sys.stderr)
    return 1


def select_single_store(store_slug: str | None) -> MemoryStore | int:
    """The one store a command acts on: ``--store`` exactly, else a strict cwd match.

    Returns an exit code (after printing the reason to stderr) when no store
    can be chosen. Never falls back to another project's store, so import
    never writes to one and export never reads from one.
    """
    if store_slug:
        try:
            return load_store(store_slug)
        except (Exception) as exc:  # NOSONAR - CLI boundary: surface as a validation error, never a raw traceback  # fmt: skip
            return validation_error("--store", str(exc))
    all_stores = discover_stores()
    if not all_stores:
        print("No memory stores found.", file=sys.stderr)
        return 1
    store = resolve_current_store(all_stores, strict=True)
    if store is None:
        print(
            "[memory] No store matches the current directory; pass --store=SLUG "
            "(see `memory stores`).",
            file=sys.stderr,
        )
        return 1
    return store


def exclusive_store_scope(store: str | None, all_stores: bool) -> int | None:
    """Reject ``--store`` combined with ``--all-stores``; None when the pair is valid."""
    if store and all_stores:
        return validation_error("--store", "cannot be combined with --all-stores")
    return None
