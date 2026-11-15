"""CLI subcommand: list memories across one or more stores.

Supports filtering by type, unindexed status, staleness, non-memory files,
and scope (single store, current repo store, or all stores).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from core.cli_output import emit_rows
from memory.commands._common import (
    ALL_STORES_ARG,
    STORE_ARG,
    ArgSpec,
    exclusive_store_scope,
    format_arg,
    validation_error,
)
from memory.discovery import discover_stores, load_store, resolve_current_store
from memory.models import Memory, MemoryStore, MemoryType

_LIST_HEADERS = ["slug", "type", "description", "mtime", "indexed", "shape"]
_NON_MEMORY_HEADERS = ["path", "store"]


ARGUMENTS: list[ArgSpec] = [
    format_arg(["table", "json", "yaml", "csv"], "table"),
    (("--limit",), {"type": int, "default": 0, "help": "Max rows (0 = all)"}),
    (("--type",), {"choices": [t.value for t in MemoryType], "default": None, "help": "Filter by memory type"}),
    (("--non-memory",), {"action": "store_true", "help": "List non-memory files instead"}),
    (("--unindexed",), {"action": "store_true", "help": "Only memories missing from MEMORY.md"}),
    (("--stale-days",), {"type": int, "default": None, "metavar": "N", "help": "Only memories older than N days"}),
    STORE_ARG,
    ALL_STORES_ARG,
]


def _memory_row(m: Memory) -> dict:
    return {
        "slug": m.slug,
        "type": m.frontmatter.type.value if m.frontmatter.type else None,
        "description": m.frontmatter.description,
        "mtime": m.mtime.isoformat(),
        "indexed": "yes" if m.indexed else "no",
        "shape": m.frontmatter.shape.value,
    }


def _filter_memories(
    memories: tuple[Memory, ...],
    *,
    type_filter: str | None,
    unindexed_only: bool,
    stale_days: int | None,
) -> list[Memory]:
    now = datetime.now(UTC)
    result = list(memories)
    if type_filter:
        result = [
            m
            for m in result
            if m.frontmatter.type and m.frontmatter.type.value == type_filter
        ]
    if unindexed_only:
        result = [m for m in result if not m.indexed]
    if stale_days is not None:
        result = [m for m in result if (now - m.mtime).days >= stale_days]
    return result


def run(args: argparse.Namespace) -> int:
    """List memories (or non-memory files) in the selected stores."""
    scope_error = exclusive_store_scope(args.store, args.all_stores)
    if scope_error is not None:
        return scope_error

    all_stores = discover_stores()

    if args.store:
        try:
            stores: tuple[MemoryStore, ...] = (load_store(args.store),)
        except Exception as exc:  # NOSONAR - CLI boundary: surface as a validation error, never a raw traceback
            return validation_error("--store", f"could not load store {args.store!r}: {exc}")
    elif args.all_stores:
        stores = all_stores
    else:
        current = resolve_current_store(all_stores)
        if current is None:
            return _emit([], args, _LIST_HEADERS, "No memory stores found.")
        stores = (current,)

    if args.non_memory:
        rows = [
            {"path": path, "store": store.project_slug}
            for store in stores
            for path in store.non_memory_files
        ]
        return _emit(rows, args, _NON_MEMORY_HEADERS, "No non-memory files found.")

    rows = []
    for store in stores:
        filtered = _filter_memories(
            store.memories,
            type_filter=args.type,
            unindexed_only=args.unindexed,
            stale_days=args.stale_days,
        )
        rows.extend(_memory_row(m) for m in filtered)

    return _emit(rows, args, _LIST_HEADERS, "No memories match the given filters.")


def _emit(rows: list[dict], args: argparse.Namespace, headers: list[str], empty_msg: str) -> int:
    if args.limit > 0:
        rows = rows[: args.limit]
    return emit_rows(rows, args.format, headers=headers, empty_msg=empty_msg, structured_empty=True)
