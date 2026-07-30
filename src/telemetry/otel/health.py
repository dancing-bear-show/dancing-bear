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
        f"  1. Run: ./bin/telemetry collector start\n"
        f"  2. Restart Claude Code or open a new terminal\n"
        f"  3. Try again\n\n"
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
