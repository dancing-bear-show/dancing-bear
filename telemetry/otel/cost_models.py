"""Dataclasses for telemetry cost analysis.

This module provides type-safe data structures for session and model cost
metrics derived from OpenTelemetry data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class SessionPerf:
    """Performance and error metrics for a single session.

    Attributes:
        error_count: Number of API errors (claude_code.api_error events).
        error_rate: error_count / api_calls (0.0-1.0).
        error_status_codes: Counter of HTTP status codes from errors.
        tool_calls: Total tool_result events.
        tool_failures: Count of tool_result events where success=false.
        tool_failure_rate: tool_failures / tool_calls (0.0-1.0).
        avg_api_latency_ms: Mean duration_ms across api_request events.
        p95_api_latency_ms: 95th percentile API latency.
        prompt_count: Number of user_prompt events (human turns).
        autonomy_ratio: api_calls / prompt_count (how many API calls per turn).
        model_mix: Dict mapping model name to call count.
        terminal_type: Terminal type (e.g., "tmux", "iTerm.app").
        total_api_wait_ms: Sum of all api_request duration_ms.
        tool_usage: Dict mapping tool_name to call count.
    """

    error_count: int = 0
    error_rate: float = 0.0
    error_status_codes: dict[str, int] = field(default_factory=dict)
    tool_calls: int = 0
    tool_failures: int = 0
    tool_failure_rate: float = 0.0
    avg_api_latency_ms: float = 0.0
    p95_api_latency_ms: float = 0.0
    prompt_count: int = 0
    autonomy_ratio: float = 0.0
    model_mix: dict[str, int] = field(default_factory=dict)
    terminal_type: str = ""
    total_api_wait_ms: float = 0.0
    tool_usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionCost:
    """Cost metrics for a single session."""

    session_id: str
    api_calls: int
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost: float
    efficiency_ratio: float
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    perf: SessionPerf | None = None

    @property
    def billable_tokens(self) -> int:
        """Total tokens billed (excludes cache_read_tokens)."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
        )

    @property
    def duration_minutes(self) -> float | None:
        """Session duration in minutes, or None if timestamps unavailable."""
        if self.first_seen and self.last_seen:
            return (self.last_seen - self.first_seen).total_seconds() / 60
        return None


@dataclass(frozen=True)
class ModelCost:
    """Cost metrics for a single model."""

    model_name: str
    api_calls: int
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost: float
    efficiency_ratio: float

    @property
    def billable_tokens(self) -> int:
        """Total tokens billed (excludes cache_read_tokens)."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
        )


@dataclass(frozen=True)
class CostMetrics:
    """Comprehensive cost analysis for all telemetry data."""

    total_api_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int
    total_cost: float
    total_cache_savings: float
    efficiency_ratio: float
    by_session: list[SessionCost] = field(default_factory=list)
    by_model: list[ModelCost] = field(default_factory=list)

    @property
    def total_billable_tokens(self) -> int:
        """Total tokens billed (excludes cache_read_tokens)."""
        return (
            self.total_input_tokens
            + self.total_output_tokens
            + self.total_cache_creation_tokens
        )

    @property
    def cache_savings_percent(self) -> float:
        """Percentage of tokens that were cache reads."""
        total = self.total_billable_tokens + self.total_cache_read_tokens
        if total == 0:
            return 0.0
        return (self.total_cache_read_tokens / total) * 100.0


@dataclass(frozen=True)
class DailyCost:
    """Cost metrics for a single day."""

    date: str  # YYYY-MM-DD
    api_calls: int
    cost: float
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int


@dataclass(frozen=True)
class ToolErrorSummary:
    """Error analysis for a single tool."""

    tool_name: str
    total_calls: int
    failures: int
    failure_rate: float
    avg_duration_ms: float
    sessions_affected: int


@dataclass(frozen=True)
class ModelPerformance:
    """Performance and cost metrics for a model."""

    model_name: str
    api_calls: int
    error_count: int
    error_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    cost: float
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class PromptMetrics:
    """Per-prompt aggregated metrics within a session."""

    prompt_id: str
    session_id: str
    timestamp: str | None  # ISO format
    prompt_length: int
    api_calls: int
    input_tokens: int
    output_tokens: int
    cost: float
    tool_calls: int
    tool_failures: int
    duration_ms: float


@dataclass(frozen=True)
class SessionHealthScore:
    """Composite health metric for a session."""

    session_id: str
    score: float  # 0.0-1.0
    error_penalty: float
    tool_failure_penalty: float
    latency_penalty: float
    grade: str  # A/B/C/D/F


@dataclass(frozen=True)
class SessionComparison:
    """Side-by-side comparison of two sessions."""

    session_a: SessionCost
    session_b: SessionCost
    cost_delta: float
    token_delta: int
    duration_delta: timedelta | None
    error_delta: int


@dataclass(frozen=True)
class AnomalyFlag:
    """Anomaly detection result for a session metric."""

    session_id: str
    metric: str
    value: float
    mean: float
    std_dev: float
    z_score: float


@dataclass(frozen=True)
class SessionCluster:
    """Cluster assignment for a session."""

    session_id: str
    cluster_id: int
    cluster_label: str
    features: dict[str, float] = field(default_factory=dict)
