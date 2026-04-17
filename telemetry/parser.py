"""Parse Claude Code JSONL session transcripts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional


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
                if stats.start_time is None or ts < stats.start_time:
                    stats.start_time = ts
                if stats.end_time is None or ts > stats.end_time:
                    stats.end_time = ts

            rec_type = rec.get("type")

            if rec_type == "assistant":
                stats.events += 1
                msg = rec.get("message", {})

                # Model
                model = msg.get("model", "")
                if model and not stats.model:
                    stats.model = model

                # Token usage
                usage = msg.get("usage", {})
                stats.input_tokens += usage.get("input_tokens", 0)
                stats.output_tokens += usage.get("output_tokens", 0)
                stats.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
                stats.cache_create_tokens += usage.get("cache_creation_input_tokens", 0)

                # Tool calls
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "unknown")
                        stats.tool_counts[name] = stats.tool_counts.get(name, 0) + 1

            elif rec_type == "user":
                # Subagent token usage — attribute to parent model
                sub = rec.get("toolUseResult")
                if sub and isinstance(sub, dict):
                    sub_usage = sub.get("usage", {})
                    stats.input_tokens += sub_usage.get("input_tokens", 0)
                    stats.output_tokens += sub_usage.get("output_tokens", 0)
                    stats.cache_read_tokens += sub_usage.get("cache_read_input_tokens", 0)
                    stats.cache_create_tokens += sub_usage.get("cache_creation_input_tokens", 0)

    return stats
