"""CLI subcommand: export memories as a redaction-scanned MemoryBundle.

Refuses to write on any block-severity finding. Redaction summary always
goes to stderr; bundle content goes to stdout or --output file, keeping
stdout clean for piped consumers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.fileutil import atomic_write_text
from memory.commands._common import DRY_RUN_ARG, YES_ARG, ArgSpec, format_arg, validation_error
from memory.bundle import build_bundle, serialize_bundle
from memory.discovery import discover_stores, resolve_current_store
from memory.models import Memory, MemoryStore
from memory.redaction import SEVERITY_WARN, Redaction, has_blocking


def _print_redaction_summary(redactions: list[Redaction]) -> None:
    """Print a human-readable redaction summary to stderr."""
    if not redactions:
        return
    print("Redaction summary:", file=sys.stderr)
    for r in redactions:
        print(
            f"  [{r.severity}] rule={r.rule_id} line={r.line_no} "
            f"matched={r.matched!r} -> {r.replacement!r}",
            file=sys.stderr,
        )


def _select_memories(
    store: MemoryStore,
    *,
    slugs: list[str] | None,
    types: list[str] | None,
    include_all: bool,
) -> tuple[Memory, ...]:
    """Filter store.memories by the provided selectors."""
    if include_all:
        return store.memories
    selected: list[Memory] = []
    for m in store.memories:
        if slugs and m.slug in slugs:
            selected.append(m)
            continue
        if types and m.frontmatter.type and m.frontmatter.type.value in types:
            selected.append(m)
    return tuple(selected)


def _confirm_export(count: int) -> bool:
    """Prompt for confirmation; return True if the export should proceed."""
    prompt = f"Export {count} memory/memories? [y/N]: "
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        print("Export cancelled (EOF).", file=sys.stderr)
        return False
    if answer != "y":
        print("Export cancelled.", file=sys.stderr)
        return False
    return True


def _write_bundle_output(content: str, output: str | None) -> int:
    """Write the serialized bundle to --output, or stdout if not given."""
    if not output:
        print(content, end="")
        return 0
    try:
        atomic_write_text(Path(output), content, refuse_symlink=True)
        print(f"Bundle written to {output}", file=sys.stderr)
        return 0
    except OSError as exc:
        print(f"Error writing to {output}: {exc}", file=sys.stderr)
        return 1


ARGUMENTS: list[ArgSpec] = [
    (("--slug",), {"action": "append", "dest": "slugs", "help": "Include this slug (repeatable)"}),
    (("--type",), {"action": "append", "dest": "types", "help": "Include this type (repeatable)"}),
    (("--all",), {"action": "store_true", "help": "Export every memory"}),
    (("--allow-warn",), {"action": "store_true", "help": "Export despite warn-severity findings"}),
    format_arg(["yaml", "json"], "yaml"),
    (("--output", "-o"), {"default": None, "help": "Output file (default: stdout)"}),
    DRY_RUN_ARG,
    YES_ARG,
]


def run(args: argparse.Namespace) -> int:
    """Export selected memories as a redaction-scanned bundle."""
    # At least one selector is required
    has_selector = bool(args.slugs) or bool(args.types) or args.all
    if not has_selector:
        return validation_error("selector", "export requires at least one selector: --slug, --type, or --all")

    all_stores = discover_stores()
    store = resolve_current_store(all_stores)
    if store is None:
        print("No memory stores found.", file=sys.stderr)
        return 1

    selected = _select_memories(
        store,
        slugs=args.slugs,
        types=args.types,
        include_all=args.all,
    )
    if not selected:
        print("No memories matched the given selectors.", file=sys.stderr)
        return 0

    bundle = build_bundle(selected)

    # Collect all redactions from every exported memory
    all_redactions: list[Redaction] = [
        r for em in bundle.memories for r in em.redactions
    ]

    # Block-severity findings always refuse export — --allow-warn has no effect here
    if has_blocking(tuple(all_redactions)):
        print(
            "Export blocked: bundle contains block-severity redaction findings.",
            file=sys.stderr,
        )
        _print_redaction_summary(all_redactions)
        return 1

    # Warn-severity findings refuse export unless --allow-warn is set
    has_warn = any(r.severity == SEVERITY_WARN for r in all_redactions)
    if has_warn and not args.allow_warn:
        print(
            "Export blocked: bundle contains warn-severity redaction findings. "
            "Pass --allow-warn to export anyway.",
            file=sys.stderr,
        )
        _print_redaction_summary(all_redactions)
        return 1

    # Always print redaction summary to stderr (keeps stdout clean)
    _print_redaction_summary(all_redactions)

    if args.dry_run:
        print(
            f"Dry-run: {len(selected)} memory/memories would be exported.",
            file=sys.stderr,
        )
        return 0

    # Require explicit confirmation unless --yes is set
    if not args.yes and not _confirm_export(len(selected)):
        return 1

    content = serialize_bundle(bundle, fmt=args.format)
    return _write_bundle_output(content, args.output)
