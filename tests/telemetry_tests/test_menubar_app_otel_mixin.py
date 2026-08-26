"""Tests for OtelSectionsMixin in telemetry/_menubar_app_otel.py.

The mixin writes formatted strings into .title attributes on SimpleNamespace
objects that stand in for rumps.MenuItem instances.  Every assertion pins the
formatted output string, never mock call counts.
"""
from __future__ import annotations

import dataclasses
import unittest
from types import SimpleNamespace as NS

from telemetry._menubar_app_otel import OtelSectionsMixin
from telemetry.otel.menubar_dataclasses import (
    CodeImpact,
    HookHealth,
    MetaStats,
    OtelModels,
    SessionPatterns,
    Skills,
    ToolActivity,
    _unavailable,
    _zero_usage,
)

_HEADERS = (
    "_hdr_otel_usage",
    "_hdr_otel_models",
    "_hdr_otel_meta",
    "_hdr_hooks",
    "_hdr_tools",
    "_hdr_code",
    "_hdr_skills",
    "_hdr_session_patterns",
)


def _make_host(window_idx: int = 0) -> OtelSectionsMixin:
    """Return a minimal host wired with all row/header attributes."""

    class _Host(OtelSectionsMixin):
        pass

    host = _Host()
    host._otel_window_idx = window_idx
    for name in _HEADERS:
        setattr(host, name, NS(title="SENTINEL"))
    host._otel_usage_rows = [NS(title="") for _ in range(4)]
    host._otel_model_rows = [NS(title="") for _ in range(4)]
    host._otel_meta_rows = [NS(title="") for _ in range(4)]
    host._hook_rows = [NS(title="") for _ in range(4)]
    host._tool_rows = [NS(title="") for _ in range(5)]
    host._code_rows = [NS(title="") for _ in range(5)]
    host._skill_rows = [NS(title="") for _ in range(2)]
    host._session_pattern_rows = [NS(title="") for _ in range(3)]
    return host


def _avail(**kwargs):
    """Return an available OtelDisplayData with optional field overrides."""
    base = dataclasses.replace(_unavailable(), available=True)
    return dataclasses.replace(base, **kwargs) if kwargs else base


class TestClearOtelHeaders(unittest.TestCase):
    """_clear_otel_headers sets every header title to the empty string."""

    def test_all_headers_cleared(self):
        host = _make_host()
        host._clear_otel_headers()
        for name in _HEADERS:
            self.assertEqual(getattr(host, name).title, "")

    def test_already_empty_headers_stay_empty(self):
        host = _make_host()
        for name in _HEADERS:
            getattr(host, name).title = ""
        host._clear_otel_headers()
        for name in _HEADERS:
            self.assertEqual(getattr(host, name).title, "")


class TestUpdateOtelSectionsAUnavailable(unittest.TestCase):
    """When available=False, _update_otel_sections_a clears all headers."""

    def test_unavailable_clears_all_headers(self):
        host = _make_host()
        host._update_otel_sections_a(_unavailable(), {})
        for name in _HEADERS:
            self.assertEqual(getattr(host, name).title, "")

    def test_unavailable_ignores_enabled_sections(self):
        """Even with sections enabled, unavailable data clears headers."""
        host = _make_host()
        s = {
            "otel_usage": {"enabled": True},
            "otel_models": {"enabled": True},
        }
        host._update_otel_sections_a(_unavailable(), s)
        self.assertEqual(host._hdr_otel_usage.title, "")
        self.assertEqual(host._hdr_otel_models.title, "")


class TestUpdateOtelSectionsANoSections(unittest.TestCase):
    """With available=True but no sections enabled, headers stay untouched."""

    def test_no_sections_headers_unchanged(self):
        host = _make_host()
        host._update_otel_sections_a(_avail(), {})
        self.assertEqual(host._hdr_otel_usage.title, "SENTINEL")
        self.assertEqual(host._hdr_otel_models.title, "SENTINEL")

    def test_disabled_section_leaves_header(self):
        host = _make_host()
        host._update_otel_sections_a(_avail(), {"otel_usage": {"enabled": False}})
        self.assertEqual(host._hdr_otel_usage.title, "SENTINEL")


class TestUpdateOtelSectionsAOtelUsage(unittest.TestCase):
    """otel_usage section: window labels, cost suffix, token math."""

    def _host_with_usage(self, window_idx: int = 0, **usage_kwargs):
        usage = dataclasses.replace(_zero_usage(), **usage_kwargs) if usage_kwargs else _zero_usage()
        host = _make_host(window_idx=window_idx)
        host._update_otel_sections_a(
            _avail(otel_usage=usage),
            {"otel_usage": {"enabled": True}},
        )
        return host

    def test_header_shows_current_window_and_next_window(self):
        host = self._host_with_usage(window_idx=0)
        self.assertEqual(
            host._hdr_otel_usage.title,
            "-- OTel Usage (last 1h) [click: last 24h] --",
        )

    def test_header_window_idx_1(self):
        host = self._host_with_usage(window_idx=1)
        self.assertEqual(
            host._hdr_otel_usage.title,
            "-- OTel Usage (last 24h) [click: last 7d] --",
        )

    def test_header_window_idx_2(self):
        host = self._host_with_usage(window_idx=2)
        self.assertEqual(
            host._hdr_otel_usage.title,
            "-- OTel Usage (last 7d) [click: last 30d] --",
        )

    def test_header_window_idx_3_wraps_to_0(self):
        """Last window's next label wraps back to the first window."""
        host = self._host_with_usage(window_idx=3)
        self.assertIn("last 30d", host._hdr_otel_usage.title)
        self.assertIn("last 1h", host._hdr_otel_usage.title)

    def test_cost_suffix_present_when_not_7d_window(self):
        """Cost row shows (7d: $N.NN) when the current window is not 7d."""
        host = self._host_with_usage(window_idx=0, cost_24h=1.23, cost_7d=9.87)
        self.assertEqual(
            host._otel_usage_rows[0].title,
            "  Cost: $1.23  (7d: $9.87)",
        )

    def test_cost_suffix_absent_when_7d_window(self):
        """The (7d: ...) suffix is omitted when the current window is already 7d."""
        host = self._host_with_usage(window_idx=2)  # "7d"
        self.assertEqual(host._otel_usage_rows[0].title, "  Cost: $0.00")

    def test_active_hours_row(self):
        host = self._host_with_usage(active_hours_24h=2.5)
        self.assertEqual(host._otel_usage_rows[1].title, "  Active: 2.5h")

    def test_active_hours_zero(self):
        host = self._host_with_usage()
        self.assertEqual(host._otel_usage_rows[1].title, "  Active: 0.0h")

    def test_token_math_millions_and_thousands(self):
        host = self._host_with_usage(
            total_tokens_24h=3_000_000,
            input_tokens_24h=500_000,
            output_tokens_24h=200_000,
        )
        self.assertEqual(
            host._otel_usage_rows[2].title,
            "  Tokens: 3M  in:500k  out:200k",
        )

    def test_token_math_zero(self):
        host = self._host_with_usage()
        self.assertEqual(
            host._otel_usage_rows[2].title,
            "  Tokens: 0M  in:0k  out:0k",
        )

    def test_model_cost_breakdown_top_2(self):
        host = self._host_with_usage(
            model_cost_breakdown=[
                ("claude.claude-3-5-sonnet-20241022", 0.85),
                ("claude.claude-3-haiku-20240307", 0.38),
            ]
        )
        self.assertEqual(
            host._otel_usage_rows[3].title,
            "  Models: claude-3-5-sonnet-20241022 $0.85, claude-3-haiku-20240307 $0.38",
        )

    def test_model_cost_breakdown_empty(self):
        host = self._host_with_usage(model_cost_breakdown=[])
        self.assertEqual(host._otel_usage_rows[3].title, "  Models: ")


class TestUpdateOtelSectionsAOtelModels(unittest.TestCase):
    """otel_models section: row formatting, truncation, zero-fill, no-dot name."""

    def _host_with_models(self, model_rows):
        host = _make_host()
        host._update_otel_sections_a(
            _avail(otel_models=OtelModels(model_rows=model_rows)),
            {"otel_models": {"enabled": True}},
        )
        return host

    def test_header_set(self):
        host = self._host_with_models([("a.model-x", 1.0, 1_000_000)])
        self.assertEqual(host._hdr_otel_models.title, "-- OTel Models --")

    def test_two_models_fills_first_two_slots_clears_rest(self):
        host = self._host_with_models([
            ("claude.claude-3-5-sonnet-20241022", 1.50, 2_000_000),
            ("anthropic.claude-3-haiku-20240307", 0.25, 500_000),
        ])
        self.assertEqual(
            host._otel_model_rows[0].title,
            "  claude-3-5-sonnet-20241022  $1.50  2000k tok",
        )
        self.assertEqual(
            host._otel_model_rows[1].title,
            "  claude-3-haiku-20240307  $0.25  500k tok",
        )
        self.assertEqual(host._otel_model_rows[2].title, "")
        self.assertEqual(host._otel_model_rows[3].title, "")

    def test_more_than_four_models_truncated_to_four(self):
        rows = [(f"a.model-{i}", float(i), i * 100_000) for i in range(1, 6)]
        host = self._host_with_models(rows)
        # Rows 0-3 populated, row 4 does not exist on the mixin
        for i in range(4):
            self.assertNotEqual(host._otel_model_rows[i].title, "")

    def test_model_name_without_dot_used_as_is(self):
        host = self._host_with_models([("opus", 2.00, 1_000_000)])
        self.assertEqual(host._otel_model_rows[0].title, "  opus  $2.00  1000k tok")
        self.assertEqual(host._otel_model_rows[1].title, "")

    def test_disabled_otel_models_leaves_header_unchanged(self):
        host = _make_host()
        host._update_otel_sections_a(
            _avail(otel_models=OtelModels(model_rows=[("a.b", 1.0, 1_000)])),
            {"otel_models": {"enabled": False}},
        )
        self.assertEqual(host._hdr_otel_models.title, "SENTINEL")


class TestUpdateOtelSectionsAOtelMeta(unittest.TestCase):
    """otel_meta section: cost ratios, cache hit rate, token count."""

    def _host_with_meta(self, **kwargs):
        defaults = dict(
            cost_per_active_hour=1.50,
            cost_per_loc_added=0.0012,
            cost_per_commit=2.75,
            cache_hit_rate_pct=68.0,
            total_tokens_24h=2_000_000,
        )
        defaults.update(kwargs)
        ms = MetaStats(**defaults)
        host = _make_host()
        host._update_otel_sections_a(
            _avail(meta_stats=ms),
            {"otel_meta": {"enabled": True}},
        )
        return host

    def test_header_set(self):
        self.assertEqual(self._host_with_meta()._hdr_otel_meta.title, "-- Meta --")

    def test_cost_per_active_hour(self):
        host = self._host_with_meta(cost_per_active_hour=1.50)
        self.assertEqual(host._otel_meta_rows[0].title, "  $1.50/hr active")

    def test_cost_per_loc_and_commit(self):
        host = self._host_with_meta(cost_per_loc_added=0.0012, cost_per_commit=2.75)
        self.assertEqual(
            host._otel_meta_rows[1].title,
            "  $0.0012/line  $2.75/commit",
        )

    def test_cache_hit_rate(self):
        host = self._host_with_meta(cache_hit_rate_pct=68.0)
        self.assertEqual(host._otel_meta_rows[2].title, "  Cache hit: 68%")

    def test_total_tokens_millions(self):
        host = self._host_with_meta(total_tokens_24h=2_000_000)
        self.assertEqual(host._otel_meta_rows[3].title, "  2M tokens today")

    def test_disabled_leaves_header_unchanged(self):
        host = _make_host()
        host._update_otel_sections_a(
            _avail(),
            {"otel_meta": {"enabled": False}},
        )
        self.assertEqual(host._hdr_otel_meta.title, "SENTINEL")


class TestUpdateOtelSectionsAOtelHooks(unittest.TestCase):
    """otel_hooks section: fired count, latency, top hooks."""

    def _host_with_hooks(self, **kwargs):
        defaults = dict(
            hooks_fired_today=25,
            avg_hook_latency_ms=42.7,
            blocking_count=3,
            error_count=1,
            hook_names=["pre-commit", "post-tool"],
        )
        defaults.update(kwargs)
        hk = HookHealth(**defaults)
        host = _make_host()
        host._update_otel_sections_a(
            _avail(hook_health=hk),
            {"otel_hooks": {"enabled": True}},
        )
        return host

    def test_header_set(self):
        self.assertEqual(self._host_with_hooks()._hdr_hooks.title, "-- Hook Health --")

    def test_fired_blocking_errors(self):
        host = self._host_with_hooks(hooks_fired_today=25, blocking_count=3, error_count=1)
        self.assertEqual(
            host._hook_rows[0].title,
            "  Fired: 25  Blocking: 3  Errors: 1",
        )

    def test_avg_latency(self):
        host = self._host_with_hooks(avg_hook_latency_ms=42.7)
        self.assertEqual(host._hook_rows[1].title, "  Avg latency: 43ms")

    def test_top_hooks_first_two(self):
        host = self._host_with_hooks(hook_names=["pre-commit", "post-tool", "ignored"])
        self.assertEqual(host._hook_rows[2].title, "  Top hooks: pre-commit, post-tool")

    def test_row_3_always_empty(self):
        self.assertEqual(self._host_with_hooks()._hook_rows[3].title, "")

    def test_disabled_leaves_header_unchanged(self):
        host = _make_host()
        host._update_otel_sections_a(
            _avail(),
            {"otel_hooks": {"enabled": False}},
        )
        self.assertEqual(host._hdr_hooks.title, "SENTINEL")


class TestUpdateOtelSectionsBUnavailable(unittest.TestCase):
    """_update_otel_sections_b returns early when data is unavailable."""

    def test_unavailable_leaves_headers_unchanged(self):
        host = _make_host()
        host._update_otel_sections_b(_unavailable(), {"otel_tools": {"enabled": True}})
        self.assertEqual(host._hdr_tools.title, "SENTINEL")


class TestUpdateOtelSectionsBTools(unittest.TestCase):
    """otel_tools section: row formatting."""

    def _host_with_tools(self, **kwargs):
        defaults = dict(
            tool_calls_today=42, accept_rate_pct=85.3,
            top_tools=[("Bash", 20), ("Read", 15)],
            tool_error_count=3, bash_error_rate_pct=7.1,
            avg_input_bytes=1234.5, avg_output_bytes=2345.6,
        )
        defaults.update(kwargs)
        ta = ToolActivity(**defaults)
        host = _make_host()
        host._update_otel_sections_b(
            _avail(tool_activity=ta),
            {"otel_tools": {"enabled": True}},
        )
        return host

    def test_header_set(self):
        self.assertEqual(self._host_with_tools()._hdr_tools.title, "-- Tool Activity --")

    def test_calls_and_accept_rate(self):
        host = self._host_with_tools(tool_calls_today=42, accept_rate_pct=85.3)
        self.assertEqual(host._tool_rows[0].title, "  Calls: 42  Accept: 85%")

    def test_top_tools(self):
        host = self._host_with_tools(top_tools=[("Bash", 20), ("Read", 15)])
        self.assertEqual(host._tool_rows[1].title, "  Top tools: Bash, Read")

    def test_bash_error_rate(self):
        host = self._host_with_tools(bash_error_rate_pct=7.1, tool_error_count=3)
        self.assertEqual(host._tool_rows[2].title, "  Bash err rate: 7%  (3 total errors)")

    def test_avg_bytes(self):
        host = self._host_with_tools(avg_input_bytes=1234.5, avg_output_bytes=2345.6)
        self.assertEqual(host._tool_rows[3].title, "  Avg in: 1234B  out: 2346B")

    def test_row_4_always_empty(self):
        self.assertEqual(self._host_with_tools()._tool_rows[4].title, "")

    def test_disabled_leaves_header_unchanged(self):
        host = _make_host()
        host._update_otel_sections_b(
            _avail(),
            {"otel_tools": {"enabled": False}},
        )
        self.assertEqual(host._hdr_tools.title, "SENTINEL")


class TestUpdateOtelSectionsBCode(unittest.TestCase):
    """otel_code section: row formatting."""

    def _host_with_code(self, **kwargs):
        defaults = dict(
            lines_added_today=100, lines_removed_today=40,
            top_languages=[("Python", 50), ("YAML", 20), ("Shell", 5)],
            commits_today=3,
            compaction_count=1,
            tokens_saved_by_compaction=5000,
        )
        defaults.update(kwargs)
        ci = CodeImpact(**defaults)
        host = _make_host()
        host._update_otel_sections_b(
            _avail(code_impact=ci),
            {"otel_code": {"enabled": True}},
        )
        return host

    def test_header_set(self):
        self.assertEqual(self._host_with_code()._hdr_code.title, "-- Code Impact --")

    def test_lines_and_commits(self):
        host = self._host_with_code(lines_added_today=100, lines_removed_today=40, commits_today=3)
        self.assertEqual(host._code_rows[0].title, "  Lines: +100 / -40  Commits: 3")

    def test_languages_top_3(self):
        host = self._host_with_code(
            top_languages=[("Python", 50), ("YAML", 20), ("Shell", 5)]
        )
        self.assertEqual(host._code_rows[1].title, "  Languages: Python \xd750, YAML \xd720, Shell \xd75")

    def test_compaction_count(self):
        host = self._host_with_code(compaction_count=2)
        self.assertEqual(host._code_rows[2].title, "  Compactions: 2")

    def test_tokens_saved(self):
        host = self._host_with_code(tokens_saved_by_compaction=5000)
        self.assertEqual(host._code_rows[3].title, "  Tokens saved: 5,000")

    def test_row_4_always_empty(self):
        self.assertEqual(self._host_with_code()._code_rows[4].title, "")


class TestUpdateOtelSectionsBSkills(unittest.TestCase):
    """otel_skills section: top skills and invocation count."""

    def _host_with_skills(self, top_skills, skills_invoked_today):
        sk = Skills(top_skills=top_skills, skills_invoked_today=skills_invoked_today)
        host = _make_host()
        host._update_otel_sections_b(
            _avail(skills=sk),
            {"otel_skills": {"enabled": True}},
        )
        return host

    def test_header_set(self):
        host = self._host_with_skills([("decompose", 5)], 5)
        self.assertEqual(host._hdr_skills.title, "-- Skills --")

    def test_top_skills_formatted(self):
        host = self._host_with_skills([("decompose", 5), ("code-review", 3)], 8)
        self.assertEqual(host._skill_rows[0].title, "  Today: decompose \xd75, code-review \xd73")

    def test_total_invocations(self):
        host = self._host_with_skills([("decompose", 5)], 12)
        self.assertEqual(host._skill_rows[1].title, "  Total invocations: 12")

    def test_empty_skills(self):
        host = self._host_with_skills([], 0)
        self.assertEqual(host._skill_rows[0].title, "  Today: ")
        self.assertEqual(host._skill_rows[1].title, "  Total invocations: 0")


class TestUpdateOtelSectionsBSessionPatterns(unittest.TestCase):
    """otel_sessions section: model mix, agent call pct, effort mix."""

    def _host_with_sessions(self, **kwargs):
        defaults = dict(
            prompts_today=25,
            model_mix=[("claude-sonnet-4-6", 15), ("claude-haiku-20240307", 10)],
            agent_call_pct=42.0,
            effort_mix={"high": 5, "medium": 8, "low": 0},
        )
        defaults.update(kwargs)
        sp = SessionPatterns(**defaults)
        host = _make_host()
        host._update_otel_sections_b(
            _avail(session_patterns=sp),
            {"otel_sessions": {"enabled": True}},
        )
        return host

    def test_header_set(self):
        self.assertEqual(self._host_with_sessions()._hdr_session_patterns.title, "-- Session Patterns --")

    def test_model_mix_uses_second_dash_segment(self):
        host = self._host_with_sessions(
            model_mix=[("claude-sonnet-4-6", 15), ("claude-haiku-20240307", 10)]
        )
        self.assertEqual(
            host._session_pattern_rows[0].title,
            "  Models: sonnet \xd715, haiku \xd710",
        )

    def test_model_mix_no_dash_uses_full_name(self):
        host = self._host_with_sessions(model_mix=[("opus", 5)])
        self.assertIn("opus", host._session_pattern_rows[0].title)

    def test_agent_call_pct_and_prompts(self):
        host = self._host_with_sessions(agent_call_pct=42.0, prompts_today=25)
        self.assertEqual(
            host._session_pattern_rows[1].title,
            "  Agent calls: 42%  Prompts: 25",
        )

    def test_effort_mix_filters_zeros(self):
        """Zero-count effort levels are omitted from the row."""
        host = self._host_with_sessions(effort_mix={"high": 5, "medium": 8, "low": 0})
        self.assertEqual(
            host._session_pattern_rows[2].title,
            "  Effort: high:5, medium:8",
        )

    def test_effort_mix_all_zero_yields_empty_effort(self):
        host = self._host_with_sessions(effort_mix={"high": 0, "medium": 0, "low": 0})
        self.assertEqual(host._session_pattern_rows[2].title, "  Effort: ")


class TestUpdateOtelSectionsDelegates(unittest.TestCase):
    """_update_otel_sections calls both _a and _b."""

    def test_calls_both_a_and_b(self):
        host = _make_host()
        s = {
            "otel_usage": {"enabled": True},
            "otel_tools": {"enabled": True},
        }
        ta = ToolActivity(
            tool_calls_today=10, accept_rate_pct=100.0,
            top_tools=[], tool_error_count=0, bash_error_rate_pct=0.0,
            avg_input_bytes=0.0, avg_output_bytes=0.0,
        )
        host._update_otel_sections(_avail(tool_activity=ta), s)
        self.assertIn("OTel Usage", host._hdr_otel_usage.title)
        self.assertEqual(host._hdr_tools.title, "-- Tool Activity --")


if __name__ == "__main__":
    unittest.main()
