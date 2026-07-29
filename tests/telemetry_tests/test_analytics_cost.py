"""Tests for telemetry/otel/analytics/cost.py — cost analysis engine."""

import unittest
from collections import defaultdict
from datetime import datetime, timezone
from unittest import mock

from telemetry.otel.analytics.cost import (
    MODEL_PRICING,
    _accumulate_cost_datapoints,
    _aggregate_requests_by_key,
    _aggregate_requests_by_session_and_model,
    _build_model_costs,
    _build_session_costs,
    _build_session_timestamps,
    _calculate_totals,
    get_all_costs,
    get_daily_costs,
    get_model_performance,
    get_model_pricing,
)
from telemetry.otel.cost_models import SessionPerf
from telemetry.otel.models import (
    MetricDataPoint,
    OTLPAttribute,
    OTLPEventsRecord,
    OTLPEvent,
    OTLPResource,
    OTLPValue,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _nano(dt: datetime) -> int:
    """Convert a UTC datetime to Unix nanoseconds."""
    return int(dt.timestamp() * 1_000_000_000)


def _attr(key: str, value: str) -> OTLPAttribute:
    return OTLPAttribute(key=key, value=OTLPValue(string_value=value))


def _resource() -> OTLPResource:
    return OTLPResource(service_name="claude-code", service_version="1.0")


def _make_event(
    body: str,
    session_id: str,
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    duration_ms: float = 1000.0,
    dt: datetime | None = None,
) -> OTLPEvent:
    """Build a real OTLPEvent for api_request-style events."""
    if dt is None:
        dt = _utc(2026, 7, 1)
    ts_nano = _nano(dt)
    attrs = [
        _attr("session.id", session_id),
        _attr("model", model),
        _attr("input_tokens", str(input_tokens)),
        _attr("output_tokens", str(output_tokens)),
        _attr("cache_creation_tokens", str(cache_creation_tokens)),
        _attr("cache_read_tokens", str(cache_read_tokens)),
        _attr("duration_ms", str(duration_ms)),
    ]
    return OTLPEvent(
        time_unix_nano=ts_nano,
        observed_time_unix_nano=ts_nano,
        body=body,
        attributes=attrs,
    )


def _make_api_request_event(
    session_id: str = "sess-1",
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    duration_ms: float = 1000.0,
    dt: datetime | None = None,
) -> OTLPEvent:
    return _make_event(
        body="api_request",
        session_id=session_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        duration_ms=duration_ms,
        dt=dt,
    )


def _make_error_event(
    session_id: str = "sess-1",
    status_code: str = "429",
    dt: datetime | None = None,
) -> OTLPEvent:
    if dt is None:
        dt = _utc(2026, 7, 1)
    ts_nano = _nano(dt)
    attrs = [
        _attr("session.id", session_id),
        _attr("status_code", status_code),
    ]
    return OTLPEvent(
        time_unix_nano=ts_nano,
        observed_time_unix_nano=ts_nano,
        body="api_error",
        attributes=attrs,
    )


def _make_tool_event(
    session_id: str = "sess-1",
    tool_name: str = "Read",
    success: str = "true",
    dt: datetime | None = None,
) -> OTLPEvent:
    if dt is None:
        dt = _utc(2026, 7, 1)
    ts_nano = _nano(dt)
    attrs = [
        _attr("session.id", session_id),
        _attr("tool_name", tool_name),
        _attr("success", success),
    ]
    return OTLPEvent(
        time_unix_nano=ts_nano,
        observed_time_unix_nano=ts_nano,
        body="tool_result",
        attributes=attrs,
    )


def _make_prompt_event(
    session_id: str = "sess-1",
    dt: datetime | None = None,
) -> OTLPEvent:
    if dt is None:
        dt = _utc(2026, 7, 1)
    ts_nano = _nano(dt)
    attrs = [_attr("session.id", session_id)]
    return OTLPEvent(
        time_unix_nano=ts_nano,
        observed_time_unix_nano=ts_nano,
        body="user_prompt",
        attributes=attrs,
    )


def _make_events_record(events: list[OTLPEvent]) -> OTLPEventsRecord:
    return OTLPEventsRecord(
        resource=_resource(),
        scope_name="claude-code",
        log_records=events,
    )


def _make_api_request_dict(
    session_id: str = "sess-1",
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    timestamp: datetime | None = None,
    duration_ms: float | None = None,
) -> dict:
    """Build a raw api_request dict (as produced by _extract_all_events)."""
    return {
        "session_id": session_id,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
        "timestamp": timestamp or _utc(2026, 7, 1),
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# get_model_pricing
# ---------------------------------------------------------------------------

class TestGetModelPricing(unittest.TestCase):

    def test_exact_match_sonnet_4_6(self):
        result = get_model_pricing("claude-sonnet-4-6")
        self.assertEqual(result, (3.0, 15.0))

    def test_exact_match_opus_4_5(self):
        result = get_model_pricing("claude-opus-4-5")
        self.assertEqual(result, (5.0, 25.0))

    def test_exact_match_haiku_4_5(self):
        result = get_model_pricing("claude-haiku-4-5")
        self.assertEqual(result, (1.0, 5.0))

    def test_exact_match_fable(self):
        result = get_model_pricing("claude-fable-5")
        self.assertEqual(result, (10.0, 50.0))

    def test_exact_match_mythos(self):
        result = get_model_pricing("claude-mythos-5")
        self.assertEqual(result, (10.0, 50.0))

    def test_sonnet_5_substring_takes_priority_over_generic_sonnet(self):
        # A hypothetical unlisted sonnet-5 variant should use introductory pricing
        result = get_model_pricing("us.anthropic.claude-sonnet-5-20260901")
        self.assertEqual(result, MODEL_PRICING["claude-sonnet-5"])
        # Confirm it's NOT the generic sonnet rate
        self.assertNotEqual(result, MODEL_PRICING["claude-sonnet"])

    def test_opus_1m_combo(self):
        result = get_model_pricing("claude-opus-4-6-1m-variant")
        self.assertEqual(result, (5.0, 25.0))

    def test_sonnet_1m_combo(self):
        result = get_model_pricing("some-sonnet-1m-extended-context")
        self.assertEqual(result, (3.0, 15.0))

    def test_mythos_substring(self):
        result = get_model_pricing("anthropic.claude-mythos-5-variant")
        self.assertEqual(result, MODEL_PRICING["claude-mythos-5"])

    def test_fable_substring(self):
        result = get_model_pricing("anthropic.claude-fable-5-beta")
        self.assertEqual(result, MODEL_PRICING["claude-fable-5"])

    def test_generic_opus_substring(self):
        # An unlisted opus variant without "1m" falls back to generic opus pricing
        result = get_model_pricing("claude-opus-99-unlisted")
        self.assertEqual(result, MODEL_PRICING["claude-opus"])

    def test_generic_sonnet_substring(self):
        result = get_model_pricing("claude-sonnet-99-unlisted")
        self.assertEqual(result, MODEL_PRICING["claude-sonnet"])

    def test_generic_haiku_substring(self):
        result = get_model_pricing("claude-haiku-99-unlisted")
        self.assertEqual(result, MODEL_PRICING["claude-haiku"])

    def test_total_fallback_to_default(self):
        result = get_model_pricing("completely-unrecognized-model-xyz")
        from telemetry.otel.analytics.cost import DEFAULT_MODEL
        self.assertEqual(result, MODEL_PRICING[DEFAULT_MODEL])

    def test_case_insensitive_matching(self):
        # Mixed-case model name — should not crash and should match sonnet fallback
        result_lower = get_model_pricing("claude-sonnet-99-x")
        result_upper = get_model_pricing("Claude-SONNET-99-X")
        self.assertEqual(result_lower, result_upper)
        self.assertEqual(result_upper, MODEL_PRICING["claude-sonnet"])

    def test_case_insensitive_haiku(self):
        result = get_model_pricing("CLAUDE-HAIKU-UNLISTED")
        self.assertEqual(result, MODEL_PRICING["claude-haiku"])

    def test_sonnet_5_beats_sonnet_1m(self):
        # "sonnet-5" check comes before "sonnet"+"1m" — this is NOT a 1m variant
        # but the model name contains both "sonnet-5" and could match other paths
        result = get_model_pricing("claude-sonnet-5-beta")
        self.assertEqual(result, MODEL_PRICING["claude-sonnet-5"])


# ---------------------------------------------------------------------------
# _aggregate_requests_by_key
# ---------------------------------------------------------------------------

class TestAggregateRequestsByKey(unittest.TestCase):

    def test_empty_list(self):
        result = _aggregate_requests_by_key([], "model")
        self.assertEqual(dict(result), {})

    def test_single_request_by_model(self):
        req = _make_api_request_dict(model="claude-sonnet-4-6", input_tokens=100, output_tokens=50)
        result = _aggregate_requests_by_key([req], "model")
        self.assertIn("claude-sonnet-4-6", result)
        self.assertEqual(result["claude-sonnet-4-6"]["api_calls"], 1)
        self.assertEqual(result["claude-sonnet-4-6"]["input_tokens"], 100)
        self.assertEqual(result["claude-sonnet-4-6"]["output_tokens"], 50)

    def test_multiple_requests_same_key_summed(self):
        reqs = [
            _make_api_request_dict(model="claude-haiku-4-5", input_tokens=100, output_tokens=50),
            _make_api_request_dict(model="claude-haiku-4-5", input_tokens=200, output_tokens=80),
        ]
        result = _aggregate_requests_by_key(reqs, "model")
        self.assertEqual(result["claude-haiku-4-5"]["api_calls"], 2)
        self.assertEqual(result["claude-haiku-4-5"]["input_tokens"], 300)
        self.assertEqual(result["claude-haiku-4-5"]["output_tokens"], 130)

    def test_different_keys_stay_separate(self):
        reqs = [
            _make_api_request_dict(model="claude-haiku-4-5", input_tokens=100),
            _make_api_request_dict(model="claude-sonnet-4-6", input_tokens=200),
        ]
        result = _aggregate_requests_by_key(reqs, "model")
        self.assertEqual(len(result), 2)
        self.assertEqual(result["claude-haiku-4-5"]["input_tokens"], 100)
        self.assertEqual(result["claude-sonnet-4-6"]["input_tokens"], 200)

    def test_aggregate_by_session_id(self):
        reqs = [
            _make_api_request_dict(session_id="sess-1", input_tokens=50),
            _make_api_request_dict(session_id="sess-1", input_tokens=75),
            _make_api_request_dict(session_id="sess-2", input_tokens=100),
        ]
        result = _aggregate_requests_by_key(reqs, "session_id")
        self.assertEqual(result["sess-1"]["input_tokens"], 125)
        self.assertEqual(result["sess-2"]["input_tokens"], 100)

    def test_cache_tokens_summed(self):
        reqs = [
            _make_api_request_dict(cache_creation_tokens=30, cache_read_tokens=200),
            _make_api_request_dict(cache_creation_tokens=10, cache_read_tokens=100),
        ]
        result = _aggregate_requests_by_key(reqs, "model")
        agg = result["claude-sonnet-4-6"]
        self.assertEqual(agg["cache_creation_tokens"], 40)
        self.assertEqual(agg["cache_read_tokens"], 300)


# ---------------------------------------------------------------------------
# _aggregate_requests_by_session_and_model
# ---------------------------------------------------------------------------

class TestAggregateRequestsBySessionAndModel(unittest.TestCase):

    def test_empty_list(self):
        result = _aggregate_requests_by_session_and_model([])
        self.assertEqual(dict(result), {})

    def test_single_request(self):
        req = _make_api_request_dict(session_id="s1", model="claude-haiku-4-5", input_tokens=100)
        result = _aggregate_requests_by_session_and_model([req])
        key = ("s1", "claude-haiku-4-5")
        self.assertIn(key, result)
        self.assertEqual(result[key]["api_calls"], 1)
        self.assertEqual(result[key]["input_tokens"], 100)

    def test_same_session_same_model_summed(self):
        reqs = [
            _make_api_request_dict(session_id="s1", model="claude-sonnet-4-6", input_tokens=100),
            _make_api_request_dict(session_id="s1", model="claude-sonnet-4-6", input_tokens=150),
        ]
        result = _aggregate_requests_by_session_and_model(reqs)
        key = ("s1", "claude-sonnet-4-6")
        self.assertEqual(result[key]["api_calls"], 2)
        self.assertEqual(result[key]["input_tokens"], 250)

    def test_same_session_different_models_separate(self):
        reqs = [
            _make_api_request_dict(session_id="s1", model="claude-sonnet-4-6", input_tokens=100),
            _make_api_request_dict(session_id="s1", model="claude-haiku-4-5", input_tokens=50),
        ]
        result = _aggregate_requests_by_session_and_model(reqs)
        self.assertEqual(len(result), 2)
        self.assertIn(("s1", "claude-sonnet-4-6"), result)
        self.assertIn(("s1", "claude-haiku-4-5"), result)

    def test_different_sessions_same_model_separate(self):
        reqs = [
            _make_api_request_dict(session_id="s1", model="claude-haiku-4-5", input_tokens=100),
            _make_api_request_dict(session_id="s2", model="claude-haiku-4-5", input_tokens=200),
        ]
        result = _aggregate_requests_by_session_and_model(reqs)
        self.assertEqual(result[("s1", "claude-haiku-4-5")]["input_tokens"], 100)
        self.assertEqual(result[("s2", "claude-haiku-4-5")]["input_tokens"], 200)


# ---------------------------------------------------------------------------
# _calculate_totals
# ---------------------------------------------------------------------------

class TestCalculateTotals(unittest.TestCase):

    def test_empty_list(self):
        result = _calculate_totals([])
        self.assertEqual(result["api_calls"], 0)
        self.assertEqual(result["input"], 0)
        self.assertEqual(result["output"], 0)
        self.assertEqual(result["cache_creation"], 0)
        self.assertEqual(result["cache_read"], 0)

    def test_single_request(self):
        req = _make_api_request_dict(
            input_tokens=100, output_tokens=50,
            cache_creation_tokens=20, cache_read_tokens=300,
        )
        result = _calculate_totals([req])
        self.assertEqual(result["api_calls"], 1)
        self.assertEqual(result["input"], 100)
        self.assertEqual(result["output"], 50)
        self.assertEqual(result["cache_creation"], 20)
        self.assertEqual(result["cache_read"], 300)

    def test_multiple_requests_summed(self):
        reqs = [
            _make_api_request_dict(input_tokens=100, output_tokens=50),
            _make_api_request_dict(input_tokens=200, output_tokens=80),
            _make_api_request_dict(input_tokens=150, output_tokens=30),
        ]
        result = _calculate_totals(reqs)
        self.assertEqual(result["api_calls"], 3)
        self.assertEqual(result["input"], 450)
        self.assertEqual(result["output"], 160)


# ---------------------------------------------------------------------------
# _build_session_timestamps
# ---------------------------------------------------------------------------

class TestBuildSessionTimestamps(unittest.TestCase):

    def test_empty_list(self):
        result = _build_session_timestamps([])
        self.assertEqual(result, {})

    def test_single_request(self):
        ts = _utc(2026, 7, 1, 10)
        req = _make_api_request_dict(session_id="s1", timestamp=ts)
        result = _build_session_timestamps([req])
        self.assertEqual(result["s1"]["first_seen"], ts)
        self.assertEqual(result["s1"]["last_seen"], ts)

    def test_first_seen_last_seen_tracked(self):
        t1 = _utc(2026, 7, 1, 10)
        t2 = _utc(2026, 7, 1, 11)
        t3 = _utc(2026, 7, 1, 12)
        reqs = [
            _make_api_request_dict(session_id="s1", timestamp=t2),
            _make_api_request_dict(session_id="s1", timestamp=t3),  # hits last_seen branch
            _make_api_request_dict(session_id="s1", timestamp=t1),  # hits first_seen branch
        ]
        result = _build_session_timestamps(reqs)
        self.assertEqual(result["s1"]["first_seen"], t1)
        self.assertEqual(result["s1"]["last_seen"], t3)

    def test_multiple_sessions_independent(self):
        t1 = _utc(2026, 7, 1)
        t2 = _utc(2026, 7, 2)
        reqs = [
            _make_api_request_dict(session_id="s1", timestamp=t1),
            _make_api_request_dict(session_id="s2", timestamp=t2),
        ]
        result = _build_session_timestamps(reqs)
        self.assertEqual(result["s1"]["first_seen"], t1)
        self.assertEqual(result["s2"]["first_seen"], t2)

    def test_later_timestamp_updates_last_seen(self):
        t1 = _utc(2026, 7, 1, 9)
        t2 = _utc(2026, 7, 1, 11)
        # t1 first, then t2 — should update last_seen to t2
        reqs = [
            _make_api_request_dict(session_id="s1", timestamp=t1),
            _make_api_request_dict(session_id="s1", timestamp=t2),
        ]
        result = _build_session_timestamps(reqs)
        self.assertEqual(result["s1"]["last_seen"], t2)

    def test_earlier_timestamp_updates_first_seen(self):
        t1 = _utc(2026, 7, 1, 9)
        t2 = _utc(2026, 7, 1, 7)
        # t1 first, then t2 which is earlier — should update first_seen to t2
        reqs = [
            _make_api_request_dict(session_id="s1", timestamp=t1),
            _make_api_request_dict(session_id="s1", timestamp=t2),
        ]
        result = _build_session_timestamps(reqs)
        self.assertEqual(result["s1"]["first_seen"], t2)


# ---------------------------------------------------------------------------
# _build_session_costs
# ---------------------------------------------------------------------------

class TestBuildSessionCosts(unittest.TestCase):

    def _make_session_model_data(
        self,
        session_id: str,
        model: str,
        input_tokens: int = 1_000_000,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        api_calls: int = 1,
    ) -> dict:
        return {
            (session_id, model): {
                "api_calls": api_calls,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_tokens": cache_creation_tokens,
                "cache_read_tokens": cache_read_tokens,
            }
        }

    def test_basic_cost_calculation(self):
        # sonnet-4-6: input=$3/M, output=$15/M
        data = self._make_session_model_data(
            "s1", "claude-sonnet-4-6",
            input_tokens=1_000_000, output_tokens=1_000_000,
        )
        costs = _build_session_costs(data)
        self.assertEqual(len(costs), 1)
        expected_cost = 3.0 + 15.0  # $3 input + $15 output
        self.assertAlmostEqual(costs[0].cost, expected_cost, places=6)
        self.assertEqual(costs[0].session_id, "s1")

    def test_cache_creation_costs(self):
        # sonnet-4-6 input=$3/M; cache_creation = input * 1.25 / 1M
        data = self._make_session_model_data(
            "s1", "claude-sonnet-4-6",
            input_tokens=0, output_tokens=0,
            cache_creation_tokens=1_000_000,
        )
        costs = _build_session_costs(data)
        expected = 3.0 * 1.25  # $3.75
        self.assertAlmostEqual(costs[0].cost, expected, places=6)

    def test_cache_read_costs(self):
        # sonnet-4-6 input=$3/M; cache_read = input * 0.1 / 1M
        data = self._make_session_model_data(
            "s1", "claude-sonnet-4-6",
            input_tokens=0, output_tokens=0,
            cache_read_tokens=1_000_000,
        )
        costs = _build_session_costs(data)
        expected = 3.0 * 0.1  # $0.30
        self.assertAlmostEqual(costs[0].cost, expected, places=6)

    def test_efficiency_ratio(self):
        data = self._make_session_model_data(
            "s1", "claude-haiku-4-5",
            input_tokens=200, output_tokens=50,
        )
        costs = _build_session_costs(data)
        self.assertAlmostEqual(costs[0].efficiency_ratio, 50 / 200, places=6)

    def test_efficiency_ratio_zero_input_tokens(self):
        # Guard against ZeroDivisionError when input_tokens==0
        data = self._make_session_model_data(
            "s1", "claude-haiku-4-5",
            input_tokens=0, output_tokens=100,
        )
        costs = _build_session_costs(data)
        self.assertEqual(costs[0].efficiency_ratio, 0.0)

    def test_timestamps_attached(self):
        data = self._make_session_model_data("s1", "claude-haiku-4-5")
        ts_first = _utc(2026, 7, 1, 9)
        ts_last = _utc(2026, 7, 1, 11)
        session_timestamps = {"s1": {"first_seen": ts_first, "last_seen": ts_last}}
        costs = _build_session_costs(data, session_timestamps=session_timestamps)
        self.assertEqual(costs[0].first_seen, ts_first)
        self.assertEqual(costs[0].last_seen, ts_last)

    def test_timestamps_none_when_not_provided(self):
        data = self._make_session_model_data("s1", "claude-haiku-4-5")
        costs = _build_session_costs(data)
        self.assertIsNone(costs[0].first_seen)
        self.assertIsNone(costs[0].last_seen)

    def test_perf_attached(self):
        data = self._make_session_model_data("s1", "claude-haiku-4-5")
        perf = SessionPerf(error_count=2, error_rate=0.1)
        costs = _build_session_costs(data, session_perf={"s1": perf})
        self.assertEqual(costs[0].perf, perf)

    def test_perf_none_when_not_provided(self):
        data = self._make_session_model_data("s1", "claude-haiku-4-5")
        costs = _build_session_costs(data)
        self.assertIsNone(costs[0].perf)

    def test_sorted_by_session_id(self):
        data = {
            ("s-bravo", "claude-haiku-4-5"): {"api_calls": 1, "input_tokens": 10, "output_tokens": 5, "cache_creation_tokens": 0, "cache_read_tokens": 0},
            ("s-alpha", "claude-haiku-4-5"): {"api_calls": 1, "input_tokens": 20, "output_tokens": 10, "cache_creation_tokens": 0, "cache_read_tokens": 0},
        }
        costs = _build_session_costs(data)
        self.assertEqual(costs[0].session_id, "s-alpha")
        self.assertEqual(costs[1].session_id, "s-bravo")

    def test_multiple_models_same_session_summed(self):
        data = {
            ("s1", "claude-haiku-4-5"): {"api_calls": 1, "input_tokens": 100_000, "output_tokens": 50_000, "cache_creation_tokens": 0, "cache_read_tokens": 0},
            ("s1", "claude-sonnet-4-6"): {"api_calls": 2, "input_tokens": 200_000, "output_tokens": 100_000, "cache_creation_tokens": 0, "cache_read_tokens": 0},
        }
        costs = _build_session_costs(data)
        self.assertEqual(len(costs), 1)
        self.assertEqual(costs[0].api_calls, 3)
        self.assertEqual(costs[0].input_tokens, 300_000)
        self.assertEqual(costs[0].output_tokens, 150_000)
        # Cost: haiku input 0.1¢ + haiku output 0.25¢ + sonnet input 0.6¢ + sonnet output 1.5¢
        haiku_cost = (100_000 * 1.0 / 1_000_000) + (50_000 * 5.0 / 1_000_000)
        sonnet_cost = (200_000 * 3.0 / 1_000_000) + (100_000 * 15.0 / 1_000_000)
        self.assertAlmostEqual(costs[0].cost, haiku_cost + sonnet_cost, places=6)
        # input 300_000, output 150_000 -> efficiency_ratio = 150_000 / 300_000 = 0.5
        self.assertAlmostEqual(costs[0].efficiency_ratio, 0.5, places=6)


# ---------------------------------------------------------------------------
# _build_model_costs
# ---------------------------------------------------------------------------

class TestBuildModelCosts(unittest.TestCase):

    def _make_model_data(
        self,
        model_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        api_calls: int = 1,
    ) -> dict:
        return {
            model_name: {
                "api_calls": api_calls,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_tokens": cache_creation_tokens,
                "cache_read_tokens": cache_read_tokens,
            }
        }

    def test_basic_cost_calculation(self):
        # haiku: $1/M input, $5/M output
        data = self._make_model_data(
            "claude-haiku-4-5",
            input_tokens=1_000_000, output_tokens=1_000_000,
        )
        costs = _build_model_costs(data)
        self.assertEqual(len(costs), 1)
        self.assertAlmostEqual(costs[0].cost, 6.0, places=6)  # $1 + $5

    def test_cache_creation_multiplier(self):
        # haiku: $1/M input; cache_creation = 1 * 1.25 = $1.25
        data = self._make_model_data("claude-haiku-4-5", cache_creation_tokens=1_000_000)
        costs = _build_model_costs(data)
        self.assertAlmostEqual(costs[0].cost, 1.25, places=6)

    def test_cache_read_multiplier(self):
        # haiku: $1/M input; cache_read = 1 * 0.1 = $0.10
        data = self._make_model_data("claude-haiku-4-5", cache_read_tokens=1_000_000)
        costs = _build_model_costs(data)
        self.assertAlmostEqual(costs[0].cost, 0.10, places=6)

    def test_efficiency_ratio(self):
        data = self._make_model_data("claude-haiku-4-5", input_tokens=400, output_tokens=100)
        costs = _build_model_costs(data)
        self.assertAlmostEqual(costs[0].efficiency_ratio, 100 / 400, places=6)

    def test_efficiency_ratio_zero_input(self):
        data = self._make_model_data("claude-haiku-4-5", input_tokens=0, output_tokens=100)
        costs = _build_model_costs(data)
        self.assertEqual(costs[0].efficiency_ratio, 0.0)

    def test_sorted_by_model_name(self):
        data = {
            "claude-sonnet-4-6": {"api_calls": 1, "input_tokens": 100, "output_tokens": 50, "cache_creation_tokens": 0, "cache_read_tokens": 0},
            "claude-haiku-4-5": {"api_calls": 1, "input_tokens": 200, "output_tokens": 80, "cache_creation_tokens": 0, "cache_read_tokens": 0},
        }
        costs = _build_model_costs(data)
        self.assertEqual(costs[0].model_name, "claude-haiku-4-5")
        self.assertEqual(costs[1].model_name, "claude-sonnet-4-6")


# ---------------------------------------------------------------------------
# _accumulate_cost_datapoints
# ---------------------------------------------------------------------------

class TestAccumulateCostDatapoints(unittest.TestCase):

    def _make_metric_point(self, value: float, dt: datetime) -> MetricDataPoint:
        ts_nano = _nano(dt)
        return MetricDataPoint(
            start_time_unix_nano=ts_nano,
            time_unix_nano=ts_nano,
            value=value,
        )

    def test_no_since_dt_accumulates_all(self):
        daily_cost: dict[str, float] = defaultdict(float)
        daily_calls: dict[str, int] = defaultdict(int)
        points = [
            self._make_metric_point(1.5, _utc(2026, 7, 1)),
            self._make_metric_point(2.0, _utc(2026, 7, 2)),
        ]
        _accumulate_cost_datapoints(points, None, daily_cost, daily_calls)
        self.assertAlmostEqual(daily_cost["2026-07-01"], 1.5, places=6)
        self.assertAlmostEqual(daily_cost["2026-07-02"], 2.0, places=6)
        self.assertEqual(daily_calls["2026-07-01"], 1)

    def test_since_dt_filters_earlier_points(self):
        daily_cost: dict[str, float] = defaultdict(float)
        daily_calls: dict[str, int] = defaultdict(int)
        since = _utc(2026, 7, 2)
        points = [
            self._make_metric_point(1.5, _utc(2026, 7, 1)),   # strictly before cutoff — excluded
            self._make_metric_point(2.0, _utc(2026, 7, 2)),   # equal to cutoff — included (filter is <, not <=)
            self._make_metric_point(3.0, _utc(2026, 7, 3)),   # after cutoff — included
        ]
        _accumulate_cost_datapoints(points, since, daily_cost, daily_calls)
        self.assertNotIn("2026-07-01", daily_cost)
        self.assertAlmostEqual(daily_cost["2026-07-02"], 2.0, places=6)
        self.assertAlmostEqual(daily_cost["2026-07-03"], 3.0, places=6)
        self.assertEqual(daily_calls["2026-07-03"], 1)

    def test_accumulates_multiple_points_same_date(self):
        daily_cost: dict[str, float] = defaultdict(float)
        daily_calls: dict[str, int] = defaultdict(int)
        # Two points on same date
        t1 = _utc(2026, 7, 1, 9)
        t2 = _utc(2026, 7, 1, 14)
        points = [
            self._make_metric_point(1.0, t1),
            self._make_metric_point(2.0, t2),
        ]
        _accumulate_cost_datapoints(points, None, daily_cost, daily_calls)
        self.assertAlmostEqual(daily_cost["2026-07-01"], 3.0, places=6)
        self.assertEqual(daily_calls["2026-07-01"], 2)

    def test_empty_points(self):
        daily_cost: dict[str, float] = defaultdict(float)
        daily_calls: dict[str, int] = defaultdict(int)
        _accumulate_cost_datapoints([], None, daily_cost, daily_calls)
        self.assertFalse(daily_cost)
        self.assertFalse(daily_calls)


# ---------------------------------------------------------------------------
# get_all_costs — integration with mocked OTLPReader
# ---------------------------------------------------------------------------

class TestGetAllCosts(unittest.TestCase):

    def _make_simple_record(
        self,
        session_id: str = "sess-1",
        model: str = "claude-sonnet-4-6",
        input_tokens: int = 1000,
        output_tokens: int = 500,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> OTLPEventsRecord:
        event = _make_api_request_event(
            session_id=session_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
        )
        return _make_events_record([event])

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_basic_get_all_costs(self, mock_reader_cls):
        record = self._make_simple_record(
            session_id="sess-1",
            model="claude-sonnet-4-6",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        data_dir = OTLPDataDir.default()

        result = get_all_costs(data_dir=data_dir)

        self.assertEqual(result.total_api_calls, 1)
        self.assertEqual(result.total_input_tokens, 1_000_000)
        self.assertEqual(result.total_output_tokens, 1_000_000)
        expected_cost = 3.0 + 15.0  # sonnet: $3 in + $15 out
        self.assertAlmostEqual(result.total_cost, expected_cost, places=4)
        self.assertEqual(len(result.by_session), 1)
        self.assertEqual(len(result.by_model), 1)
        self.assertEqual(result.by_session[0].session_id, "sess-1")
        self.assertEqual(result.by_model[0].model_name, "claude-sonnet-4-6")

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_efficiency_ratio_calculation(self, mock_reader_cls):
        record = self._make_simple_record(
            input_tokens=400_000, output_tokens=100_000,
        )
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_all_costs(data_dir=OTLPDataDir.default())
        self.assertAlmostEqual(result.efficiency_ratio, 100_000 / 400_000, places=6)

    @mock.patch("telemetry.otel.analytics.cost.OTLPDataDir")
    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_no_data_dir_uses_from_env(self, mock_reader_cls, mock_data_dir_cls):
        mock_data_dir_cls.from_env.return_value = mock.MagicMock()
        mock_reader_cls.return_value.read_events.return_value = []
        result = get_all_costs()
        mock_data_dir_cls.from_env.assert_called_once()
        self.assertEqual(result.total_api_calls, 0)

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_explicit_data_dir_skips_from_env(self, mock_reader_cls):
        from telemetry.otel.reader import OTLPDataDir
        data_dir = OTLPDataDir.default()
        mock_reader_cls.return_value.read_events.return_value = []
        get_all_costs(data_dir=data_dir)
        # OTLPReader should be called with the provided data_dir
        mock_reader_cls.assert_called_once_with(data_dir)

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_cache_savings_estimated(self, mock_reader_cls):
        # Cache reads reduce effective input cost
        # Fixture: input=800_000, cache_read=200_000, output=500, model=claude-sonnet-4-6
        # total_cost = (800_000*3.0 + 500*15.0 + 200_000*3.0*0.1) / 1_000_000 = 2.4675
        # input_ratio = 800_000 / (800_000 + 200_000) = 0.8
        # cache_savings = 2.4675 * (1 - 0.8) * 0.9 = 0.44415
        record = self._make_simple_record(
            input_tokens=800_000,
            cache_read_tokens=200_000,
        )
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_all_costs(data_dir=OTLPDataDir.default())
        self.assertAlmostEqual(result.total_cache_savings, 0.44415, places=4)

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_since_cutoff_filters_events(self, mock_reader_cls):
        # Event before cutoff is excluded; event after is included
        old_event = _make_api_request_event(
            session_id="sess-old", model="claude-haiku-4-5",
            input_tokens=500, dt=_utc(2026, 1, 1),
        )
        new_event = _make_api_request_event(
            session_id="sess-new", model="claude-haiku-4-5",
            input_tokens=1000, dt=_utc(2026, 7, 15),
        )
        record = _make_events_record([old_event, new_event])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        since = _utc(2026, 7, 1)
        result = get_all_costs(data_dir=OTLPDataDir.default(), since=since)
        self.assertEqual(result.total_api_calls, 1)
        self.assertEqual(result.total_input_tokens, 1000)

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_multiple_sessions(self, mock_reader_cls):
        r1 = self._make_simple_record(session_id="s1", input_tokens=100)
        r2 = self._make_simple_record(session_id="s2", input_tokens=200)
        mock_reader_cls.return_value.read_events.return_value = [r1, r2]
        from telemetry.otel.reader import OTLPDataDir
        result = get_all_costs(data_dir=OTLPDataDir.default())
        self.assertEqual(result.total_api_calls, 2)
        self.assertEqual(len(result.by_session), 2)

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_empty_events_zero_cost(self, mock_reader_cls):
        mock_reader_cls.return_value.read_events.return_value = []
        from telemetry.otel.reader import OTLPDataDir
        result = get_all_costs(data_dir=OTLPDataDir.default())
        self.assertEqual(result.total_cost, 0.0)
        self.assertEqual(result.efficiency_ratio, 0.0)
        self.assertEqual(result.by_session, [])
        self.assertEqual(result.by_model, [])

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_mixed_event_types(self, mock_reader_cls):
        # api_request, api_error, tool_result, user_prompt in same record
        api_event = _make_api_request_event("sess-1", input_tokens=1000)
        err_event = _make_error_event("sess-1")
        tool_event = _make_tool_event("sess-1")
        prompt_event = _make_prompt_event("sess-1")
        record = _make_events_record([api_event, err_event, tool_event, prompt_event])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_all_costs(data_dir=OTLPDataDir.default())
        # Only api_request contributes to api_calls/costs
        self.assertEqual(result.total_api_calls, 1)
        # Session perf should have error_count=1 and tool_calls=1
        self.assertEqual(len(result.by_session), 1)
        perf = result.by_session[0].perf
        self.assertIsNotNone(perf)
        self.assertEqual(perf.error_count, 1)
        self.assertEqual(perf.tool_calls, 1)
        self.assertEqual(perf.prompt_count, 1)


# ---------------------------------------------------------------------------
# get_daily_costs — integration with mocked OTLPReader
# ---------------------------------------------------------------------------

class TestGetDailyCosts(unittest.TestCase):

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_basic_daily_aggregation(self, mock_reader_cls):
        dt1 = _utc(2026, 7, 1, 10)
        dt2 = _utc(2026, 7, 2, 10)
        r1 = _make_events_record([
            _make_api_request_event("s1", model="claude-haiku-4-5",
                                    input_tokens=1_000_000, output_tokens=0, dt=dt1),
        ])
        r2 = _make_events_record([
            _make_api_request_event("s2", model="claude-haiku-4-5",
                                    input_tokens=0, output_tokens=1_000_000, dt=dt2),
        ])
        mock_reader_cls.return_value.read_events.return_value = [r1, r2]
        from telemetry.otel.reader import OTLPDataDir
        result = get_daily_costs(data_dir=OTLPDataDir.default())
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].date, "2026-07-01")
        self.assertAlmostEqual(result[0].cost, 1.0, places=4)  # $1/M input for haiku
        self.assertEqual(result[1].date, "2026-07-02")
        self.assertAlmostEqual(result[1].cost, 5.0, places=4)  # $5/M output for haiku

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_sorted_by_date_ascending(self, mock_reader_cls):
        # Feed events in reverse order (later date first) so sorting is actually exercised
        dt1 = _utc(2026, 7, 3)
        dt2 = _utc(2026, 7, 1)
        r1 = _make_events_record([_make_api_request_event("s1", dt=dt1)])
        r2 = _make_events_record([_make_api_request_event("s2", dt=dt2)])
        mock_reader_cls.return_value.read_events.return_value = [r1, r2]
        from telemetry.otel.reader import OTLPDataDir
        result = get_daily_costs(data_dir=OTLPDataDir.default())
        dates = [d.date for d in result]
        self.assertEqual(dates, ['2026-07-01', '2026-07-03'])

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_same_day_requests_summed(self, mock_reader_cls):
        dt = _utc(2026, 7, 1)
        record = _make_events_record([
            _make_api_request_event("s1", input_tokens=500_000, dt=dt),
            _make_api_request_event("s2", input_tokens=500_000, dt=dt),
        ])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_daily_costs(data_dir=OTLPDataDir.default())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].api_calls, 2)

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_empty_events_empty_list(self, mock_reader_cls):
        mock_reader_cls.return_value.read_events.return_value = []
        from telemetry.otel.reader import OTLPDataDir
        result = get_daily_costs(data_dir=OTLPDataDir.default())
        self.assertEqual(result, [])

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_since_string_filters_events(self, mock_reader_cls):
        # Use "99999d" window — always includes 2026 fixture regardless of wall-clock
        dt_recent = _utc(2026, 7, 1)
        record = _make_events_record([
            _make_api_request_event("s1", dt=dt_recent),
        ])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_daily_costs(data_dir=OTLPDataDir.default(), since="99999d")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].date, "2026-07-01")

    @mock.patch("telemetry.otel.analytics.cost.OTLPDataDir")
    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_no_data_dir_uses_from_env(self, mock_reader_cls, mock_data_dir_cls):
        mock_data_dir_cls.from_env.return_value = mock.MagicMock()
        mock_reader_cls.return_value.read_events.return_value = []
        get_daily_costs()
        mock_data_dir_cls.from_env.assert_called_once()

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_daily_cost_includes_token_fields(self, mock_reader_cls):
        record = _make_events_record([
            _make_api_request_event(
                "s1", input_tokens=100, output_tokens=50,
                cache_creation_tokens=20, cache_read_tokens=300,
                dt=_utc(2026, 7, 1),
            ),
        ])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_daily_costs(data_dir=OTLPDataDir.default())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].input_tokens, 100)
        self.assertEqual(result[0].output_tokens, 50)
        self.assertEqual(result[0].cache_creation_tokens, 20)
        self.assertEqual(result[0].cache_read_tokens, 300)


# ---------------------------------------------------------------------------
# get_model_performance — integration with mocked OTLPReader
# ---------------------------------------------------------------------------

class TestGetModelPerformance(unittest.TestCase):

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_basic_model_performance(self, mock_reader_cls):
        record = _make_events_record([
            _make_api_request_event(
                "s1", model="claude-haiku-4-5",
                input_tokens=1_000_000, output_tokens=0,
                duration_ms=500.0,
            ),
        ])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_model_performance(data_dir=OTLPDataDir.default())
        self.assertEqual(len(result), 1)
        perf = result[0]
        self.assertEqual(perf.model_name, "claude-haiku-4-5")
        self.assertEqual(perf.api_calls, 1)
        self.assertAlmostEqual(perf.avg_latency_ms, 500.0, places=1)
        self.assertAlmostEqual(perf.p95_latency_ms, 500.0, places=1)

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_cost_formula_omits_cache_read(self, mock_reader_cls):
        # get_model_performance cost = input + output + cache_creation*1 (NOT 1.25)
        # and does NOT include cache_read term at all
        record = _make_events_record([
            _make_api_request_event(
                "s1", model="claude-haiku-4-5",
                input_tokens=1_000_000, output_tokens=1_000_000,
                cache_creation_tokens=1_000_000, cache_read_tokens=999_999,
            ),
        ])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_model_performance(data_dir=OTLPDataDir.default())
        perf = result[0]
        # haiku: $1 input + $5 output + $1 cache_creation (1.0x not 1.25x)
        expected_cost = 1.0 + 5.0 + 1.0
        self.assertAlmostEqual(perf.cost, expected_cost, places=4)

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_sorted_by_model_name(self, mock_reader_cls):
        # Feed models in reverse-sorted order (sonnet before haiku) to exercise sort
        record = _make_events_record([
            _make_api_request_event("s1", model="claude-sonnet-4-6"),
            _make_api_request_event("s1", model="claude-haiku-4-5"),
        ])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_model_performance(data_dir=OTLPDataDir.default())
        model_names = [p.model_name for p in result]
        self.assertEqual(model_names, ['claude-haiku-4-5', 'claude-sonnet-4-6'])

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_error_rate_zero_when_no_errors(self, mock_reader_cls):
        record = _make_events_record([
            _make_api_request_event("s1", model="claude-haiku-4-5"),
        ])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_model_performance(data_dir=OTLPDataDir.default())
        self.assertEqual(result[0].error_count, 0)
        self.assertEqual(result[0].error_rate, 0.0)

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_error_attribution_proportional(self, mock_reader_cls):
        # Session s1 with 2 api calls for the SAME model (claude-haiku-4-5) + 1 error.
        # proportion = 2/2 = 1.0, round(1 * 1.0) = 1, so exactly 1 error is attributed.
        e1 = _make_api_request_event("s1", model="claude-haiku-4-5", dt=_utc(2026, 7, 1, 9))
        e2 = _make_api_request_event("s1", model="claude-haiku-4-5", dt=_utc(2026, 7, 1, 10))
        err = _make_error_event("s1")
        record = _make_events_record([e1, e2, err])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_model_performance(data_dir=OTLPDataDir.default())
        # Exactly one ModelPerformance result for claude-haiku-4-5
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].model_name, "claude-haiku-4-5")
        # 2 api calls, 1 error attributed deterministically
        self.assertEqual(result[0].api_calls, 2)
        self.assertEqual(result[0].error_count, 1)
        # error_rate is one error over two calls, i.e. one half
        self.assertAlmostEqual(result[0].error_rate, 0.5, places=6)

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_empty_api_calls_no_divide_by_zero(self, mock_reader_cls):
        # Events with no api_request body — only errors, so model_data is empty
        # But we can also check with empty events
        mock_reader_cls.return_value.read_events.return_value = []
        from telemetry.otel.reader import OTLPDataDir
        result = get_model_performance(data_dir=OTLPDataDir.default())
        # No division error
        self.assertEqual(result, [])

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_errors_without_api_requests_returns_empty(self, mock_reader_cls):
        # Session has api_error events but ZERO api_request events.
        # model_mix is empty so the attribution guard (perf.model_mix) is falsy —
        # no errors attributed, model_data stays empty, result is [].
        record = _make_events_record([_make_error_event("s1")])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_model_performance(data_dir=OTLPDataDir.default())
        self.assertEqual(result, [])

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_avg_latency_across_multiple_calls(self, mock_reader_cls):
        record = _make_events_record([
            _make_api_request_event("s1", model="claude-haiku-4-5", duration_ms=100.0),
            _make_api_request_event("s1", model="claude-haiku-4-5", duration_ms=300.0),
        ])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_model_performance(data_dir=OTLPDataDir.default())
        self.assertAlmostEqual(result[0].avg_latency_ms, 200.0, places=1)

    @mock.patch("telemetry.otel.analytics.cost.OTLPDataDir")
    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_no_data_dir_uses_from_env(self, mock_reader_cls, mock_data_dir_cls):
        mock_data_dir_cls.from_env.return_value = mock.MagicMock()
        mock_reader_cls.return_value.read_events.return_value = []
        get_model_performance()
        mock_data_dir_cls.from_env.assert_called_once()

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_since_string_parsing(self, mock_reader_cls):
        # "99999d" window always includes 2026 fixture regardless of wall-clock
        record = _make_events_record([
            _make_api_request_event("s1", model="claude-haiku-4-5", dt=_utc(2026, 7, 15)),
        ])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_model_performance(data_dir=OTLPDataDir.default(), since="99999d")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].model_name, "claude-haiku-4-5")
        self.assertEqual(result[0].api_calls, 1)

    @mock.patch("telemetry.otel.analytics.cost.OTLPReader")
    def test_no_duration_ms_skipped_in_latencies(self, mock_reader_cls):
        # Event with duration_ms=None should not contribute to latency list
        # Build a special event with no duration_ms attribute
        ts_nano = _nano(_utc(2026, 7, 1))
        event_no_dur = OTLPEvent(
            time_unix_nano=ts_nano,
            observed_time_unix_nano=ts_nano,
            body="api_request",
            attributes=[
                _attr("session.id", "sess-nodur"),
                _attr("model", "claude-haiku-4-5"),
                _attr("input_tokens", "100"),
                _attr("output_tokens", "50"),
                _attr("cache_creation_tokens", "0"),
                _attr("cache_read_tokens", "0"),
                # No duration_ms attribute
            ],
        )
        record = _make_events_record([event_no_dur])
        mock_reader_cls.return_value.read_events.return_value = [record]
        from telemetry.otel.reader import OTLPDataDir
        result = get_model_performance(data_dir=OTLPDataDir.default())
        self.assertEqual(len(result), 1)
        # avg_latency_ms and p95 should both be 0 when no duration data
        self.assertEqual(result[0].avg_latency_ms, 0.0)
        self.assertEqual(result[0].p95_latency_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
