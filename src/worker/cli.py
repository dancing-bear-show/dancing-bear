"""Background worker CLI (daemon/queue).

Subcommands:
- enqueue: add a job to the file queue
- run-once: process up to N jobs once
- daemon: poll and process jobs continuously
- list: show queue counts
- status: show detailed worker/queue status
- show: print a job JSON by id
- requeue-errors: move error jobs back to pending
- retry: requeue a single error job by id
- purge: delete old done/error jobs
"""

from __future__ import annotations

import argparse
import sys

from core.cli_errors import UsageError
from core.cli_framework import CLIApp
from worker.commands import (
    DaemonRunner,
    EnqueueCommand,
    JobProcessor,
    ListCommand,
    PurgeCommand,
    RequeueErrorsCommand,
    RetryCommand,
    ShowCommand,
    StatusCommand,
    WorkerConfig,
)
from worker.handlers import REGISTRY as HANDLERS

# ---------------------------------------------------------------------------
# Shared module-level helpers used by the CLIApp run-once/daemon commands
# ---------------------------------------------------------------------------


def _parse_interval(args: argparse.Namespace) -> float:
    """Parse and validate --interval; raises UsageError on invalid input."""
    raw = getattr(args, "interval", "5")
    try:
        value = float(str(raw))
        if value <= 0:
            raise ValueError("must be positive")
        return value
    except ValueError:
        raise UsageError(f"--interval must be a positive number, got {raw!r}")


def _run_processor(args: argparse.Namespace, cmd: str) -> int:
    """Build config and run a job processor for run-once or daemon."""
    interval = _parse_interval(args)
    max_per_tick = args.max if cmd == "run-once" else args.max_per_tick
    config = WorkerConfig(
        backoff=int(getattr(args, "backoff", 60) or 60),
        max_per_tick=int(max_per_tick),
        max_inflight=int(getattr(args, "max_inflight", 0) or 0),
        job_timeout=int(getattr(args, "job_timeout", 0) or 0),
        interval=interval,
    )
    processor = JobProcessor(config, cmd)
    runner = DaemonRunner(config, processor)
    if cmd == "run-once":
        return runner.run_once()
    return runner.run_daemon()


# ---------------------------------------------------------------------------
# CLIApp declarative definition (production entry point)
# ---------------------------------------------------------------------------

app = CLIApp("worker", "Background worker queue and daemon", add_common_args=False)


@app.command("enqueue", help="Enqueue a job")
@app.argument("--type", required=True, choices=sorted(HANDLERS.keys()))
@app.argument("--payload-json", default="{}", help="JSON payload for the job")
@app.argument("--priority", type=int, default=5)
@app.argument("--not-before", dest="not_before", default="", help="Process no earlier than this ISO time (UTC)")
@app.argument("--max-attempts", type=int, default=3)
@app.argument("--id", dest="job_id", default="")
def cmd_enqueue(args: argparse.Namespace) -> int:
    """Enqueue a job."""
    return EnqueueCommand.run(args)


@app.command("run-once", help="Process up to N pending jobs once")
@app.argument("--max", type=int, default=5, help="Max jobs to process this run")
@app.argument("--backoff", type=int, default=60, help="Retry backoff seconds (default 60)")
def cmd_run_once(args: argparse.Namespace) -> int:
    """Process up to N pending jobs once."""
    return _run_processor(args, "run-once")


@app.command("daemon", help="Run in a loop, polling for work")
@app.argument("--interval", default="5", help="Poll interval seconds (default 5)")
@app.argument("--max-per-tick", type=int, default=3)
@app.argument("--backoff", type=int, default=60)
@app.argument("--max-inflight", type=int, default=0, help="Hard cap of concurrent processing jobs; 0 disables clamping")
@app.argument("--job-timeout", type=int, default=0, help="Job timeout in seconds; 0 disables timeout (default 0)")
def cmd_daemon(args: argparse.Namespace) -> int:
    """Run worker daemon."""
    return _run_processor(args, "daemon")


@app.command("list", help="Show queue counts")
def cmd_list(args: argparse.Namespace) -> int:
    """Show queue counts."""
    return ListCommand.run(args)


@app.command("status", help="Show detailed worker/queue status summary")
@app.argument("--json", action="store_true", help="Output JSON (default)")
@app.argument("--text", action="store_true", help="Output human-readable text")
@app.argument("--with-throughput", action="store_true", help="Include recent jobs/min and avg duration (perf logs)")
def cmd_status(args: argparse.Namespace) -> int:
    """Show detailed status."""
    return StatusCommand.run(args)


@app.command("show", help="Show a job JSON by id")
@app.argument("id")
def cmd_show(args: argparse.Namespace) -> int:
    """Show a job by id."""
    return ShowCommand.run(args)


@app.command("requeue-errors", help="Move jobs from error/ back to pending/")
@app.argument("--limit", type=int, default=0, help="Max number of error jobs to requeue (default all)")
@app.argument("--delay", type=int, default=0, help="Delay seconds before requeued jobs become eligible (default 0)")
@app.argument("--reset-attempts", action="store_true", help="Reset attempts to 0 for requeued jobs")
@app.argument("--new-max-attempts", type=int, default=0, help="Override max_attempts for requeued jobs (0=leave unchanged)")
@app.argument("--since", default=None, help="Only requeue errors updated within window (e.g., 2d, 6h)")
@app.argument("--match", action="append", help="Only requeue errors whose JSON contains this substring (repeatable)")
def cmd_requeue_errors(args: argparse.Namespace) -> int:
    """Move error jobs back to pending."""
    return RequeueErrorsCommand.run(args)


@app.command("retry", help="Requeue a single error job by id")
@app.argument("id", help="Job id (without .json)")
@app.argument("--delay", type=int, default=0)
@app.argument("--reset-attempts", action="store_true")
@app.argument("--new-max-attempts", type=int, default=0)
def cmd_retry(args: argparse.Namespace) -> int:
    """Requeue a single error job by id."""
    return RetryCommand.run(args)


@app.command("purge", help="Delete old done/error jobs")
@app.argument("--older-than", default="30d", help="Age threshold (e.g., 7d, 24h). Default 30d")
@app.argument("--folders", default="done,error", help="Comma-separated folders (done,error)")
def cmd_purge(args: argparse.Namespace) -> int:
    """Delete old done/error jobs."""
    return PurgeCommand.run(args)


# ---------------------------------------------------------------------------
# Module-level entry point (production path: delegates to CLIApp)
# ---------------------------------------------------------------------------

def _no_command_usage() -> int:
    """Preserve the legacy no-subcommand behavior (one-line usage to
    stderr, exit 1) rather than CLIApp's default (full --help,
    ExitCode.USAGE), since this is a public CLI surface."""
    print(
        "Usage: worker {enqueue|run-once|daemon|list|status|show|requeue-errors|retry|purge} --help",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    """Entry point for bin/worker."""
    return app.run(argv, on_no_command=_no_command_usage)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
