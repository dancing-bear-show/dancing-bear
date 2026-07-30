"""Health checks for OTel telemetry infrastructure."""

from __future__ import annotations

import os
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
    grpc_port = os.environ.get("OTEL_GRPC_PORT", "4327")
    print(
        f"\nOpenTelemetry infrastructure not found\n\n"
        f"The telemetry CLI requires a local OTel collector to be running.\n\n"
        f"To set up:\n"
        f"  1. Run: docker compose -f docker-compose.otel.yaml up -d\n"
        f"  2. Export these in your shell profile — port {grpc_port} is this\n"
        f"     shell's current OTEL_GRPC_PORT (4327 is the default when that\n"
        f"     var is unset). The compose file reads OTEL_GRPC_PORT, it\n"
        f"     doesn't set it — keep it the same in both the shell that ran\n"
        f"     `docker compose up` and this one. Never use 4328 — that's the\n"
        f"     HTTP port, not gRPC:\n"
        f"       export CLAUDE_CODE_ENABLE_TELEMETRY=1\n"
        f"       export OTEL_METRICS_EXPORTER=otlp\n"
        f"       export OTEL_LOGS_EXPORTER=otlp\n"
        f"       export OTEL_EXPORTER_OTLP_PROTOCOL=grpc\n"
        f"       export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:{grpc_port}\n"
        f"  3. Restart Claude Code or open a new terminal\n"
        f"  4. Try again\n\n"
        f"Setup details:\n"
        f"  - Creates: {data_dir}\n"
        f"    (this reflects TELEMETRY_DATA_DIR if set, else ~/.config/otel.\n"
        f"    docker-compose.otel.yaml's bind mount is controlled by a\n"
        f"    different var, OTEL_DATA_DIR — they default to the same path,\n"
        f"    but if you override one you must override both to match.)\n"
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
