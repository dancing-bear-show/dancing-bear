"""query subcommand — query metrics."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.cli_output import emit_rows
from telemetry.otel.cli._format_helpers import add_format_argument, format_validation_error
from telemetry.otel.reader import OTLPDataDir, OTLPReader
from telemetry.otel.utils import parse_time_window

if TYPE_CHECKING:
    from telemetry.otel.models import OTLPMetric, OTLPMetricsRecord


def main(argv: list[str] | None = None) -> int:
    """Query metrics."""
    parser = argparse.ArgumentParser(
        prog="telemetry query",
        description="Query metrics by pattern",
    )
    parser.add_argument(
        "--metric",
        type=str,
        help="Metric name pattern (fnmatch glob)",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Time range (e.g., '1h', '24h', '7d')",
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

    records = reader.read_metrics()

    try:
        cutoff_time = parse_time_window(args.since)
    except ValueError as e:
        return format_validation_error("--since", str(e))

    filtered_metrics = _filter_metrics(records, args.metric, cutoff_time)

    return _output_query_results(filtered_metrics, args.format)


def _filter_metrics(
    records: list[OTLPMetricsRecord], metric_pattern: str | None, cutoff_time: datetime | None
) -> list:
    """Filter metrics by pattern and time window."""
    filtered = []
    for record in records:
        metrics = _select_metrics_by_pattern(record, metric_pattern)
        for metric in metrics:
            data_points = _filter_data_points(metric.data_points, cutoff_time)
            if data_points:
                filtered.append(_build_metric_result(metric, data_points))
    return filtered


def _select_metrics_by_pattern(record: OTLPMetricsRecord, metric_pattern: str | None) -> list:
    """Select metrics by pattern from a record."""
    if metric_pattern:
        return record.metrics_by_name(metric_pattern)
    return record.metrics


def _filter_data_points(
    data_points: list, cutoff_time: datetime | None
) -> list:
    """Filter data points by time window."""
    if cutoff_time:
        return [dp for dp in data_points if dp.timestamp >= cutoff_time]
    return data_points


def _build_metric_result(metric: OTLPMetric, data_points: list) -> dict:
    """Build a metric result dict from metric and data points."""
    return {
        "name": metric.name,
        "unit": metric.unit,
        "points": len(data_points),
        "latest": data_points[-1].value if data_points else None,
    }


def _output_query_results(metrics: list, format_type: str) -> int:
    """Output query results in specified format."""
    if format_type == "json":
        return emit_rows(metrics, "json")

    if not metrics:
        print("No metrics found")
        return 0

    headers = ["Name", "Unit", "Points", "Latest"]
    return emit_rows(metrics, format_type, headers=headers)
