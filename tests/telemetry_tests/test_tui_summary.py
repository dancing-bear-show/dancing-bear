"""Tests for telemetry.tui._summary.compute_summary."""

import unittest
from dataclasses import dataclass, field
from datetime import datetime, timezone

from telemetry.models import AgentSummary, SessionEvent, SessionSummary
from telemetry.tui._summary import SummaryConfig, compute_summary


@dataclass
class EventSpec:
    """Convenience spec for building a SessionEvent in tests."""

    event_type: str
    sequence: int = 0
    tool_name: str | None = None
    classification: str | None = None
    cost_usd: float | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    timestamp: datetime = field(
        default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    )


def make_event(spec: EventSpec, session_id: str = "sess-1") -> SessionEvent:
    """Build a SessionEvent from an EventSpec."""
    return SessionEvent(
        timestamp=spec.timestamp,
        event_type=spec.event_type,
        sequence=spec.sequence,
        session_id=session_id,
        tool_name=spec.tool_name,
        classification=spec.classification,
        cost_usd=spec.cost_usd,
        model=spec.model,
        input_tokens=spec.input_tokens,
        output_tokens=spec.output_tokens,
        cache_read_tokens=spec.cache_read_tokens,
        cache_creation_tokens=spec.cache_creation_tokens,
    )


def make_tool_event(
    tool_name: str | None,
    classification: str | None = None,
    cost_usd: float | None = None,
    sequence: int = 0,
    timestamp: datetime | None = None,
) -> SessionEvent:
    """Build a tool_use SessionEvent."""
    spec = EventSpec(
        event_type="tool_use",
        sequence=sequence,
        tool_name=tool_name,
        classification=classification,
        cost_usd=cost_usd,
    )
    if timestamp is not None:
        spec.timestamp = timestamp
    return make_event(spec)


def make_api_event(
    model: str = "claude-sonnet-4-6",
    cost_usd: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_creation_tokens: int | None = None,
    sequence: int = 0,
    timestamp: datetime | None = None,
) -> SessionEvent:
    """Build an api_request SessionEvent."""
    spec = EventSpec(
        event_type="api_request",
        sequence=sequence,
        model=model,
        cost_usd=cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )
    if timestamp is not None:
        spec.timestamp = timestamp
    return make_event(spec)


def make_agent_summary(agent_id: str = "agent-1") -> AgentSummary:
    """Build a minimal AgentSummary."""
    return AgentSummary(
        agent_id=agent_id,
        agent_type="general-purpose",
        description="do a thing",
        model="claude-sonnet-4-6",
        duration_ms=1000,
        total_tokens=500,
        total_tool_uses=3,
        cost_usd=0.01,
    )


_CFG = SummaryConfig("s", None, cost_is_estimated=False)


class TestComputeSummaryEmpty(unittest.TestCase):
    def test_empty_events_defaults(self):
        summary = compute_summary(
            events=[],
            agents=[],
            config=SummaryConfig("sess-empty", "/some/project", cost_is_estimated=False),
        )
        self.assertIsInstance(summary, SessionSummary)
        self.assertEqual(summary.session_id, "sess-empty")
        self.assertEqual(summary.project_path, "/some/project")
        self.assertEqual(summary.total_events, 0)
        self.assertEqual(summary.productive_count, 0)
        self.assertEqual(summary.neutral_count, 0)
        self.assertEqual(summary.avoidable_count, 0)
        self.assertEqual(summary.review_count, 0)
        self.assertEqual(summary.efficiency_score, 100.0)
        self.assertEqual(summary.total_cost, 0.0)
        self.assertEqual(summary.tool_stats, {})
        self.assertEqual(summary.agents, [])
        self.assertIsNone(summary.cache_hit_rate)

    def test_empty_events_end_time_none(self):
        summary = compute_summary(
            events=[],
            agents=[],
            config=SummaryConfig("sess-empty", None, cost_is_estimated=False),
        )
        self.assertIsNone(summary.end_time)
        self.assertIsInstance(summary.start_time, datetime)

    def test_empty_project_path_is_none(self):
        summary = compute_summary(
            events=[], agents=[],
            config=SummaryConfig("s", None, cost_is_estimated=True),
        )
        self.assertIsNone(summary.project_path)
        self.assertTrue(summary.cost_is_estimated)


class TestComputeSummaryClassifications(unittest.TestCase):
    def test_mixed_classifications_counted(self):
        events = [
            make_tool_event("Read", classification="productive", sequence=1),
            make_tool_event("Read", classification="productive", sequence=2),
            make_tool_event("Bash", classification="neutral", sequence=3),
            make_tool_event("Bash", classification="avoidable", sequence=4),
            make_tool_event("Grep", classification="review", sequence=5),
        ]
        summary = compute_summary(
            events=events,
            agents=[],
            config=SummaryConfig("sess-1", "/proj", cost_is_estimated=False),
        )
        self.assertEqual(summary.productive_count, 2)
        self.assertEqual(summary.neutral_count, 1)
        self.assertEqual(summary.avoidable_count, 1)
        self.assertEqual(summary.review_count, 1)
        self.assertEqual(summary.total_events, 5)

    def test_efficiency_score_all_productive(self):
        events = [
            make_tool_event("Read", classification="productive", sequence=1),
            make_tool_event("Read", classification="productive", sequence=2),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertEqual(summary.efficiency_score, 100.0)

    def test_efficiency_score_mixed(self):
        # 1 productive (1.0) + 1 neutral (0.5) + 1 avoidable (0) + 1 review (0) = 1.5 / 4 * 100
        events = [
            make_tool_event("Read", classification="productive", sequence=1),
            make_tool_event("Bash", classification="neutral", sequence=2),
            make_tool_event("Bash", classification="avoidable", sequence=3),
            make_tool_event("Grep", classification="review", sequence=4),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertAlmostEqual(summary.efficiency_score, 37.5)

    def test_unclassified_events_do_not_count(self):
        events = [make_tool_event("Read", classification=None, sequence=1)]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertEqual(summary.productive_count, 0)
        self.assertEqual(summary.neutral_count, 0)
        self.assertEqual(summary.avoidable_count, 0)
        self.assertEqual(summary.review_count, 0)
        self.assertEqual(summary.total_events, 1)


class TestComputeSummaryToolStats(unittest.TestCase):
    def test_multiple_events_same_tool_accumulate(self):
        events = [
            make_tool_event("Read", classification="productive", cost_usd=0.1, sequence=1),
            make_tool_event("Read", classification="avoidable", cost_usd=0.2, sequence=2),
            make_tool_event("Read", classification="review", cost_usd=0.3, sequence=3),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        stats = summary.tool_stats["Read"]
        self.assertEqual(stats.tool_name, "Read")
        self.assertEqual(stats.count, 3)
        self.assertAlmostEqual(stats.cost, 0.6)
        self.assertEqual(stats.avoidable_count, 1)
        self.assertEqual(stats.review_count, 1)

    def test_multiple_tools_separate_stats(self):
        events = [
            make_tool_event("Read", classification="productive", sequence=1),
            make_tool_event("Bash", classification="productive", sequence=2),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertIn("Read", summary.tool_stats)
        self.assertIn("Bash", summary.tool_stats)
        self.assertEqual(summary.tool_stats["Read"].count, 1)
        self.assertEqual(summary.tool_stats["Bash"].count, 1)

    def test_missing_tool_name_grouped_as_unknown(self):
        events = [make_tool_event(tool_name=None, classification="neutral", sequence=1)]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertIn("unknown", summary.tool_stats)
        self.assertEqual(summary.tool_stats["unknown"].count, 1)

    def test_cost_none_not_added(self):
        events = [make_tool_event("Read", classification="productive", cost_usd=None, sequence=1)]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertEqual(summary.tool_stats["Read"].cost, 0.0)

    def test_api_events_excluded_from_tool_stats(self):
        events = [
            make_api_event(sequence=1),
            make_tool_event("Read", classification="productive", sequence=2),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertEqual(len(summary.tool_stats), 1)
        self.assertIn("Read", summary.tool_stats)


class TestComputeSummaryCacheHitRate(unittest.TestCase):
    def test_cache_hit_rate_with_cache_tokens(self):
        events = [
            make_api_event(input_tokens=100, cache_read_tokens=300, sequence=1),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        # hit rate is cache_read as a fraction of (input + cache_read): 300 of 400 = 0.75
        self.assertAlmostEqual(summary.cache_hit_rate, 0.75)
        self.assertEqual(summary.cache_read_tokens, 300)
        self.assertEqual(summary.input_tokens, 100)

    def test_cache_hit_rate_without_cache_tokens(self):
        events = [
            make_api_event(input_tokens=100, cache_read_tokens=0, sequence=1),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertEqual(summary.cache_hit_rate, 0.0)

    def test_cache_hit_rate_none_when_no_api_events(self):
        events = [make_tool_event("Read", classification="productive", sequence=1)]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertIsNone(summary.cache_hit_rate)

    def test_cache_hit_rate_none_when_totals_zero(self):
        events = [make_api_event(input_tokens=0, cache_read_tokens=0, sequence=1)]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertIsNone(summary.cache_hit_rate)

    def test_cache_creation_tokens_summed_separately(self):
        events = [
            make_api_event(cache_creation_tokens=50, sequence=1),
            make_api_event(cache_creation_tokens=25, sequence=2),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertEqual(summary.cache_creation_tokens, 75)


class TestComputeSummaryEndTime(unittest.TestCase):
    def test_end_time_present_when_events_exist(self):
        t1 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 10, 30, tzinfo=timezone.utc)
        events = [
            make_tool_event("Read", classification="productive", sequence=1, timestamp=t1),
            make_tool_event("Bash", classification="productive", sequence=2, timestamp=t2),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertEqual(summary.start_time, t1)
        self.assertEqual(summary.end_time, t2)

    def test_end_time_absent_when_no_events(self):
        summary = compute_summary(events=[], agents=[], config=_CFG)
        self.assertIsNone(summary.end_time)


class TestComputeSummaryModelAndCost(unittest.TestCase):
    def test_latest_model_from_last_api_event(self):
        events = [
            make_api_event(model="claude-haiku-4-5", sequence=1),
            make_api_event(model="claude-opus-4-6", sequence=2),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertEqual(summary.model, "claude-opus-4-6")

    def test_model_empty_when_no_api_events_have_model(self):
        events = [make_api_event(model="", sequence=1)]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertEqual(summary.model, "")

    def test_total_cost_sums_api_events(self):
        events = [
            make_api_event(cost_usd=0.5, sequence=1),
            make_api_event(cost_usd=1.5, sequence=2),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertAlmostEqual(summary.total_cost, 2.0)

    def test_total_cost_override_takes_precedence(self):
        events = [make_api_event(cost_usd=0.5, sequence=1)]
        summary = compute_summary(
            events=events,
            agents=[],
            config=SummaryConfig("s", None, cost_is_estimated=False, total_cost_override=99.0),
        )
        self.assertEqual(summary.total_cost, 99.0)

    def test_avoidable_cost_only_counts_avoidable_tool_events(self):
        events = [
            make_tool_event("Read", classification="avoidable", cost_usd=0.3, sequence=1),
            make_tool_event("Bash", classification="productive", cost_usd=0.7, sequence=2),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertAlmostEqual(summary.avoidable_cost, 0.3)

    def test_productive_cost_sums_api_event_costs(self):
        events = [
            make_api_event(cost_usd=0.4, sequence=1),
            make_api_event(cost_usd=0.6, sequence=2),
        ]
        summary = compute_summary(events=events, agents=[], config=_CFG)
        self.assertAlmostEqual(summary.productive_cost, 1.0)


class TestComputeSummaryAgents(unittest.TestCase):
    def test_agents_passed_through(self):
        agents = [make_agent_summary("a1"), make_agent_summary("a2")]
        summary = compute_summary(events=[], agents=agents, config=_CFG)
        self.assertEqual(len(summary.agents), 2)
        self.assertEqual(summary.agents[0].agent_id, "a1")
        self.assertEqual(summary.agents[1].agent_id, "a2")


if __name__ == "__main__":
    unittest.main()
