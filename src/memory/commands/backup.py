"""CLI subcommand: back up memory stores to a local-only git repo.

Delegates all git work to memory.backup — this module constructs
no subprocess commands itself. --status is strictly read-only; all other
invocations require --store or --all-stores.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from core.cli_output import emit_one
from core.paths import output_dir
from memory.commands._common import (
    ALL_STORES_ARG,
    STORE_ARG,
    ArgSpec,
    exclusive_store_scope,
    format_arg,
    validation_error,
)
from memory.backup import backup_status, backup_stores
from memory.discovery import discover_stores, load_store


def default_backup_dest() -> Path:
    """``<data-home>/memory/backup`` — resolved per call so env overrides apply."""
    return output_dir("memory") / "backup"


ARGUMENTS: list[ArgSpec] = [
    (("--status",), {"action": "store_true", "help": "Report last backup and dirty state (read-only)"}),
    STORE_ARG,
    ALL_STORES_ARG,
    (("--dest",), {"default": None, "help": "Backup repo (default: <data-home>/memory/backup)"}),
    (("--message",), {"default": None, "help": "Commit message (default: ISO timestamp)"}),
    format_arg(["json", "table"], "json"),
]


def run(args: argparse.Namespace) -> int:
    """Back up memory stores into a local-only git repository."""
    scope_error = exclusive_store_scope(args.store, args.all_stores)
    if scope_error is not None:
        return scope_error

    dest = Path(args.dest).expanduser() if args.dest else default_backup_dest()

    if args.status:
        status = backup_status(dest)
        return emit_one(asdict(status), args.format)

    # A target must be specified for actual backup operations
    if not args.store and not args.all_stores:
        return validation_error("target", "specify --store <slug> or --all-stores")

    if args.all_stores:
        stores = discover_stores()
    else:
        try:
            stores = (load_store(args.store),)
        except Exception as exc:  # NOSONAR - CLI boundary: surface as a validation error, never a raw traceback
            return validation_error("--store", f"could not load store {args.store!r}: {exc}")

    if not stores:
        print("No stores to back up.", file=sys.stderr)
        return 0

    try:
        result = backup_stores(stores, dest, message=args.message)
    except Exception as exc:  # NOSONAR - CLI boundary: a failed backup must report, never crash with a traceback
        print(f"Error: backup failed: {exc}", file=sys.stderr)
        return 1

    if result.failed:
        # backup_stores signals a genuine git-subprocess failure (as opposed
        # to the commit_sha=None "nothing to commit" no-op) via result.failed
        # rather than an exception — surface it as a non-zero exit here.
        # Checked BEFORE emit_one so a failure never prints misleading
        # success-shaped JSON/table output to stdout first.
        print(f"Error: {result.message}", file=sys.stderr)
        return 1

    emit_one(
        {
            "dest": result.dest,
            "files_staged": len(result.files_staged),
            "commit_sha": result.commit_sha,
            "message": result.message,
            "created_repo": result.created_repo,
        },
        args.format,
    )
    return 0
