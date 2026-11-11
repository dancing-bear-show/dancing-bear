"""CLI subcommand: list discovered memory stores with inferred roles.

Answers "where does my memory actually live?" by enumerating every store
under ~/.claude/projects with its computed metadata and role classification.
"""

from __future__ import annotations

import argparse
from datetime import datetime

from core.cli_output import emit_rows
from memory.commands._common import ArgSpec, format_arg
from memory.consolidate import _group_by_repo
from memory.discovery import discover_stores, elect_canonical
from memory.models import MemoryStore

_STORES_HEADERS = [
    "project_slug",
    "inferred_repo",
    "is_worktree",
    "memory_dir_exists",
    "memory_count",
    "index_entries",
    "newest_mtime",
    "role",
]


def _newest_mtime_str(store: MemoryStore) -> str:
    """Return ISO timestamp of the newest memory mtime, or empty string."""
    if not store.memories:
        return ""
    newest: datetime = max(m.mtime for m in store.memories)
    return newest.isoformat()


def _memory_dir_exists(store: MemoryStore) -> bool:
    """Infer whether the memory directory exists from available fields."""
    return bool(store.memories or store.non_memory_files or store.index_path)


def _classify_role(
    store: MemoryStore,
    canonicals: set[int],
) -> str:
    """Assign a role label based on membership and memory presence.

    canonicals holds id() of one elected store per inferred_repo group (see
    _group_by_repo) rather than a single global winner — a multi-project
    user has one canonical store per repo, not one canonical store total.
    MemoryStore is not hashable (unknown_keys is a plain dict), so identity
    is tracked via id() rather than putting stores directly in the set.
    """
    memory_count = len(store.memories)
    has_index = bool(store.index_entries)

    if id(store) in canonicals:
        return "canonical"
    if memory_count > 0:
        return "superseded"
    if has_index:
        return "orphan-index"
    return "no-memory"


def _build_row(store: MemoryStore, role: str) -> dict[str, str | int | None]:
    return {
        "project_slug": store.project_slug,
        "inferred_repo": store.inferred_repo,
        "is_worktree": str(store.is_worktree_slug),
        "memory_dir_exists": str(_memory_dir_exists(store)),
        "memory_count": len(store.memories),
        "index_entries": len(store.index_entries),
        "newest_mtime": _newest_mtime_str(store),
        "role": role,
    }


ARGUMENTS: list[ArgSpec] = [
    format_arg(["table", "json", "csv"], "table"),
    (("--with-memory-only",), {"action": "store_true", "help": "Only stores with at least one memory"}),
]


def run(args: argparse.Namespace) -> int:
    """List every discovered store with its inferred role."""
    stores = discover_stores()
    groups = _group_by_repo(stores)
    canonicals: set[int] = set()
    for group in groups.values():
        c = elect_canonical(group)
        if c is not None:
            canonicals.add(id(c))

    rows = []
    for store in stores:
        if args.with_memory_only and len(store.memories) == 0:
            continue
        role = _classify_role(store, canonicals)
        rows.append(_build_row(store, role))

    return emit_rows(
        rows,
        args.format,
        headers=_STORES_HEADERS,
        empty_msg="No memory stores discovered.",
        structured_empty=True,
    )
