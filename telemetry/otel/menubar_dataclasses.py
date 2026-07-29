"""Frozen dataclasses and zero-constructors extracted from menubar_provider.py."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class OtelUsage:
    """Token and cost summary for the selected window (default: 24h).

    Field names use the ``_24h`` suffix for compatibility; the actual
    aggregation period is whatever window was passed to
    :meth:`OtelMenubarProvider.get_display_data`. ``cost_7d`` is always
    a 7-day reference cost regardless of the selected window.
    """

    cost_24h: float
    cost_7d: float
    input_tokens_24h: int
    output_tokens_24h: int
    cache_read_tokens_24h: int
    cache_creation_tokens_24h: int
    total_tokens_24h: int
    active_hours_24h: float
    model_cost_breakdown: list[tuple[str, float]]  # top 3 by cost


@dataclass(frozen=True)
class OtelModels:
    """Per-model cost and token breakdown for the selected window (default: 24h)."""

    model_rows: list[tuple[str, float, int]]  # (model, cost_24h, total_tokens_24h) top 4


@dataclass(frozen=True)
class MetaStats:
    """Derived efficiency ratios."""

    cost_per_active_hour: float  # 0.0 if active_hours == 0
    cost_per_loc_added: float    # 0.0 if lines_added == 0
    cost_per_commit: float       # 0.0 if commits == 0
    cache_hit_rate_pct: float    # 0.0 if no cache tokens
    total_tokens_24h: int


@dataclass(frozen=True)
class HookHealth:
    """Hook execution health for the selected window (default: 24h)."""

    hooks_fired_today: int
    avg_hook_latency_ms: float
    blocking_count: int
    error_count: int
    hook_names: list[str]  # top 3 by count


@dataclass(frozen=True)
class ToolActivity:
    """Tool call statistics for the selected window (default: 24h)."""

    tool_calls_today: int
    accept_rate_pct: float
    top_tools: list[tuple[str, int]]  # top 4
    tool_error_count: int
    bash_error_rate_pct: float
    avg_input_bytes: float
    avg_output_bytes: float


@dataclass(frozen=True)
class CodeImpact:
    """Code change and compaction stats for the selected window (default: 24h)."""

    lines_added_today: int
    lines_removed_today: int
    top_languages: list[tuple[str, int]]  # top 3 by code_edit_tool.decision count
    commits_today: int
    compaction_count: int
    tokens_saved_by_compaction: int


@dataclass(frozen=True)
class Skills:
    """Skill invocation stats for the selected window (default: 24h)."""

    top_skills: list[tuple[str, int]]  # top 4
    skills_invoked_today: int


@dataclass(frozen=True)
class SessionPatterns:
    """Session-level usage patterns for the selected window (default: 24h)."""

    prompts_today: int
    model_mix: list[tuple[str, int]]  # top 3
    agent_call_pct: float
    effort_mix: dict[str, int]


@dataclass(frozen=True)
class OtelDisplayData:
    """All display data for the menubar, produced by OtelMenubarProvider."""

    available: bool
    collected_at: datetime
    otel_usage: OtelUsage
    otel_models: OtelModels
    meta_stats: MetaStats
    hook_health: HookHealth
    tool_activity: ToolActivity
    code_impact: CodeImpact
    skills: Skills
    session_patterns: SessionPatterns


def _zero_usage() -> OtelUsage:
    return OtelUsage(
        cost_24h=0.0, cost_7d=0.0,
        input_tokens_24h=0, output_tokens_24h=0,
        cache_read_tokens_24h=0, cache_creation_tokens_24h=0,
        total_tokens_24h=0, active_hours_24h=0.0,
        model_cost_breakdown=[],
    )


def _zero_models() -> OtelModels:
    return OtelModels(model_rows=[])


def _zero_meta(total_tokens: int = 0) -> MetaStats:
    return MetaStats(
        cost_per_active_hour=0.0,
        cost_per_loc_added=0.0,
        cost_per_commit=0.0,
        cache_hit_rate_pct=0.0,
        total_tokens_24h=total_tokens,
    )


def _zero_hook_health() -> HookHealth:
    return HookHealth(hooks_fired_today=0, avg_hook_latency_ms=0.0, blocking_count=0, error_count=0, hook_names=[])


def _zero_tool_activity() -> ToolActivity:
    return ToolActivity(tool_calls_today=0, accept_rate_pct=0.0, top_tools=[], tool_error_count=0, bash_error_rate_pct=0.0, avg_input_bytes=0.0, avg_output_bytes=0.0)


def _zero_code_impact() -> CodeImpact:
    return CodeImpact(lines_added_today=0, lines_removed_today=0, top_languages=[], commits_today=0, compaction_count=0, tokens_saved_by_compaction=0)


def _zero_skills() -> Skills:
    return Skills(top_skills=[], skills_invoked_today=0)


def _zero_session_patterns() -> SessionPatterns:
    return SessionPatterns(prompts_today=0, model_mix=[], agent_call_pct=0.0, effort_mix={})


def _unavailable() -> OtelDisplayData:
    """Return an OtelDisplayData indicating the collector is unavailable."""
    return OtelDisplayData(
        available=False,
        collected_at=datetime.now(tz=timezone.utc),
        otel_usage=_zero_usage(),
        otel_models=_zero_models(),
        meta_stats=_zero_meta(),
        hook_health=_zero_hook_health(),
        tool_activity=_zero_tool_activity(),
        code_impact=_zero_code_impact(),
        skills=_zero_skills(),
        session_patterns=_zero_session_patterns(),
    )
