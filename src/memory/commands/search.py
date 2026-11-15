"""CLI subcommand: full-text search across memory stores.

Deliberately dumb sweep — no embedding index, no ranking. Substring by default;
opt-in regex via --regex. Emits slug/store/type/match_field/snippet rows.
"""

from __future__ import annotations

import argparse
import re

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
from memory.models import Memory, MemoryStore

SNIPPET_WINDOW = 60  # characters of context on each side of the match

_SEARCH_HEADERS = ["slug", "store", "type", "match_field", "snippet"]


def _resolve_stores(
    args: argparse.Namespace, all_stores: tuple[MemoryStore, ...]
) -> tuple[MemoryStore, ...] | int:
    """Resolve which stores to search based on --store/--all-stores flags.

    Returns a tuple of stores to search, or an int exit code if store
    loading failed (the caller must return that code immediately).
    """
    if args.store:
        try:
            return (load_store(args.store),)
        except Exception as exc:  # NOSONAR - CLI boundary: surface as a validation error, never a raw traceback
            return validation_error("--store", f"could not load store {args.store!r}: {exc}")
    if args.all_stores:
        return all_stores
    # Default: current repo store only
    current = resolve_current_store(all_stores)
    return (current,) if current is not None else all_stores


def _collect_matches(
    stores: tuple[MemoryStore, ...],
    *,
    query: str,
    pattern: re.Pattern | None,
    limit: int,
) -> list[dict]:
    """Search every memory in every store, stopping early once limit is hit."""
    matches: list[dict] = []
    for store in stores:
        for memory in store.memories:
            matches.extend(_search_memory(memory, store, query=query, pattern=pattern))
            if limit > 0 and len(matches) >= limit:
                return matches[:limit]
    return matches


def _extract_snippet(text: str, start: int, end: int) -> str:
    """Return a single-line +/-SNIPPET_WINDOW context around [start:end].

    Collapses whitespace and truncates at 200 chars.
    """
    snip_start = max(0, start - SNIPPET_WINDOW)
    snip_end = min(len(text), end + SNIPPET_WINDOW)
    snippet = text[snip_start:snip_end]
    snippet = " ".join(snippet.split())
    if len(snippet) > 200:
        snippet = snippet[:197] + "..."
    return snippet


def _search_field(
    memory: Memory,
    store: MemoryStore,
    field_name: str,
    field_value: str,
    *,
    query: str,
    pattern: re.Pattern | None,
) -> list[dict]:
    """Return match rows for a single (memory, field) combination."""
    rows: list[dict] = []
    mem_type = memory.frontmatter.type.value if memory.frontmatter.type else None

    if pattern is not None:
        for m in pattern.finditer(field_value):
            rows.append(
                {
                    "slug": memory.slug,
                    "store": store.project_slug,
                    "type": mem_type,
                    "match_field": field_name,
                    "snippet": _extract_snippet(field_value, m.start(), m.end()),
                }
            )
    else:
        idx = 0
        while True:
            pos = field_value.find(query, idx)
            if pos == -1:
                break
            rows.append(
                {
                    "slug": memory.slug,
                    "store": store.project_slug,
                    "type": mem_type,
                    "match_field": field_name,
                    "snippet": _extract_snippet(field_value, pos, pos + len(query)),
                }
            )
            idx = pos + 1

    return rows


def _search_memory(
    memory: Memory,
    store: MemoryStore,
    *,
    query: str,
    pattern: re.Pattern | None,
) -> list[dict]:
    """Search all searchable fields of a memory and return match rows."""
    rows: list[dict] = []
    fields = {
        "body": memory.body,
        "name": memory.frontmatter.name or "",
        "description": memory.frontmatter.description or "",
    }
    for field_name, field_value in fields.items():
        if field_value:
            rows.extend(
                _search_field(
                    memory,
                    store,
                    field_name,
                    field_value,
                    query=query,
                    pattern=pattern,
                )
            )
    return rows


ARGUMENTS: list[ArgSpec] = [
    (("query",), {"help": "Substring (or regex with --regex)"}),
    STORE_ARG,
    ALL_STORES_ARG,
    (("--regex",), {"action": "store_true", "help": "Treat query as a regex"}),
    format_arg(["table", "json", "csv"], "table"),
    (("--limit",), {"type": int, "default": 0, "help": "Max matches (0 = all)"}),
]


def run(args: argparse.Namespace) -> int:
    """Full-text search across memory stores."""
    scope_error = exclusive_store_scope(args.store, args.all_stores)
    if scope_error is not None:
        return scope_error

    pattern: re.Pattern | None = None
    if args.regex:
        try:
            pattern = re.compile(args.query)
        except re.error as exc:
            return validation_error("query", f"invalid regex pattern: {exc}")

    all_stores = discover_stores()

    resolved = _resolve_stores(args, all_stores)
    if isinstance(resolved, int):
        return resolved
    stores = resolved

    matches = _collect_matches(
        stores, query=args.query, pattern=pattern, limit=args.limit
    )

    return emit_rows(
        matches,
        args.format,
        headers=_SEARCH_HEADERS,
        empty_msg="No matches found",
        structured_empty=True,
    )
