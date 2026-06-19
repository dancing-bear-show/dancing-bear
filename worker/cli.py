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


class WorkerApp:
    prog = "worker"
    description = "Background worker queue and daemon"

    def agentic_extras(self) -> dict:
        """Provide LLM-friendly examples and notes."""
        return {
            "category": "worker",
            "note": "Valid subcommands: enqueue, run-once, daemon, list, status, show, requeue-errors, retry, purge.",
            "flows": [
                {"id": "worker_enqueue", "desc": "Enqueue a job", "cmd": "./bin/worker enqueue --type run_cli --payload-json '{\"cmd\": [\"mail-assistant\", \"list\"]}'", "params": {}},
                {"id": "worker_daemon", "desc": "Start daemon (poll every 5 sec)", "cmd": "./bin/worker daemon", "params": {}},
                {"id": "worker_daemon_custom", "desc": "Start daemon with custom interval", "cmd": "./bin/worker daemon --interval 10 --max-per-tick 5", "params": {}},
                {"id": "worker_list", "desc": "Show queue counts", "cmd": "./bin/worker list", "params": {}},
                {"id": "worker_status", "desc": "Show detailed status", "cmd": "./bin/worker status --with-throughput", "params": {}},
            ],
            "common_commands": ["daemon", "enqueue", "list", "status"],
            "validation": "Subcommand is required. Use './bin/worker --help' to see available subcommands.",
        }

    def build_parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog=self.prog, description=self.description)
        sub = p.add_subparsers(dest="command")

        enq = sub.add_parser("enqueue", help="Enqueue a job")
        enq.add_argument("--type", required=True, choices=sorted(HANDLERS.keys()))
        enq.add_argument("--payload-json", default="{}", help="JSON payload for the job")
        enq.add_argument("--priority", type=int, default=5)
        enq.add_argument("--not-before", dest="not_before", default="", help="Process no earlier than this ISO time (UTC)")
        enq.add_argument("--max-attempts", type=int, default=3)
        enq.add_argument("--id", dest="job_id", default="")

        ro = sub.add_parser("run-once", help="Process up to N pending jobs once")
        ro.add_argument("--max", type=int, default=5, help="Max jobs to process this run")
        ro.add_argument("--backoff", type=int, default=60, help="Retry backoff seconds (default 60)")

        dm = sub.add_parser("daemon", help="Run in a loop, polling for work")
        dm.add_argument("--interval", default="5", help="Poll interval seconds (default 5)")
        dm.add_argument("--max-per-tick", type=int, default=3)
        dm.add_argument("--backoff", type=int, default=60)
        dm.add_argument("--max-inflight", type=int, default=0, help="Hard cap of concurrent processing jobs; 0 disables clamping")
        dm.add_argument("--job-timeout", type=int, default=0, help="Job timeout in seconds; 0 disables timeout (default 0)")

        sub.add_parser("list", help="Show queue counts")
        st = sub.add_parser("status", help="Show detailed worker/queue status summary")
        st.add_argument("--json", action="store_true", help="Output JSON (default)")
        st.add_argument("--text", action="store_true", help="Output human-readable text")
        st.add_argument("--with-throughput", action="store_true", help="Include recent jobs/min and avg duration (perf logs)")
        sh = sub.add_parser("show", help="Show a job JSON by id")
        sh.add_argument("id")
        rq = sub.add_parser("requeue-errors", help="Move jobs from error/ back to pending/")
        rq.add_argument("--limit", type=int, default=0, help="Max number of error jobs to requeue (default all)")
        rq.add_argument("--delay", type=int, default=0, help="Delay seconds before requeued jobs become eligible (default 0)")
        rq.add_argument("--reset-attempts", action="store_true", help="Reset attempts to 0 for requeued jobs")
        rq.add_argument("--new-max-attempts", type=int, default=0, help="Override max_attempts for requeued jobs (0=leave unchanged)")
        rq.add_argument("--since", default=None, help="Only requeue errors updated within window (e.g., 2d, 6h)")
        rq.add_argument("--match", action="append", help="Only requeue errors whose JSON contains this substring (repeatable)")

        rt = sub.add_parser("retry", help="Requeue a single error job by id")
        rt.add_argument("id", help="Job id (without .json)")
        rt.add_argument("--delay", type=int, default=0)
        rt.add_argument("--reset-attempts", action="store_true")
        rt.add_argument("--new-max-attempts", type=int, default=0)

        pg = sub.add_parser("purge", help="Delete old done/error jobs")
        pg.add_argument("--older-than", default="30d", help="Age threshold (e.g., 7d, 24h). Default 30d")
        pg.add_argument("--folders", default="done,error", help="Comma-separated folders (done,error)")
        return p

    @staticmethod
    def _parse_interval(args: argparse.Namespace) -> float | None:
        """Parse and validate --interval; returns None and prints error on failure."""
        import sys
        raw = getattr(args, "interval", "5")
        try:
            value = float(str(raw))
            if value <= 0:
                raise ValueError("must be positive")
            return value
        except ValueError:
            print(f"error: --interval must be a positive number, got {raw!r}", file=sys.stderr)
            return None

    def _run_processor(self, args: argparse.Namespace, cmd: str) -> int:
        """Build config and run a job processor for run-once or daemon."""
        interval = self._parse_interval(args)
        if interval is None:
            return 1
        config = WorkerConfig(
            backoff=int(getattr(args, "backoff", 60) or 60),
            max_per_tick=int(getattr(args, "max", getattr(args, "max_per_tick", 3))),
            max_inflight=int(getattr(args, "max_inflight", 0) or 0),
            job_timeout=int(getattr(args, "job_timeout", 0) or 0),
            interval=interval,
        )
        processor = JobProcessor(config, cmd)
        runner = DaemonRunner(config, processor)
        if cmd == "run-once":
            return runner.run_once()
        return runner.run_daemon()

    def run(self, args: argparse.Namespace) -> int:
        """Execute worker command using command pattern."""
        import sys
        cmd = args.command

        dispatch: dict[str, object] = {
            "enqueue": lambda: EnqueueCommand.run(args),
            "list": lambda: ListCommand.run(args),
            "status": lambda: StatusCommand.run(args),
            "show": lambda: ShowCommand.run(args),
            "requeue-errors": lambda: RequeueErrorsCommand.run(args),
            "retry": lambda: RetryCommand.run(args),
            "purge": lambda: PurgeCommand.run(args),
        }

        if cmd in dispatch:
            return dispatch[cmd]()  # type: ignore[operator]

        if cmd in {"run-once", "daemon"}:
            return self._run_processor(args, cmd)

        print("Usage: worker {enqueue|run-once|daemon|list|status|show|requeue-errors|retry|purge} --help", file=sys.stderr)
        return 1

    def main(self, argv: list[str] | None = None) -> int:
        """Parse arguments and run the command."""
        parser = self.build_parser()
        args = parser.parse_args(argv)
        return self.run(args)


def main(argv: list[str] | None = None) -> int:
    """Entry point for bin/worker."""
    return WorkerApp().main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
