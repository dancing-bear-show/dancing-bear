"""stats subcommand — show telemetry statistics."""

from __future__ import annotations

import argparse
from pathlib import Path

from core.cli_output import emit_one
from telemetry.otel.cli._format_helpers import add_format_argument
from telemetry.otel.reader import OTLPDataDir, OTLPReader


def main(argv: list[str] | None = None) -> int:
    """Show telemetry statistics."""
    parser = argparse.ArgumentParser(
        prog="telemetry stats",
        description="Show telemetry statistics",
    )
    parser.add_argument(
        "--group-by",
        choices=["metric", "resource"],
        default="metric",
        help="Group by field (default: metric)",
    )
    add_format_argument(parser, formats=["table", "json"], default="table")
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

    if args.group_by == "metric":
        metrics = reader.read_metrics()
        stats = _aggregate_by_metric(metrics)
        return _output_stats(stats, "Metric Statistics", args.format)

    metrics = reader.read_metrics()
    events = reader.read_events()
    spans = reader.read_spans()
    stats = _aggregate_by_resource(metrics, events, spans)
    return _output_stats(stats, "Resource Statistics", args.format)


def _aggregate_by_metric(metrics: list) -> dict:
    """Aggregate metrics by metric name."""
    metric_counts: dict[str, int] = {}
    for record in metrics:
        for metric in record.metrics:
            count = metric_counts.get(metric.name, 0)
            metric_counts[metric.name] = count + len(metric.data_points)
    return metric_counts


def _aggregate_by_resource(metrics: list, events: list, spans: list) -> dict:
    """Aggregate stats by resource (service name)."""
    resource_stats: dict[str, dict[str, int]] = {}

    for record in metrics:
        svc = record.resource.service_name
        if svc not in resource_stats:
            resource_stats[svc] = {"metrics": 0, "events": 0, "spans": 0}
        metric_points = sum(
            len(m.data_points) for m in record.metrics
        )
        resource_stats[svc]["metrics"] += metric_points

    for record in events:
        svc = record.resource.service_name
        if svc not in resource_stats:
            resource_stats[svc] = {"metrics": 0, "events": 0, "spans": 0}
        resource_stats[svc]["events"] += len(record.log_records)

    for record in spans:
        svc = record.resource.service_name
        if svc not in resource_stats:
            resource_stats[svc] = {"metrics": 0, "events": 0, "spans": 0}
        resource_stats[svc]["spans"] += len(record.spans)

    return resource_stats


def _output_stats(stats: dict, title: str, format_type: str) -> int:  # NOSONAR python:S3516 - always returns 0 by design; no error conditions
    """Output statistics in requested format."""
    if format_type == "json":
        emit_one(stats, "json")
        return 0
    print(f"{title}:")
    print("-" * 60)
    for key, value in sorted(stats.items()):
        if isinstance(value, dict):
            print(f"  {key}:")
            print(f"    Metrics: {value['metrics']:,}")
            print(f"    Events: {value['events']:,}")
            print(f"    Spans: {value['spans']:,}")
        else:
            print(f"  {key}: {value:,} data points")
    return 0
