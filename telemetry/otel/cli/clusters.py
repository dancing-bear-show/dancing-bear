"""clusters subcommand — session clustering analysis."""

from __future__ import annotations

import argparse

from core.cli_output import emit_rows
from telemetry.otel.analytics.clustering import cluster_sessions
from telemetry.otel.cli._format_helpers import (
    add_data_dir_argument,
    add_format_argument,
    add_since_argument,
    resolve_data_dir,
    resolve_since,
    truncate_sid,
)


def main(argv: list[str] | None = None) -> int:
    """Cluster sessions by cost and token features."""
    parser = argparse.ArgumentParser(
        prog="telemetry clusters",
        description="Cluster sessions by cost and token features",
    )
    add_since_argument(parser)
    parser.add_argument(
        "--clusters",
        type=int,
        default=3,
        help="Number of clusters (default: 3)",
    )
    add_format_argument(parser, formats=["table", "json"], default="table")
    add_data_dir_argument(parser)

    args = parser.parse_args(argv)
    data_dir = resolve_data_dir(args, allow_none=True)
    since, err = resolve_since(args)
    if err is not None:
        return err

    results = cluster_sessions(
        data_dir=data_dir, since=since, n_clusters=args.clusters
    )

    headers = ["cluster", "session_id", "cost", "tokens"]
    rows = [
        {
            "cluster": r.cluster_label,
            "session_id": truncate_sid(r.session_id),
            "cost": (
                f"${r.features.get('cost', 0):.4f}"
                if args.format == "table"
                else r.features.get("cost", 0)
            ),
            "tokens": (
                f"{r.features.get('billable_tokens', 0):,.0f}"
                if args.format == "table"
                else r.features.get("billable_tokens", 0)
            ),
        }
        for r in results
    ]
    return emit_rows(rows, args.format, headers=headers, empty_msg="No session data for clustering.")
