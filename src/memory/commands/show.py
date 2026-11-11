"""CLI subcommand: show a single memory in detail.

Renders name/description/type/body, with a Links block for wikilinks,
and supports --raw for raw file bytes and --format json/yaml for structured output.
"""

from __future__ import annotations

import argparse
import sys

from core.cli_output import emit_one
from memory.commands._common import ArgSpec, format_arg, validation_error
from memory.discovery import discover_stores, resolve_current_store
from memory.models import Memory, MemoryStore
from memory.parser import normalize_slug


def _find_memory(store: MemoryStore, slug_input: str) -> Memory | str:
    """Resolve slug_input against store; return Memory or error string."""
    # Strip .md suffix for normalisation
    key = slug_input.removesuffix(".md")

    exact = [m for m in store.memories if m.slug == key]
    if len(exact) == 1:
        return exact[0]

    prefix_matches = [m for m in store.memories if m.slug.startswith(key)]
    # Re-check for exact match inside prefix results
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) == 0:
        return f"no memory matches '{slug_input}'"

    candidate_list = ", ".join(m.slug for m in prefix_matches)
    return f"ambiguous — matches: {candidate_list}"


def _render_text(memory: Memory, *, known_slugs: set[str]) -> str:
    """Build a human-readable text rendering of the memory."""
    lines: list[str] = []
    fm = memory.frontmatter
    lines.append(f"# {fm.name or memory.slug}")
    if fm.description:
        lines.append(f"\n{fm.description}")
    if fm.type:
        lines.append(f"\ntype: {fm.type.value}")
    lines.append("")

    if memory.body:
        lines.append(memory.body.strip())

    if memory.wikilinks:
        lines.append("\n## Links")
        for link_slug in memory.wikilinks:
            status = "ok" if link_slug in known_slugs else "broken"
            lines.append(f"- [[{link_slug}]] [{status}]")

    return "\n".join(lines)


def _build_structured(memory: Memory, *, known_slugs: set[str]) -> dict:
    """Build a structured dict suitable for json/yaml output."""
    fm = memory.frontmatter
    links = [{"slug": s, "resolved": s in known_slugs} for s in memory.wikilinks]
    return {
        "slug": memory.slug,
        "name": fm.name,
        "description": fm.description,
        "type": fm.type.value if fm.type else None,
        "shape": fm.shape.value,
        "indexed": memory.indexed,
        "mtime": memory.mtime.isoformat(),
        "body": memory.body,
        "why": memory.why,
        "how_to_apply": memory.how_to_apply,
        "links": links,
    }


ARGUMENTS: list[ArgSpec] = [
    (("slug",), {"nargs": "?", "help": "Memory slug or unique prefix"}),
    format_arg(["text", "json", "yaml"], "text"),
    (("--raw",), {"action": "store_true", "help": "Dump raw file bytes"}),
]


def run(args: argparse.Namespace) -> int:
    """Show one memory from the current repo's store."""
    if not args.slug:
        return validation_error("slug", "required argument missing")

    all_stores = discover_stores()
    store = resolve_current_store(all_stores)
    if store is None:
        print("No memory stores found.", file=sys.stderr)
        return 1

    result = _find_memory(store, args.slug)
    if isinstance(result, str):
        return validation_error("slug", result)

    memory = result

    if args.raw:
        try:
            with open(memory.path, "rb") as fh:
                sys.stdout.buffer.write(fh.read())
            return 0
        except OSError as exc:
            print(f"Error reading {memory.path}: {exc}", file=sys.stderr)
            return 1

    known_slugs = {normalize_slug(m.slug) for m in store.memories}

    if args.format == "text":
        print(_render_text(memory, known_slugs=known_slugs))
        return 0

    return emit_one(_build_structured(memory, known_slugs=known_slugs), args.format)

