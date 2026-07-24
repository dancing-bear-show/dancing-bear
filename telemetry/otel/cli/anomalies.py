"""anomalies subcommand — detect anomalous sessions via z-score."""

from __future__ import annotations

import argparse

from core.cli_output import emit_rows
from telemetry.otel.analytics.anomaly import detect_anomalies
from telemetry.otel.cli._format_helpers import (
    add_data_dir_argument,
    add_format_argument,
    add_since_argument,
    resolve_data_dir,
    resolve_since,
    truncate_sid,
)


def main(argv: list[str] | None = None) -> int:
    """Detect anomalous sessions using z-score analysis."""
    parser = argparse.ArgumentParser(
        prog="telemetry anomalies",
        description="Detect anomalous sessions using z-score analysis",
    )
    add_since_argument(parser)
    parser.add_argument(
        "--threshold",
        type=float,
        default=2.0,
        help="Z-score threshold for flagging (default: 2.0)",
    )
    add_format_argument(parser, formats=["table", "json"], default="table")
    add_data_dir_argument(parser)

    args = parser.parse_args(argv)
    data_dir = resolve_data_dir(args, allow_none=True)
    since, err = resolve_since(args)
    if err is not None:
        return err

    flags = detect_anomalies(
        data_dir=data_dir, since=since, threshold=args.threshold
    )

    headers = ["session_id", "metric", "value", "mean", "z_score"]
    rows = [
        {
            "session_id": truncate_sid(f.session_id),
            "metric": f.metric,
            "value": round(f.value, 4),
            "mean": round(f.mean, 4),
            "z_score": round(f.z_score, 2),
        }
        for f in flags
    ]
    return emit_rows(rows, args.format, headers=headers, empty_msg="No anomalies detected.")
