from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BlameTarget:
    level: str  # "session" | "skill" | "agent"
    name: str  # "session" | "s2s:s2s-onboarding" | "Scan remaining grpc clients"
    fix_hint: str


@dataclass
class SessionEvent:
    timestamp: datetime
    event_type: str  # "tool_use" | "api_request" | "user_prompt"
    sequence: int
    session_id: str
    prompt_id: str = ""

    # Tool fields
    tool_name: str | None = None
    tool_input: dict[str, object] | None = None
    success: bool | None = None
    duration_ms: int | None = None
    result_size_bytes: int | None = None

    # Cost fields
    model: str | None = None
    cost_usd: float | None = None
    cost_is_estimated: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None

    # Classification (populated by ClassifyEngine and BlameEngine)
    classification: str | None = None
    waste_reason: str | None = None
    blame_target: BlameTarget | None = None


@dataclass
class ToolStats:
    tool_name: str
    count: int = 0
    cost: float = 0.0
    avoidable_count: int = 0
    review_count: int = 0
    avg_duration_ms: float | None = None


@dataclass
class Tip:
    severity: str  # "avoidable" | "review"
    waste_reason: str
    count: int
    cost_impact: float
    blame_target: BlameTarget
    message: str
    fix_hint: str


@dataclass
class AgentSummary:
    agent_id: str
    agent_type: str
    description: str
    model: str
    duration_ms: int
    total_tokens: int
    total_tool_uses: int
    cost_usd: float
    cost_is_estimated: bool = False
    productive_count: int = 0
    neutral_count: int = 0
    avoidable_count: int = 0
    review_count: int = 0


@dataclass
class SessionSummary:
    session_id: str
    project_path: str | None
    start_time: datetime
    end_time: datetime | None
    model: str
    total_cost: float
    cost_is_estimated: bool
    total_events: int
    efficiency_score: float

    productive_count: int = 0
    neutral_count: int = 0
    avoidable_count: int = 0
    review_count: int = 0
    productive_cost: float = 0.0
    avoidable_cost: float = 0.0

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_hit_rate: float | None = None

    tool_stats: dict[str, ToolStats] = field(default_factory=dict)
    agents: list[AgentSummary] = field(default_factory=list)
    tips: list[Tip] = field(default_factory=list)


@dataclass
class AgentTokenRow:
    """Aggregated token usage and cost for a named agent across all sessions."""

    agent: str
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    models: list[str]  # sorted unique model names
    est_cost: float
