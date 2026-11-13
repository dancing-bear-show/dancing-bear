"""CLI subcommand: graduate a memory from a non-canonical store into the canonical store."""

from __future__ import annotations

import argparse
import sys

from core.cli_output import emit_rows
from memory.commands._common import DRY_RUN_ARG, STORE_ARG, ArgSpec, format_arg, validation_error
from memory.discovery import (
    discover_stores,
    elect_canonical,
    load_store,
    resolve_current_store,
)
from memory.graduate import GraduateError, graduate_memory

_GRADUATE_HEADERS = ["slug", "action", "canonical_store", "source_store"]


ARGUMENTS: list[ArgSpec] = [
    (("slug",), {"nargs": "?", "help": "Memory slug or unique prefix"}),
    STORE_ARG,
    format_arg(["table", "json"], "table"),
    DRY_RUN_ARG,
    (("--yes",), {"action": "store_true", "help": "Overwrite a diverged canonical copy"}),
]


def run(args: argparse.Namespace) -> int:
    """Promote a memory from a non-canonical store into the canonical store."""
    if not args.slug:
        return validation_error("slug", "required argument missing")

    all_stores = discover_stores()

    if args.store:
        try:
            source = load_store(args.store)
        except Exception as exc:  # NOSONAR - CLI boundary: surface as validation error
            return validation_error("--store", f"could not load store {args.store!r}: {exc}")
    else:
        resolved = resolve_current_store(all_stores)
        if resolved is None:
            print("No memory stores found.", file=sys.stderr)
            return 1
        source = resolved

    # inferred_repo=None means the slug couldn't be decoded to a repo path —
    # we can't safely identify which canonical store to target.
    if source.inferred_repo is None:
        return validation_error(
            "store",
            "cannot graduate: source store has no decodable repo path (inferred_repo=None). "
            "Use --store to specify a store with a known repo path.",
        )

    # Find canonical store for the same inferred_repo
    same_repo = tuple(s for s in all_stores if s.inferred_repo == source.inferred_repo)
    canonical = elect_canonical(same_repo) if same_repo else None

    if canonical is None:
        return validation_error("store", f"no canonical store found for repo '{source.inferred_repo}'")

    try:
        result = graduate_memory(
            args.slug,
            source,
            canonical,
            dry_run=args.dry_run,
            yes=args.yes,
        )
    except GraduateError as exc:
        return validation_error("slug", str(exc))

    row = {
        "slug": result.slug,
        "action": result.action,
        "canonical_store": canonical.project_slug,
        "source_store": source.project_slug,
    }
    return emit_rows([row], args.format, headers=_GRADUATE_HEADERS)
