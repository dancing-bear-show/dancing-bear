"""Health check subcommand for telemetry system."""

from __future__ import annotations

import argparse

from core.cli_output import emit_one
from telemetry.otel.cli._format_helpers import add_format_argument
from telemetry.otel.health import check_otel_infrastructure
from telemetry.otel.reader import OTLPDataDir

METRICS_FILE = "metrics.jsonl"
EVENTS_FILE = "events.jsonl"
SPANS_FILE = "spans.jsonl"
DATA_FILES = [METRICS_FILE, EVENTS_FILE, SPANS_FILE]


def _output_json(data_dir: OTLPDataDir, file_exists: dict[str, bool]) -> None:
    """Output health check results in JSON format."""
    files = {}
    for filename in DATA_FILES:
        if file_exists[filename]:
            file_path = data_dir.path / filename
            size = file_path.stat().st_size
            with open(file_path) as f:
                lines = sum(1 for _ in f)
            files[filename] = {"size": size, "records": lines}
        else:
            files[filename] = {
                "size": 0,
                "records": 0,
                "missing": True,
            }
    output = {
        "status": "healthy",
        "data_dir": str(data_dir.path),
        "files": files,
    }
    emit_one(output, "json")


def _output_text(data_dir: OTLPDataDir, file_exists: dict[str, bool]) -> None:
    """Output health check results in text format."""
    print("OpenTelemetry infrastructure is healthy")
    print(f"Data directory: {data_dir.path}")
    print()
    print("Data files:")
    for filename in DATA_FILES:
        if file_exists[filename]:
            file_path = data_dir.path / filename
            size = file_path.stat().st_size
            with open(file_path) as f:
                lines = sum(1 for _ in f)
            print(f"  OK  {filename} ({size:,} bytes, {lines} records)")
        else:
            print(f"  --  {filename} (not yet created)")


def main(args: list[str] | None = None) -> int:
    """Check OTEL telemetry system health."""
    parser = argparse.ArgumentParser(
        prog="telemetry health",
        description="Check OTEL telemetry system health",
    )
    add_format_argument(parser, formats=["text", "json"], default="text")
    args_parsed = parser.parse_args(args)

    data_dir = OTLPDataDir.from_env()

    infra_ok = check_otel_infrastructure()

    if not infra_ok:
        return 1

    file_exists = {
        METRICS_FILE: (data_dir.path / METRICS_FILE).exists(),
        EVENTS_FILE: (data_dir.path / EVENTS_FILE).exists(),
        SPANS_FILE: (data_dir.path / SPANS_FILE).exists(),
    }

    if any(file_exists.values()):
        if args_parsed.format == "json":
            _output_json(data_dir, file_exists)
        else:
            _output_text(data_dir, file_exists)

        return 0

    return 1  # pragma: no cover
