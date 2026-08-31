"""inspect subcommand — inspect telemetry records."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from core.cli_output import emit_rows
from telemetry.otel.cli._format_helpers import add_format_argument
from telemetry.otel.reader import OTLPDataDir, OTLPReader


def main(argv: list[str] | None = None) -> int:
    """Inspect telemetry records."""
    parser = argparse.ArgumentParser(
        prog="telemetry inspect",
        description="Inspect telemetry records",
    )
    parser.add_argument(
        "--type",
        choices=["metrics", "events", "spans"],
        default="metrics",
        help="Data type to inspect (default: metrics)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of records to show (default: 10)",
    )
    add_format_argument(parser, formats=["json", "table"], default="table")
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

    records_by_type: dict[str, Callable[[], list]] = {
        "metrics": reader.read_metrics,
        "events": reader.read_events,
        "spans": reader.read_spans,
    }
    records = records_by_type[str(args.type)]()[:int(str(args.limit))]

    if args.format == "json":
        rows = _build_json_rows(records, args.type)
        return emit_rows(rows, "json")

    rows, headers = _build_table_rows(records, args.type)
    return emit_rows(rows, args.format, headers=headers)


def _build_json_rows(records: list, data_type: str) -> list[dict]:
    """Build rows for JSON output (lowercase keys)."""
    results = []
    for record in records:
        if data_type == "metrics":
            ts = record.earliest_timestamp()
            data = {
                "service": record.resource.service_name,
                "metrics": len(record.metrics),
                "earliest": ts.isoformat() if ts else None,
            }
        elif data_type == "events":
            earliest = min(
                (e.timestamp.isoformat() for e in record.log_records),
                default=None,
            )
            data = {
                "service": record.resource.service_name,
                "events": len(record.log_records),
                "earliest": earliest,
            }
        else:  # spans
            earliest = min(
                (s.start_timestamp.isoformat() for s in record.spans),
                default=None,
            )
            data = {
                "service": record.resource.service_name,
                "spans": len(record.spans),
                "earliest": earliest,
            }
        results.append(data)
    return results


def _build_table_rows(records: list, data_type: str) -> tuple[list[dict], list[str]]:
    """Build display rows and headers for table output."""
    if data_type == "metrics":
        return _metrics_rows(records), ["Service", "Metrics", "Earliest"]
    if data_type == "events":
        return _events_rows(records), ["Service", "Events", "Earliest"]
    return _spans_rows(records), ["Service", "Spans", "Earliest"]


def _metrics_rows(records: list) -> list[dict]:
    """Build rows for metrics table."""
    return [
        {
            "Service": r.resource.service_name,
            "Metrics": len(r.metrics),
            "Earliest": (
                r.earliest_timestamp().isoformat()
                if r.earliest_timestamp()
                else "N/A"
            ),
        }
        for r in records
    ]


def _events_rows(records: list) -> list[dict]:
    """Build rows for events table."""
    return [
        {
            "Service": r.resource.service_name,
            "Events": len(r.log_records),
            "Earliest": min(
                (e.timestamp.isoformat() for e in r.log_records),
                default="N/A",
            ),
        }
        for r in records
    ]


def _spans_rows(records: list) -> list[dict]:
    """Build rows for spans table."""
    return [
        {
            "Service": r.resource.service_name,
            "Spans": len(r.spans),
            "Earliest": min(
                (s.start_timestamp.isoformat() for s in r.spans),
                default="N/A",
            ),
        }
        for r in records
    ]
