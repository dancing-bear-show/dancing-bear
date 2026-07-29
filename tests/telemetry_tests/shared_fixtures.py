"""Shared test fixtures for telemetry test suite splits."""
from __future__ import annotations

import io
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from telemetry.models import (
    AgentSummary,
    AgentTokenRow,
    BlameTarget,
    SessionEvent,
    SessionSummary,
    Tip,
    ToolStats,
)

# ---------------------------------------------------------------------------
# classify shared helpers
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_seq = [0]


def _evt(
    tool_name: str | None = None,
    event_type: str = "tool_use",
    tool_input: dict | None = None,
    success: bool | None = None,
    classification: str | None = None,
    waste_reason: str | None = None,
    offset_seconds: float = 0.0,
) -> SessionEvent:
    """Build a SessionEvent with sensible defaults, auto-incrementing sequence."""
    _seq[0] += 1
    return SessionEvent(
        timestamp=_BASE_TS + timedelta(seconds=offset_seconds),
        event_type=event_type,
        sequence=_seq[0],
        session_id="test-session",
        tool_name=tool_name,
        tool_input=tool_input,
        success=success,
        classification=classification,
        waste_reason=waste_reason,
    )


def reset_seq() -> None:
    """Reset the auto-incrementing sequence counter before each test class."""
    _seq[0] = 0


EMPTY_RULES: dict = {}

BASH_RULES = {
    "avoidable": {
        "bash-as-cat": {
            "enabled": True,
            "patterns": [r"\bcat\b"],
            "exclude": [],
        },
        "bash-as-grep": {
            "enabled": True,
            "patterns": [r"\bgrep\b"],
            "exclude": [r"--include"],
        },
        "bash-as-disabled": {
            "enabled": False,
            "patterns": [r"\bls\b"],
            "exclude": [],
        },
    }
}

# ---------------------------------------------------------------------------
# cli shared helpers
# ---------------------------------------------------------------------------


def _make_session_summary(
    session_id: str = "abc123def456",
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_read_tokens: int = 200,
    cache_creation_tokens: int = 50,
    total_events: int = 5,
    total_cost: float = 0.01,
    start: str = "2026-04-16T10:00:00Z",
    end: str = "2026-04-16T10:30:00Z",
    agents: list | None = None,
    project_path: str | None = "/foo/bar",
) -> SessionSummary:
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return SessionSummary(
        session_id=session_id,
        project_path=project_path,
        start_time=start_dt,
        end_time=end_dt,
        model=model,
        total_cost=total_cost,
        cost_is_estimated=False,
        total_events=total_events,
        efficiency_score=80.0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        agents=agents or [],
    )


def _make_agent_token_row(
    agent: str = "code-writer",
    calls: int = 3,
    input_tokens: int = 5000,
    output_tokens: int = 2000,
    cache_read_tokens: int = 1000,
    cache_write_tokens: int = 500,
    models: list | None = None,
    est_cost: float = 0.05,
) -> AgentTokenRow:
    return AgentTokenRow(
        agent=agent,
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        models=models if models is not None else ["claude-sonnet-4-6"],
        est_cost=est_cost,
    )


def _make_agent_summary_cli(
    agent_id: str = "agt-001",
    agent_type: str = "code-writer",
    description: str = "Write code",
    model: str = "claude-sonnet-4-6",
    duration_ms: int = 30000,
    total_tokens: int = 3000,
    total_tool_uses: int = 5,
    cost_usd: float = 0.03,
) -> AgentSummary:
    return AgentSummary(
        agent_id=agent_id,
        agent_type=agent_type,
        description=description,
        model=model,
        duration_ms=duration_ms,
        total_tokens=total_tokens,
        total_tool_uses=total_tool_uses,
        cost_usd=cost_usd,
    )


# ---------------------------------------------------------------------------
# transcript_provider shared helpers
# ---------------------------------------------------------------------------


def _write_jsonl(dir_path: Path, name: str, records: list[dict]) -> Path:
    """Write a list of JSON records as newline-delimited JSON to dir_path/name."""
    path = dir_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    return path


def make_assistant_record(
    session_id: str = "sess-1",
    timestamp: str = "2026-04-16T10:00:00Z",
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    tool_blocks: list[dict] | None = None,
    include_usage: bool = True,
    agent_name: str | None = None,
) -> dict:
    """Build an assistant-type JSONL record."""
    content = list(tool_blocks) if tool_blocks is not None else []
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read_tokens,
        "cache_creation_input_tokens": cache_creation_tokens,
    }
    record = {
        "type": "assistant",
        "sessionId": session_id,
        "timestamp": timestamp,
        "message": {
            "model": model,
            "usage": usage if include_usage else {},
            "content": content,
        },
    }
    if agent_name is not None:
        record["agentName"] = agent_name
    return record


def make_tool_use_block(name: str, tool_id: str, tool_input: dict | None = None) -> dict:
    """Build a tool_use content block for an assistant message."""
    return {"type": "tool_use", "name": name, "id": tool_id, "input": tool_input or {}}


def make_user_record(
    session_id: str = "sess-1",
    timestamp: str = "2026-04-16T10:01:00Z",
    tool_use_result: dict | None = None,
    tool_use_id: str | None = None,
) -> dict:
    """Build a user-type JSONL record, optionally with a toolUseResult and tool_result block."""
    content = []
    if tool_use_id is not None:
        content.append({"type": "tool_result", "tool_use_id": tool_use_id})
    record = {
        "type": "user",
        "sessionId": session_id,
        "timestamp": timestamp,
        "message": {"content": content},
    }
    if tool_use_result is not None:
        record["toolUseResult"] = tool_use_result
    return record


def make_agent_tool_use_result(
    agent_id: str = "agent-1",
    agent_type: str = "general-purpose",
    total_tokens: int = 500,
    total_tool_uses: int = 3,
    duration_ms: int = 1000,
    input_tokens: int = 200,
    output_tokens: int = 80,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> dict:
    """Build a toolUseResult dict representing a completed subagent run."""
    return {
        "agentId": agent_id,
        "agentType": agent_type,
        "totalTokens": total_tokens,
        "totalToolUseCount": total_tool_uses,
        "totalDurationMs": duration_ms,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "cache_creation_input_tokens": cache_creation_tokens,
        },
    }


class TempProjectsDirMixin:
    """Provides a temp projects_dir and a bound TranscriptProvider."""

    def setUp(self) -> None:  # NOSONAR - required unittest lifecycle method name
        from telemetry.providers.transcript import TranscriptProvider
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)  # type: ignore[attr-defined]
        self.projects_dir = Path(self._td.name)
        self.provider = TranscriptProvider(projects_dir=self.projects_dir)

    def project_dir(self, name: str = "-Users-me-project") -> Path:
        d = self.projects_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d


# ---------------------------------------------------------------------------
# tui_renderers shared helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Return a stable UTC datetime for the current test run."""
    return datetime.now(timezone.utc)


def _make_summary_base(
    *,
    session_id: str = "abc123def4560000",
    project_path: str | None = "/home/user/myproject",
    model: str = "anthropic/claude-sonnet-4-6",
    total_cost: float = 0.05,
    cost_is_estimated: bool = False,
    efficiency_score: float = 80.0,
    end_time_offset_secs: int | None = 1800,
    cache_hit_rate: float | None = 0.5,
    input_tokens: int = 1000,
    output_tokens: int = 500,
) -> dict:
    """Return a kwargs dict for SessionSummary construction (identity/timing/cost fields)."""
    start = _now() - timedelta(seconds=end_time_offset_secs or 3600)
    end = (start + timedelta(seconds=end_time_offset_secs)) if end_time_offset_secs is not None else None
    return {
        "session_id": session_id,
        "project_path": project_path,
        "start_time": start,
        "end_time": end,
        "model": model,
        "total_cost": total_cost,
        "cost_is_estimated": cost_is_estimated,
        "total_events": 20,
        "efficiency_score": efficiency_score,
        "cache_hit_rate": cache_hit_rate,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _make_summary(
    *,
    productive_count: int = 10,
    neutral_count: int = 5,
    avoidable_count: int = 2,
    review_count: int = 1,
    tool_stats: dict | None = None,
    agents: list | None = None,
    tips: list | None = None,
    **base_kwargs: object,
) -> SessionSummary:
    """Build a SessionSummary with sensible defaults for renderer tests."""
    kwargs = _make_summary_base(**base_kwargs)  # type: ignore[arg-type]
    kwargs.update({
        "productive_count": productive_count,
        "neutral_count": neutral_count,
        "avoidable_count": avoidable_count,
        "review_count": review_count,
        "tool_stats": tool_stats or {},
        "agents": agents or [],
        "tips": tips or [],
    })
    return SessionSummary(**kwargs)


def _make_event(
    *,
    event_type: str = "tool_use",
    tool_name: str | None = "Bash",
    tool_input: dict | None = None,
    classification: str | None = "productive",
    waste_reason: str | None = None,
    cost_usd: float | None = None,
    cost_is_estimated: bool = False,
    blame_target: BlameTarget | None = None,
    model: str | None = "claude-sonnet-4-6",
) -> SessionEvent:
    return SessionEvent(
        timestamp=_now(),
        event_type=event_type,
        sequence=1,
        session_id="abc123def4560000",
        tool_name=tool_name,
        tool_input=tool_input,
        classification=classification,
        waste_reason=waste_reason,
        cost_usd=cost_usd,
        cost_is_estimated=cost_is_estimated,
        blame_target=blame_target,
        model=model,
    )


def _make_blame() -> BlameTarget:
    return BlameTarget(
        level="skill",
        name="s2s:onboarding",
        fix_hint="Reduce repeated reads",
    )


def _make_tip(*, severity: str = "avoidable") -> Tip:
    return Tip(
        severity=severity,
        waste_reason="redundant-read",
        count=3,
        cost_impact=0.012,
        blame_target=_make_blame(),
        message="Redundant reads detected",
        fix_hint="Cache file contents between calls",
    )


def _make_tool_stats(tool_name: str = "Bash") -> ToolStats:
    return ToolStats(
        tool_name=tool_name,
        count=5,
        cost=0.025,
        avoidable_count=2,
        review_count=1,
    )


def _make_agent_summary_tui() -> AgentSummary:
    return AgentSummary(
        agent_id="agent-001",
        agent_type="code-writer",
        description="Fix authentication bug",
        model="anthropic/claude-sonnet-4-6",
        duration_ms=5000,
        total_tokens=2000,
        total_tool_uses=8,
        cost_usd=0.03,
        cost_is_estimated=False,
    )


def _render_panel_text(panel: Panel, width: int = 100) -> str:
    """Render a Rich Panel to a plain string via StringIO."""
    buf = io.StringIO()
    console = Console(file=buf, width=width, highlight=False, markup=True)
    console.print(panel)
    return buf.getvalue()
