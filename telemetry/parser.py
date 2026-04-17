"""Parse Claude Code JSONL session transcripts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


PROJECTS_DIR = Path.home() / ".claude" / "projects"


@dataclass
class SessionStats:
    session_id: str
    path: Path
    model: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    events: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    @property
    def total_tokens(self) -> int:
        return (self.input_tokens + self.output_tokens +
                self.cache_read_tokens + self.cache_create_tokens)

    def accumulate_usage(self, usage: Dict[str, Any]) -> None:
        """Add token counts from a usage dict."""
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
        self.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
        self.cache_create_tokens += usage.get("cache_creation_input_tokens", 0)

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
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    for proj in PROJECTS_DIR.iterdir():
        if not proj.is_dir():
            continue
        for jl in proj.glob("*.jsonl"):
            mtime = datetime.fromtimestamp(jl.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                yield jl


def _parse_ts(raw: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp (handles trailing Z)."""
    try:
        raw = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except (ValueError, AttributeError):
        return None


def _process_assistant_record(stats: SessionStats, msg: Dict[str, Any]) -> None:
    """Extract model, usage, and tool calls from an assistant message."""
    stats.events += 1

    model = msg.get("model", "")
    if model and not stats.model:
        stats.model = model

    stats.accumulate_usage(msg.get("usage", {}))

    for block in msg.get("content", []):
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name", "unknown")
            stats.tool_counts[name] = stats.tool_counts.get(name, 0) + 1


def _process_user_record(stats: SessionStats, rec: Dict[str, Any]) -> None:
    """Extract subagent token usage from a user message."""
    sub = rec.get("toolUseResult")
    if sub and isinstance(sub, dict):
        stats.accumulate_usage(sub.get("usage", {}))


def parse_session(path: Path) -> SessionStats:
    """Parse a single JSONL session file into stats."""
    stats = SessionStats(session_id=path.stem, path=path)

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # nosec B112 - skip corrupt/partial writes

            ts = _parse_ts(rec.get("timestamp", ""))
            if ts:
                stats.update_time_range(ts)

            rec_type = rec.get("type")
            if rec_type == "assistant":
                _process_assistant_record(stats, rec.get("message", {}))
            elif rec_type == "user":
                _process_user_record(stats, rec)

    return stats
