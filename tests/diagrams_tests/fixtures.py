"""Test fixtures for diagrams domain tests.

Provides a shared make_session() factory used by all diagrams test modules.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from telemetry.parser import SessionStats


def make_session(
    session_id: str = "abc123",
    model: str = "claude-sonnet-4-6",
    input_tok: int = 1000,
    output_tok: int = 500,
    cache_read: int = 0,
    cache_create: int = 0,
    start: str = "2026-04-16T10:00:00Z",
    end: str = "2026-04-16T10:30:00Z",
) -> SessionStats:
    """Return a fresh SessionStats instance populated with the given values.

    All callers receive their own object — no shared mutable state.
    """
    s = SessionStats(session_id=session_id, path=Path(f"/fake/{session_id}.jsonl"))
    s.model = model
    s.input_tokens = input_tok
    s.output_tokens = output_tok
    s.cache_read_tokens = cache_read
    s.cache_create_tokens = cache_create
    s.events = 1
    s.start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
    s.end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return s
