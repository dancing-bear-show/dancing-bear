"""Parse Claude Code JSONL session transcripts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.date_utils import now_utc, parse_iso_utc
from typing import Any, Iterator

from telemetry.providers.transcript_parse import extract_cache_creation, message_key


PROJECTS_DIR = Path.home() / ".claude" / "projects"


@dataclass
class SessionStats:
    session_id: str
    path: Path
    model: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    events: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    # Output count already added per billed call (message.id, requestId), so the
    # per-content-block copies of one call are counted once.
    seen_output: dict[tuple[str, str | None], int] = field(default_factory=dict, repr=False)

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    @property
    def total_tokens(self) -> int:
        return (self.input_tokens + self.output_tokens +
                self.cache_read_tokens + self.cache_create_tokens)

    def accumulate_usage(
        self, usage: dict[str, Any] | None, key: tuple[str, str | None] | None = None
    ) -> None:
        """Add token counts from a usage dict (null-safe).

        *key* identifies the billed call. A repeat of a call already counted
        adds only its output growth: the other counts were final on, and added
        from, the first copy.
        """
        usage = usage or {}
        output = usage.get("output_tokens") or 0
        if key is not None:
            prev = self.seen_output.get(key)
            if prev is not None:
                if output > prev:
                    self.output_tokens += output - prev
                    self.seen_output[key] = output
                return
            self.seen_output[key] = output
        self.input_tokens += usage.get("input_tokens") or 0
        self.output_tokens += output
        self.cache_read_tokens += usage.get("cache_read_input_tokens") or 0
        self.cache_create_tokens += extract_cache_creation(usage)[0]

    def update_time_range(self, ts: datetime) -> None:
        """Expand the session time range to include ts."""
        if self.start_time is None or ts < self.start_time:
            self.start_time = ts
        if self.end_time is None or ts > self.end_time:
            self.end_time = ts


def iter_session_files(days: int = 7) -> Iterator[Path]:
    """Yield .jsonl files modified within the last N days."""
    if not PROJECTS_DIR.is_dir():
        return
    cutoff = now_utc() - timedelta(days=days)
    for proj in PROJECTS_DIR.iterdir():
        if not proj.is_dir():
            continue
        for jl in proj.glob("*.jsonl"):
            mtime = datetime.fromtimestamp(jl.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                yield jl


def _parse_ts(raw: str) -> datetime | None:
    """Parse ISO 8601 timestamp and normalize to UTC.

    Handles trailing Z and converts all results to UTC so timestamps are
    always comparable regardless of the original offset.
    """
    return parse_iso_utc(raw)


def _process_assistant_record(stats: SessionStats, rec: dict[str, Any]) -> None:
    """Extract model, usage, and tool calls from an assistant record."""
    stats.events += 1
    msg = rec.get("message") or {}

    model = msg.get("model", "")
    if model and not stats.model:
        stats.model = model

    stats.accumulate_usage(msg.get("usage"), message_key(msg.get("id"), rec.get("requestId")))

    for block in msg.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name", "unknown")
            stats.tool_counts[name] = stats.tool_counts.get(name, 0) + 1


def _process_user_record(stats: SessionStats, rec: dict[str, Any]) -> None:
    """Extract subagent token usage from a user message."""
    sub = rec.get("toolUseResult")
    if sub and isinstance(sub, dict):
        stats.accumulate_usage(sub.get("usage"))


_RECORD_HANDLERS: dict[str, Any] = {
    "assistant": _process_assistant_record,
    "user": _process_user_record,
}


def _parse_session_line(stats: SessionStats, line: str) -> None:
    """Parse and apply a single JSONL line to stats. No-op on malformed input."""
    line = line.strip()
    if not line:
        return
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return  # nosec B112 - skip corrupt/partial writes

    ts = _parse_ts(rec.get("timestamp", ""))
    if ts:
        stats.update_time_range(ts)

    handler = _RECORD_HANDLERS.get(rec.get("type"))
    if handler:
        handler(stats, rec)


def parse_session(path: Path) -> SessionStats:
    """Parse a single JSONL session file into stats."""
    stats = SessionStats(session_id=path.stem, path=path)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            _parse_session_line(stats, line)

    return stats
