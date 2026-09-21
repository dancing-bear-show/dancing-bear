"""size subcommand — show telemetry storage usage."""

from __future__ import annotations

import argparse
from pathlib import Path

from core.cli_output import emit_one, emit_rows
from telemetry.otel.cli._format_helpers import add_format_argument
from telemetry.otel.reader import OTLPDataDir, OTLPReader


def main(argv: list[str] | None = None) -> int:
    """Show telemetry storage usage."""
    parser = argparse.ArgumentParser(
        prog="telemetry size",
        description="Show telemetry storage usage",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        help="Override default data directory",
    )
    parser.add_argument(
        "--breakdown",
        choices=["metric", "none"],
        default="metric",
        help="Show size breakdown by metric (default: metric)",
    )
    add_format_argument(parser, formats=["table", "json"], default="table")

    args = parser.parse_args(argv)

    if args.data_dir:
        data_dir = OTLPDataDir(path=Path(args.data_dir))
    else:
        data_dir = OTLPDataDir.from_env()

    reader = OTLPReader(data_dir)

    file_sizes = reader.file_sizes()
    total_size = reader.data_dir_size()

    if args.format == "json":
        output = {
            "data_dir": str(data_dir.path),
            "total_bytes": total_size,
            "files": file_sizes,
        }
        emit_one(output, "json")
        return 0

    print(f"Telemetry storage: {data_dir.path}")

    if args.breakdown == "metric":
        metrics_size = f"{file_sizes['metrics.jsonl']:,} B"
        events_size = f"{file_sizes['events.jsonl']:,} B"
        spans_size = f"{file_sizes['spans.jsonl']:,} B"
        total_display = f"{total_size:,} B"
        rows: list[dict[str, object]] = [
            {"File": "metrics.jsonl", "Size": metrics_size},
            {"File": "events.jsonl", "Size": events_size},
            {"File": "spans.jsonl", "Size": spans_size},
            {"File": "TOTAL", "Size": total_display},
        ]
        return emit_rows(rows, "table", headers=["File", "Size"])

    print(f"Total: {total_size:,} B")
    return 0
