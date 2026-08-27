"""Agentic capsule for the worker CLI."""

from __future__ import annotations


def build_agentic_capsule() -> str:
    """Return the human/LLM-readable agentic capsule text for worker."""
    lines: list[str] = []
    lines.append("agentic: worker")
    lines.append("purpose: Background worker queue and daemon for job processing")
    lines.append("commands:")
    lines.append("  - enqueue: ./bin/worker enqueue --type run_cli --payload-json '{}'")
    lines.append("  - run-once: ./bin/worker run-once")
    lines.append("  - daemon: ./bin/worker daemon")
    lines.append("  - list: ./bin/worker list")
    lines.append("  - status: ./bin/worker status")
    lines.append("  - show: ./bin/worker show <job-id>")
    lines.append("  - requeue-errors: ./bin/worker requeue-errors")
    lines.append("  - retry: ./bin/worker retry <job-id>")
    lines.append("  - purge: ./bin/worker purge")
    lines.append("notes:")
    lines.append("  - jobs are file-based; queue lives under the configured data dir")
    lines.append("  - run-once processes up to N pending jobs in a single pass (use for batch)")
    lines.append("  - daemon polls continuously; use for persistent background processing")
    return "\n".join(lines)


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
