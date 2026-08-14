"""clear subcommand — clear all telemetry data."""

from __future__ import annotations

import argparse
from pathlib import Path

from telemetry.otel.reader import OTLPDataDir


def main(argv: list[str] | None = None) -> int:  # NOSONAR S3516 - CLI entry point; multiple return paths all return 0
    """Clear telemetry data."""
    parser = argparse.ArgumentParser(
        prog="telemetry clear",
        description="Clear telemetry data",
    )
    parser.add_argument(
        "--type",
        choices=["metrics", "events", "spans", "all"],
        default="all",
        help="Data type to clear (default: all)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm deletion without prompting",
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

    if not args.confirm:
        print(f"Clear telemetry data from {data_dir.path}?")
        response = input("Type 'yes' to confirm: ").strip().lower()
        if response != "yes":
            print("Cancelled.")
            return 0

    if args.type in ("all", "metrics"):
        (data_dir.path / "metrics.jsonl").unlink(missing_ok=True)
        print("Cleared metrics.jsonl")
    if args.type in ("all", "events"):
        (data_dir.path / "events.jsonl").unlink(missing_ok=True)
        print("Cleared events.jsonl")
    if args.type in ("all", "spans"):
        (data_dir.path / "spans.jsonl").unlink(missing_ok=True)
        print("Cleared spans.jsonl")

    return 0
