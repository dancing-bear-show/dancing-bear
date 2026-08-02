"""OTel sections mixin extracted from _menubar_app.py."""
from __future__ import annotations

from telemetry.otel.menubar_provider import OtelDisplayData


class OtelSectionsMixin:
    """Methods for rendering OTel menu sections into the menubar."""

    def _clear_otel_headers(self) -> None:
        for hdr in (
            self._hdr_otel_usage, self._hdr_otel_models, self._hdr_otel_meta,  # type: ignore[attr-defined]
            self._hdr_hooks, self._hdr_tools, self._hdr_code,  # type: ignore[attr-defined]
            self._hdr_skills, self._hdr_session_patterns,  # type: ignore[attr-defined]
        ):
            hdr.title = ""

    def _update_otel_sections_a(self, otel_data: OtelDisplayData, s: dict) -> None:
        # Late import avoids circular: _menubar_app imports this module.
        from telemetry._menubar_app import _OTEL_WINDOWS
        if not otel_data.available:
            self._clear_otel_headers()
            return
        if s.get("otel_usage", {}).get("enabled", False):
            ou = otel_data.otel_usage
            otel_label, _ = _OTEL_WINDOWS[self._otel_window_idx]  # type: ignore[attr-defined]
            otel_next_label, _ = _OTEL_WINDOWS[(self._otel_window_idx + 1) % len(_OTEL_WINDOWS)]  # type: ignore[attr-defined]
            self._hdr_otel_usage.title = f"-- OTel Usage ({otel_label}) [click: {otel_next_label}] --"  # type: ignore[attr-defined]
            _, current_otel_window = _OTEL_WINDOWS[self._otel_window_idx]  # type: ignore[attr-defined]
            cost_suffix = "" if current_otel_window == "7d" else f"  (7d: ${ou.cost_7d:.2f})"
            self._otel_usage_rows[0].title = f"  Cost: ${ou.cost_24h:.2f}{cost_suffix}"  # type: ignore[attr-defined]
            self._otel_usage_rows[1].title = f"  Active: {ou.active_hours_24h:.1f}h"  # type: ignore[attr-defined]
            self._otel_usage_rows[2].title = f"  Tokens: {ou.total_tokens_24h // 1_000_000}M  in:{ou.input_tokens_24h // 1000}k  out:{ou.output_tokens_24h // 1000}k"  # type: ignore[attr-defined]
            top_model_str = ", ".join(f"{mdl.split('.')[-1]} ${cost:.2f}" for mdl, cost in ou.model_cost_breakdown[:2])
            self._otel_usage_rows[3].title = "  Models: " + top_model_str  # type: ignore[attr-defined]
        if s.get("otel_models", {}).get("enabled", False):
            om = otel_data.otel_models
            self._hdr_otel_models.title = "-- OTel Models --"  # type: ignore[attr-defined]
            for idx, (mdl, cost, toks) in enumerate(om.model_rows[:4]):
                short = mdl.split(".")[-1] if "." in mdl else mdl
                self._otel_model_rows[idx].title = f"  {short}  ${cost:.2f}  {toks // 1000}k tok"  # type: ignore[attr-defined]
            for idx in range(len(om.model_rows), 4):
                self._otel_model_rows[idx].title = ""  # type: ignore[attr-defined]
        if s.get("otel_meta", {}).get("enabled", False):
            ms = otel_data.meta_stats
            self._hdr_otel_meta.title = "-- Meta --"  # type: ignore[attr-defined]
            self._otel_meta_rows[0].title = f"  ${ms.cost_per_active_hour:.2f}/hr active"  # type: ignore[attr-defined]
            self._otel_meta_rows[1].title = f"  ${ms.cost_per_loc_added:.4f}/line  ${ms.cost_per_commit:.2f}/commit"  # type: ignore[attr-defined]
            self._otel_meta_rows[2].title = f"  Cache hit: {ms.cache_hit_rate_pct:.0f}%"  # type: ignore[attr-defined]
            self._otel_meta_rows[3].title = f"  {ms.total_tokens_24h // 1_000_000}M tokens today"  # type: ignore[attr-defined]
        if s.get("otel_hooks", {}).get("enabled", False):
            hk = otel_data.hook_health
            self._hdr_hooks.title = "-- Hook Health --"  # type: ignore[attr-defined]
            self._hook_rows[0].title = f"  Fired: {hk.hooks_fired_today}  Blocking: {hk.blocking_count}  Errors: {hk.error_count}"  # type: ignore[attr-defined]
            self._hook_rows[1].title = f"  Avg latency: {hk.avg_hook_latency_ms:.0f}ms"  # type: ignore[attr-defined]
            top_hooks = ", ".join(hk.hook_names[:2])
            self._hook_rows[2].title = "  Top hooks: " + top_hooks  # type: ignore[attr-defined]
            self._hook_rows[3].title = ""  # type: ignore[attr-defined]

    def _update_otel_sections_b(self, otel_data: OtelDisplayData, s: dict) -> None:
        if not otel_data.available:
            return
        if s.get("otel_tools", {}).get("enabled", False):
            ta = otel_data.tool_activity
            self._hdr_tools.title = "-- Tool Activity --"  # type: ignore[attr-defined]
            self._tool_rows[0].title = f"  Calls: {ta.tool_calls_today}  Accept: {ta.accept_rate_pct:.0f}%"  # type: ignore[attr-defined]
            top2 = ", ".join(t for t, _ in ta.top_tools[:2])
            self._tool_rows[1].title = "  Top tools: " + top2  # type: ignore[attr-defined]
            self._tool_rows[2].title = f"  Bash err rate: {ta.bash_error_rate_pct:.0f}%  ({ta.tool_error_count} total errors)"  # type: ignore[attr-defined]
            self._tool_rows[3].title = f"  Avg in: {ta.avg_input_bytes:.0f}B  out: {ta.avg_output_bytes:.0f}B"  # type: ignore[attr-defined]
            self._tool_rows[4].title = ""  # type: ignore[attr-defined]
        if s.get("otel_code", {}).get("enabled", False):
            ci = otel_data.code_impact
            self._hdr_code.title = "-- Code Impact --"  # type: ignore[attr-defined]
            self._code_rows[0].title = f"  Lines: +{ci.lines_added_today:,} / -{ci.lines_removed_today:,}  Commits: {ci.commits_today}"  # type: ignore[attr-defined]
            langs = ", ".join(f"{lang} \xd7{cnt}" for lang, cnt in ci.top_languages[:3])
            self._code_rows[1].title = "  Languages: " + langs  # type: ignore[attr-defined]
            self._code_rows[2].title = f"  Compactions: {ci.compaction_count}"  # type: ignore[attr-defined]
            self._code_rows[3].title = f"  Tokens saved: {ci.tokens_saved_by_compaction:,}"  # type: ignore[attr-defined]
            self._code_rows[4].title = ""  # type: ignore[attr-defined]
        if s.get("otel_skills", {}).get("enabled", False):
            sk = otel_data.skills
            self._hdr_skills.title = "-- Skills --"  # type: ignore[attr-defined]
            top_sk = ", ".join(f"{name} \xd7{cnt}" for name, cnt in sk.top_skills[:3])
            self._skill_rows[0].title = "  Today: " + top_sk  # type: ignore[attr-defined]
            self._skill_rows[1].title = f"  Total invocations: {sk.skills_invoked_today}"  # type: ignore[attr-defined]
        if s.get("otel_sessions", {}).get("enabled", False):
            sp = otel_data.session_patterns
            self._hdr_session_patterns.title = "-- Session Patterns --"  # type: ignore[attr-defined]
            mix = ", ".join(f"{mdl.split('-')[1] if '-' in mdl else mdl} \xd7{cnt}" for mdl, cnt in sp.model_mix[:2])
            self._session_pattern_rows[0].title = "  Models: " + mix  # type: ignore[attr-defined]
            self._session_pattern_rows[1].title = f"  Agent calls: {sp.agent_call_pct:.0f}%  Prompts: {sp.prompts_today}"  # type: ignore[attr-defined]
            effort = ", ".join(f"{eff}:{cnt}" for eff, cnt in sp.effort_mix.items() if cnt)
            self._session_pattern_rows[2].title = "  Effort: " + effort  # type: ignore[attr-defined]

    def _update_otel_sections(self, otel_data: OtelDisplayData, s: dict) -> None:
        self._update_otel_sections_a(otel_data, s)
        self._update_otel_sections_b(otel_data, s)
