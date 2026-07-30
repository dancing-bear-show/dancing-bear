"""Health checks for OTel telemetry infrastructure."""

from __future__ import annotations

import sys
from pathlib import Path

from telemetry.otel.reader import OTLPDataDir


def check_otel_infrastructure() -> bool:
    """Check if OTel telemetry infrastructure is available.

    Returns:
        True if infrastructure is ready, False otherwise.
        Prints a helpful message to stderr if missing.
    """
    data_dir = OTLPDataDir.from_env()

    if not data_dir.path.exists():
        _print_no_infrastructure_message(data_dir.path)
        return False

    has_any_file = any(
        (data_dir.path / f).exists()
        for f in ("metrics.jsonl", "events.jsonl", "spans.jsonl")
    )

    if not has_any_file:
        _print_no_infrastructure_message(data_dir.path)
        return False

    return True


def _print_no_infrastructure_message(data_dir: Path) -> None:
    """Print helpful message when OTel infrastructure is not set up."""
    print(
        f"\nOpenTelemetry infrastructure not found\n\n"
        f"The telemetry CLI requires a local OTel collector to be running.\n\n"
        f"To set up:\n"
        f"  1. Run: docker compose -f docker-compose.otel.yaml up -d\n"
        f"  2. Export these in your shell profile (protocol must be gRPC —\n"
        f"     the endpoint's port is the collector's *gRPC* host port, not\n"
        f"     its HTTP port):\n"
        f"       export CLAUDE_CODE_ENABLE_TELEMETRY=1\n"
        f"       export OTEL_METRICS_EXPORTER=otlp\n"
        f"       export OTEL_LOGS_EXPORTER=otlp\n"
        f"       export OTEL_EXPORTER_OTLP_PROTOCOL=grpc\n"
        f"       export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:${{OTEL_GRPC_PORT:-4327}}\n"
        f"     (OTEL_GRPC_PORT must match the host port bound to container\n"
        f"     port 4317 in docker-compose.otel.yaml)\n"
        f"  3. Restart Claude Code or open a new terminal\n"
        f"  4. Try again\n\n"
        f"Setup details:\n"
        f"  - Creates: {data_dir}\n"
        f"  - Starts: Docker container with OTel collector\n"
        f"  - Data files: metrics.jsonl, events.jsonl, spans.jsonl\n",
        file=sys.stderr,
    )


def require_otel_infrastructure() -> None:
    """Ensure OTel infrastructure exists, exit cleanly if not.

    Raises:
        SystemExit: with code 1 if infrastructure is not available.
    """
    if not check_otel_infrastructure():
        sys.exit(1)
