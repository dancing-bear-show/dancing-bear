"""Tests for telemetry/otel/menubar_dataclasses.py — frozen dataclasses and zero constructors."""
from __future__ import annotations

import unittest
from datetime import timezone

from telemetry.otel.menubar_dataclasses import (
    CodeImpact,
    HookHealth,
    MetaStats,
    OtelDisplayData,
    OtelModels,
    OtelUsage,
    SessionPatterns,
    Skills,
    ToolActivity,
    _unavailable,
    _zero_code_impact,
    _zero_hook_health,
    _zero_meta,
    _zero_models,
    _zero_session_patterns,
    _zero_skills,
    _zero_tool_activity,
    _zero_usage,
)


class TestZeroUsage(unittest.TestCase):
    def test_returns_otel_usage(self) -> None:
        result = _zero_usage()
        self.assertIsInstance(result, OtelUsage)

    def test_all_numeric_fields_are_zero(self) -> None:
        result = _zero_usage()
        self.assertEqual(result.cost_24h, 0.0)
        self.assertEqual(result.cost_7d, 0.0)
        self.assertEqual(result.input_tokens_24h, 0)
        self.assertEqual(result.output_tokens_24h, 0)
        self.assertEqual(result.cache_read_tokens_24h, 0)
        self.assertEqual(result.cache_creation_tokens_24h, 0)
        self.assertEqual(result.total_tokens_24h, 0)
        self.assertEqual(result.active_hours_24h, 0.0)

    def test_model_cost_breakdown_is_empty_list(self) -> None:
        result = _zero_usage()
        self.assertEqual(result.model_cost_breakdown, [])

    def test_frozen(self) -> None:
        result = _zero_usage()
        with self.assertRaises((AttributeError, TypeError)):
            result.cost_24h = 1.0  # type: ignore[misc]


class TestZeroModels(unittest.TestCase):
    def test_returns_otel_models(self) -> None:
        result = _zero_models()
        self.assertIsInstance(result, OtelModels)

    def test_model_rows_is_empty(self) -> None:
        result = _zero_models()
        self.assertEqual(result.model_rows, [])


class TestZeroMeta(unittest.TestCase):
    def test_returns_meta_stats(self) -> None:
        result = _zero_meta()
        self.assertIsInstance(result, MetaStats)

    def test_all_zero_by_default(self) -> None:
        result = _zero_meta()
        self.assertEqual(result.cost_per_active_hour, 0.0)
        self.assertEqual(result.cost_per_loc_added, 0.0)
        self.assertEqual(result.cost_per_commit, 0.0)
        self.assertEqual(result.cache_hit_rate_pct, 0.0)
        self.assertEqual(result.total_tokens_24h, 0)

    def test_total_tokens_parameter(self) -> None:
        result = _zero_meta(total_tokens=5000)
        self.assertEqual(result.total_tokens_24h, 5000)


class TestZeroHookHealth(unittest.TestCase):
    def test_returns_hook_health(self) -> None:
        result = _zero_hook_health()
        self.assertIsInstance(result, HookHealth)

    def test_all_zero(self) -> None:
        result = _zero_hook_health()
        self.assertEqual(result.hooks_fired_today, 0)
        self.assertEqual(result.avg_hook_latency_ms, 0.0)
        self.assertEqual(result.blocking_count, 0)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(result.hook_names, [])


class TestZeroToolActivity(unittest.TestCase):
    def test_returns_tool_activity(self) -> None:
        result = _zero_tool_activity()
        self.assertIsInstance(result, ToolActivity)

    def test_all_zero(self) -> None:
        result = _zero_tool_activity()
        self.assertEqual(result.tool_calls_today, 0)
        self.assertEqual(result.accept_rate_pct, 0.0)
        self.assertEqual(result.top_tools, [])
        self.assertEqual(result.tool_error_count, 0)
        self.assertEqual(result.bash_error_rate_pct, 0.0)
        self.assertEqual(result.avg_input_bytes, 0.0)
        self.assertEqual(result.avg_output_bytes, 0.0)


class TestZeroCodeImpact(unittest.TestCase):
    def test_returns_code_impact(self) -> None:
        result = _zero_code_impact()
        self.assertIsInstance(result, CodeImpact)

    def test_all_zero(self) -> None:
        result = _zero_code_impact()
        self.assertEqual(result.lines_added_today, 0)
        self.assertEqual(result.lines_removed_today, 0)
        self.assertEqual(result.top_languages, [])
        self.assertEqual(result.commits_today, 0)
        self.assertEqual(result.compaction_count, 0)
        self.assertEqual(result.tokens_saved_by_compaction, 0)


class TestZeroSkills(unittest.TestCase):
    def test_returns_skills(self) -> None:
        result = _zero_skills()
        self.assertIsInstance(result, Skills)

    def test_all_zero(self) -> None:
        result = _zero_skills()
        self.assertEqual(result.top_skills, [])
        self.assertEqual(result.skills_invoked_today, 0)


class TestZeroSessionPatterns(unittest.TestCase):
    def test_returns_session_patterns(self) -> None:
        result = _zero_session_patterns()
        self.assertIsInstance(result, SessionPatterns)

    def test_all_zero(self) -> None:
        result = _zero_session_patterns()
        self.assertEqual(result.prompts_today, 0)
        self.assertEqual(result.model_mix, [])
        self.assertEqual(result.agent_call_pct, 0.0)
        self.assertEqual(result.effort_mix, {})


class TestUnavailable(unittest.TestCase):
    def test_returns_otel_display_data(self) -> None:
        result = _unavailable()
        self.assertIsInstance(result, OtelDisplayData)

    def test_available_is_false(self) -> None:
        result = _unavailable()
        self.assertFalse(result.available)

    def test_collected_at_is_utc(self) -> None:
        result = _unavailable()
        self.assertEqual(result.collected_at.tzinfo, timezone.utc)

    def test_sub_objects_are_zero(self) -> None:
        result = _unavailable()
        self.assertIsInstance(result.otel_usage, OtelUsage)
        self.assertIsInstance(result.otel_models, OtelModels)
        self.assertIsInstance(result.meta_stats, MetaStats)
        self.assertIsInstance(result.hook_health, HookHealth)
        self.assertIsInstance(result.tool_activity, ToolActivity)
        self.assertIsInstance(result.code_impact, CodeImpact)
        self.assertIsInstance(result.skills, Skills)
        self.assertIsInstance(result.session_patterns, SessionPatterns)

    def test_frozen(self) -> None:
        result = _unavailable()
        with self.assertRaises((AttributeError, TypeError)):
            result.available = True  # type: ignore[misc]


class TestOtelUsageConstruction(unittest.TestCase):
    def test_construct_with_values(self) -> None:
        usage = OtelUsage(
            cost_24h=1.5,
            cost_7d=10.0,
            input_tokens_24h=1000,
            output_tokens_24h=500,
            cache_read_tokens_24h=200,
            cache_creation_tokens_24h=50,
            total_tokens_24h=1750,
            active_hours_24h=2.5,
            model_cost_breakdown=[("sonnet", 1.5)],
        )
        self.assertEqual(usage.cost_24h, 1.5)
        self.assertEqual(usage.model_cost_breakdown, [("sonnet", 1.5)])


class TestOtelModelsConstruction(unittest.TestCase):
    def test_construct_with_rows(self) -> None:
        models = OtelModels(model_rows=[("sonnet", 1.0, 5000), ("haiku", 0.5, 2000)])
        self.assertEqual(len(models.model_rows), 2)
        self.assertEqual(models.model_rows[0][0], "sonnet")


if __name__ == "__main__":
    unittest.main()
