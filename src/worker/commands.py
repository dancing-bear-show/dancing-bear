"""Worker command classes.

Each command is extracted into its own class for maintainability and testability.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from core.cli_errors import CLIError, ExitCode
from core.cli_output import OutputWriter, emit_one
from core.date_utils import iso_now, now_utc, parse_iso_utc, parse_window
from worker._helpers import (
    DATE_FORMAT_YMD,
    ISO_DATETIME_FORMAT,
)
from worker import queue_ops as q
from worker.queue_ops import QUEUE_FOLDERS
from worker.queue_metrics import counts, status

logger = logging.getLogger(__name__)


# ============================================================================
# Command Classes
# ============================================================================


class EnqueueCommand:
    """Enqueue a new job to the queue."""

    @staticmethod
    def run(args) -> int:
        """Execute enqueue command."""
        payload = {}
        try:
            payload = json.loads(str(getattr(args, "payload_json", "") or "{}"))
        except Exception:
            logger.exception("Invalid --payload-json")
            return 2

        job_id = str(getattr(args, "job_id", "") or uuid.uuid4().hex)
        job = q.Job(
            id=job_id,
            type=str(args.type),
            payload=payload,
            priority=int(getattr(args, "priority", 5) or 5),
            not_before=str(getattr(args, "not_before", "") or ""),
            attempts=0,
            max_attempts=int(getattr(args, "max_attempts", 3) or 3),
            enqueued_at=iso_now(),
        )

        path = q.enqueue(job, root=q.QUEUE_ROOT)
        emit_one({"enqueued": True, "id": job_id, "path": str(path)}, fmt="jsonl")
        return 0


class ListCommand:
    """List queue counts."""

    @staticmethod
    def run(args) -> int:
        """Execute list command."""
        emit_one(counts(root=q.QUEUE_ROOT))
        return 0


class StatusCommand:
    """Show queue status with optional throughput metrics."""

    @staticmethod
    def run(args, writer: OutputWriter | None = None) -> int:
        """Execute status command."""
        s = status(root=q.QUEUE_ROOT)

        if getattr(args, "text", False) and not getattr(args, "json", False):
            StatusCommand._print_text_status(s, args, writer=writer)
        else:
            emit_one(s)

        return 0

    @staticmethod
    def _print_text_status(
        status: dict[str, object], args, writer: OutputWriter | None = None
    ) -> None:
        """Print human-readable status."""
        out = writer or OutputWriter()
        nxt = status.get("next_scheduled_in_sec")
        nxt_txt = f"{nxt}s" if nxt is not None else "-"
        counts: dict[str, object] = (
            status.get("counts") if isinstance(status.get("counts"), dict) else {}
        )
        error_ids: list[str] = (
            status.get("recent_error_ids")
            if isinstance(status.get("recent_error_ids"), list)
            else []
        )

        lines = [
            f"Queue root: {status.get('root')}",
            "Counts: " + " ".join(f"{f}={counts.get(f, 0)}" for f in QUEUE_FOLDERS),
            f"Pending by priority: {status.get('pending_by_priority', {})}",
            f"Oldest pending wait: {status.get('oldest_pending_wait_sec', 0)}s",
            f"Next scheduled in: {nxt_txt}",
            f"Oldest processing age: {status.get('processing_oldest_age_sec', 0)}s",
            f"Recent errors: {', '.join(error_ids) or '-'}",
        ]

        if getattr(args, "with_throughput", False):
            throughput_line = StatusCommand._calculate_throughput()
            if throughput_line:
                lines.append(throughput_line)

        out.print("\n".join(lines))

    @staticmethod
    def _load_completed_job_rows(path: Path) -> list[dict]:
        """Parse today's perf log, keeping only successful daemon run_cli records."""
        rows: list[dict] = []
        for line in path.open("r", encoding="utf-8"):
            try:
                rec = json.loads(line)
            except Exception:  # nosec B112 - skip malformed log lines
                continue
            if rec.get("args") == ["daemon", "run_cli", "ok"]:
                rows.append(rec)
        return rows

    @staticmethod
    def _format_throughput(rows: list[dict]) -> str:
        rows.sort(key=lambda r: r.get("ts", ""))
        start = datetime.strptime(rows[0]["ts"], ISO_DATETIME_FORMAT)
        end = datetime.strptime(rows[-1]["ts"], ISO_DATETIME_FORMAT)
        secs = max(1, (end - start).total_seconds())
        rate = len(rows) / secs * 60.0
        avg_ms = sum(int(r.get("duration_ms", 0)) for r in rows) / max(1, len(rows))
        return f"Throughput (today): {rate:.2f} jobs/min, avg {avg_ms:.0f} ms/job"

    @staticmethod
    def _calculate_throughput() -> str | None:
        """Calculate throughput from today's perf log."""
        try:
            ymd = datetime.now(UTC).strftime(DATE_FORMAT_YMD)
            path = Path.cwd() / "_data" / "logs" / f"perf-worker-{ymd}.jsonl"
            if not path.exists():
                return None
            rows = StatusCommand._load_completed_job_rows(path)
            if not rows:
                return None
            return StatusCommand._format_throughput(rows)
        except Exception:  # nosec B110 - best-effort throughput calculation
            return None


class ShowCommand:
    """Show a job by ID."""

    @staticmethod
    def run(args, writer: OutputWriter | None = None) -> int:
        """Execute show command."""
        out = writer or OutputWriter()
        jid = str(args.id)
        root = q.QUEUE_ROOT

        for folder in QUEUE_FOLDERS:
            p = root / folder / f"{jid}.json"
            if p.exists():
                out.print(p.read_text(encoding="utf-8"))
                return 0

        raise CLIError(f"Job not found: {jid}", code=ExitCode.NOT_FOUND)


class RequeueErrorsCommand:
    """Requeue error jobs with optional filtering."""

    @staticmethod
    def run(args) -> int:
        """Execute requeue-errors command."""
        limit = int(getattr(args, "limit", 0) or 0) or None
        delay = int(getattr(args, "delay", 0) or 0)
        reset = bool(getattr(args, "reset_attempts", False))
        newmax = int(getattr(args, "new_max_attempts", 0) or 0) or None
        since = getattr(args, "since", None)
        match = [str(m) for m in (getattr(args, "match", []) or [])]

        items = q.list_error(root=q.QUEUE_ROOT)
        items = RequeueErrorsCommand._apply_since_filter(items, since)
        items = RequeueErrorsCommand._apply_match_filter(items, match)

        if limit is not None:
            items = items[: int(limit)]

        paths: list[Path] = []
        for p, _ in items:
            paths.append(
                q.requeue_error(
                    p,
                    delay_sec=delay,
                    root=q.QUEUE_ROOT,
                    reset_attempts=reset,
                    new_max_attempts=newmax,
                )
            )

        emit_one({"requeued": len(paths), "paths": [str(p) for p in paths]})
        return 0

    @staticmethod
    def _apply_since_filter(
        items: list[tuple[Path, dict]], since: str | None
    ) -> list[tuple[Path, dict]]:
        """Filter items by time window."""
        if not since:
            return items

        try:
            win = parse_window(since)
            cutoff = now_utc() - win

            def _ts(d):
                s = d.get("updated_at") or d.get("enqueued_at") or ""
                dt = parse_iso_utc(s)
                return dt if dt else now_utc()

            return [(p, d) for (p, d) in items if _ts(d) >= cutoff]
        except Exception:  # nosec B110 - best-effort filter; return all on error
            return items

    @staticmethod
    def _apply_match_filter(
        items: list[tuple[Path, dict]], match: list[str]
    ) -> list[tuple[Path, dict]]:
        """Filter items by string matching."""
        if not match:
            return items

        def _has(d) -> bool:
            try:
                blob = json.dumps(d)
            except Exception:  # nosec B110 - fallback to str repr
                blob = str(d)
            return all(m.lower() in blob.lower() for m in match)

        return [(p, d) for (p, d) in items if _has(d)]


class RetryCommand:
    """Retry a specific error job by ID."""

    @staticmethod
    def run(args) -> int:
        """Execute retry command."""
        jid = str(args.id)
        p = q.find_job_path_by_id(jid, root=q.QUEUE_ROOT)

        if not p or p.parent.name != "error":
            raise CLIError(f"Job {jid!r} not found in error/", code=ExitCode.NOT_FOUND)

        np = q.requeue_error(
            p,
            delay_sec=int(getattr(args, "delay", 0) or 0),
            root=q.QUEUE_ROOT,
            reset_attempts=bool(getattr(args, "reset_attempts", False)),
            new_max_attempts=(int(getattr(args, "new_max_attempts", 0) or 0) or None),
        )

        emit_one({"requeued": True, "path": str(np)})
        return 0


class PurgeCommand:
    """Purge old jobs from done/error folders."""

    @staticmethod
    def run(args) -> int:
        """Execute purge command."""
        win = parse_window(str(getattr(args, "older_than", "30d")))
        secs = int(win.total_seconds())
        folders = [
            s.strip()
            for s in str(getattr(args, "folders", "done,error")).split(",")
            if s.strip()
        ]

        res = q.purge(secs, root=q.QUEUE_ROOT, folders=folders)
        emit_one(res)
        return 0
