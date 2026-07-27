"""prune subcommand — prune old telemetry data."""

from __future__ import annotations

import argparse
from pathlib import Path

from telemetry.otel.cli._format_helpers import format_validation_error
from telemetry.otel.config import DataTypeRetention, RetentionConfig, load_retention_config
from telemetry.otel.reader import OTLPDataDir, OTLPReader
from telemetry.otel.retention import TelemetryPruner


def main(argv: list[str] | None = None) -> int:
    """Prune old telemetry data."""
    parser = argparse.ArgumentParser(
        prog="telemetry prune",
        description="Prune old telemetry data",
    )
    parser.add_argument(
        "--older-than",
        type=int,
        help="Delete records older than N days",
    )
    parser.add_argument(
        "--type",
        choices=["all", "metrics", "events", "spans"],
        default="all",
        help="Data type to prune (default: all)",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be deleted without making changes (default behavior)",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the data (required to make changes)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        help="Override default data directory",
    )

    args = parser.parse_args(argv)

    if args.data_dir:
        data_dir = OTLPDataDir(path=Path(args.data_dir))
    else:
        data_dir = OTLPDataDir.from_env()

    reader = OTLPReader(data_dir)

    config = load_retention_config()

    if args.older_than is not None:
        config = RetentionConfig(
            metrics=DataTypeRetention(keep_days=args.older_than),
            events=DataTypeRetention(keep_days=args.older_than),
            spans=DataTypeRetention(keep_days=args.older_than),
            min_records_after_prune=config.min_records_after_prune,
        )

    pruner = TelemetryPruner(reader, config)

    dry_run = not args.apply

    try:
        if args.type == "all":
            results = pruner.prune_all(dry_run=dry_run)
        else:
            result = pruner.prune(args.type, dry_run=dry_run)
            results = [result]
    except ValueError as e:
        return format_validation_error("prune", str(e))

    for result in results:
        print(f"\n{result.data_type.upper()}:")
        print(
            f"  Before: {result.records_before} records "
            f"({result.bytes_before:,} bytes)"
        )
        print(
            f"  After:  {result.records_after} records "
            f"({result.bytes_after:,} bytes)"
        )
        print(
            f"  Removed: {result.records_removed} records "
            f"({result.bytes_removed:,} bytes)"
        )
        if result.dry_run:
            print("  (DRY RUN — no changes made)")

    return 0
