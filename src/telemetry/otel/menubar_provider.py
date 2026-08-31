"""OtelMenubarProvider — compute display-ready metrics from OTLP JSONL files.

Reads all rotation files (metrics*.jsonl, events*.jsonl) within the requested
time window, skipping files whose mtime predates the cutoff to keep I/O bounded.
Returns frozen dataclasses ready for menubar rendering.

Dataclasses and zero-constructors live in menubar_dataclasses.py.
Parsing/accumulation helpers and constants live in menubar_parsers.py.
"""

from __future__ import annotations

import collections
import time

from core.date_utils import now_utc

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
)
from telemetry.otel.menubar_parsers import (
    _COLLECTOR_STALE_SECS,
    _METRIC_COST,
    _METRIC_TOKEN_USAGE,
    _WINDOW_7D_SECS,
    _WINDOW_SECS,
    _accumulate_compaction_events,
    _accumulate_cost_metric,
    _accumulate_datapoint,
    _accumulate_loc_metrics,
    _accumulate_token_metric,
    _iter_log_records,
    _iter_metric_datapoints,
    _parse_attrs,
    _parse_nano_ts,
    _process_tool_result_event,
    _read_rotated_jsonl,
    _safe_float,
    _safe_int,
    _top_n,
    _trunc,
)
from telemetry.otel.reader import EVENTS_FILE, METRICS_FILE, OTLPDataDir

__all__ = [
    # dataclasses
    "CodeImpact",
    "HookHealth",
    "MetaStats",
    "OtelDisplayData",
    "OtelModels",
    "OtelUsage",
    "SessionPatterns",
    "Skills",
    "ToolActivity",
    # provider
    "OtelMenubarProvider",
]


# ── Provider ───────────────────────────────────────────────────────────────────


class OtelMenubarProvider:
    """Compute display-ready metrics from OTLP JSONL files."""

    def __init__(self, data_dir: OTLPDataDir | None = None) -> None:
        self._data_dir = data_dir or OTLPDataDir.from_env()

    def get_display_data(self, window: str = "24h", cutoff: float | None = None) -> OtelDisplayData:
        """Return all display data, or an unavailable sentinel if data is stale/missing.

        Args:
            window: Time window for aggregation. Valid values: "1h", "24h", "7d", "30d".
                    Defaults to "24h". Unknown values fall back to "24h". Ignored when
                    *cutoff* is provided.
            cutoff: Optional Unix timestamp lower bound. When provided, overrides the
                    *window* parameter for the primary aggregation period. The 7d reference
                    cost is always computed from a fixed 7d lookback regardless.
        """
        events_path = self._data_dir.path / EVENTS_FILE
        metrics_path = self._data_dir.path / METRICS_FILE

        if not self._data_dir.path.exists():
            return _unavailable()
        if not events_path.exists() or events_path.stat().st_size == 0:
            return _unavailable()
        now = time.time()
        explicit_cutoff = cutoff is not None
        if cutoff is None:
            cutoff = now - _WINDOW_SECS.get(window, _WINDOW_SECS["24h"])

        age = now - events_path.stat().st_mtime
        if age > _COLLECTOR_STALE_SECS and not explicit_cutoff:
            return _unavailable()
        cutoff_7d = now - _WINDOW_7D_SECS

        raw_events = _read_rotated_jsonl(events_path, cutoff)
        raw_metrics = _read_rotated_jsonl(metrics_path, cutoff_7d)

        events = self._parse_events(raw_events, cutoff)
        metrics = self._parse_metric_datapoints(raw_metrics, cutoff)
        metrics_7d = self._parse_metric_datapoints(raw_metrics, cutoff_7d)

        code_impact = self._compute_code_impact(events, metrics)
        otel_usage = self._compute_otel_usage(metrics, metrics_7d)
        otel_models = self._compute_otel_models(metrics)
        meta_stats = self._compute_meta_stats(otel_usage, code_impact)
        hook_health = self._compute_hook_health(events)
        tool_activity = self._compute_tool_activity(events)
        skills = self._compute_skills(events)
        session_patterns = self._compute_session_patterns(events)

        return OtelDisplayData(
            available=True,
            collected_at=now_utc(),
            otel_usage=otel_usage,
            otel_models=otel_models,
            meta_stats=meta_stats,
            hook_health=hook_health,
            tool_activity=tool_activity,
            code_impact=code_impact,
            skills=skills,
            session_patterns=session_patterns,
        )

    def _parse_events(
        self, raw_lines: list[dict[str, object]], cutoff: float
    ) -> list[tuple[str, float, dict[str, object]]]:
        """Parse raw event JSONL dicts into (event_type, ts_secs, attrs) triples."""
        out: list[tuple[str, float, dict[str, object]]] = []
        for log_record in _iter_log_records(raw_lines):
            ts_nano = _parse_nano_ts(log_record.get("timeUnixNano", 0))
            ts = ts_nano / 1e9
            if ts < cutoff:
                continue
            body = log_record.get("body", "")
            if isinstance(body, dict):
                event_type = body.get("stringValue", "")
            else:
                event_type = str(body)
            raw_attrs = log_record.get("attributes", [])
            attrs = _parse_attrs(raw_attrs if isinstance(raw_attrs, list) else [])
            out.append((event_type, ts, attrs))
        return out

    def _parse_metric_datapoints(
        self, raw_lines: list[dict[str, object]], cutoff: float
    ) -> list[tuple[str, float, dict[str, object]]]:
        """Parse raw metrics JSONL dicts into (metric_name, value, attrs) triples."""
        out: list[tuple[str, float, dict[str, object]]] = []
        for raw in raw_lines:
            for name, dp in _iter_metric_datapoints(raw):
                _accumulate_datapoint(dp, name, cutoff, out)
        return out

    def _compute_otel_usage(
        self,
        metrics_24h: list[tuple[str, float, dict[str, object]]],
        metrics_7d: list[tuple[str, float, dict[str, object]]],
    ) -> OtelUsage:
        token_counters: dict[str, int] = {"input": 0, "output": 0, "cacheRead": 0, "cacheCreation": 0}
        cost_holder = [0.0]
        active_secs_24h = 0.0
        model_cost: dict[str, float] = collections.defaultdict(float)

        for name, value, attrs in metrics_24h:
            if name == _METRIC_TOKEN_USAGE:
                _accumulate_token_metric(str(attrs.get("type") or ""), _safe_int(value, 0), token_counters)
            elif name == _METRIC_COST:
                _accumulate_cost_metric(value, attrs, cost_holder, model_cost)
            elif name == "claude_code.active_time.total":
                active_secs_24h += _safe_float(value, 0.0)

        cost_7d = sum(value for name, value, _ in metrics_7d if name == _METRIC_COST)
        total_tokens_24h = sum(token_counters.values())

        return OtelUsage(
            cost_24h=cost_holder[0],
            cost_7d=cost_7d,
            input_tokens_24h=token_counters["input"],
            output_tokens_24h=token_counters["output"],
            cache_read_tokens_24h=token_counters["cacheRead"],
            cache_creation_tokens_24h=token_counters["cacheCreation"],
            total_tokens_24h=total_tokens_24h,
            active_hours_24h=active_secs_24h / 3600.0,
            model_cost_breakdown=_top_n(model_cost, 3),
        )

    def _compute_otel_models(
        self, metrics_24h: list[tuple[str, float, dict[str, object]]]
    ) -> OtelModels:
        model_cost: dict[str, float] = collections.defaultdict(float)
        model_tokens: dict[str, int] = collections.defaultdict(int)

        for name, value, attrs in metrics_24h:
            model = _trunc(attrs.get("model", "unknown"))
            if name == _METRIC_COST:
                model_cost[model] += _safe_float(value, 0.0)
            elif name == _METRIC_TOKEN_USAGE:
                model_tokens[model] += _safe_int(value, 0)

        all_models = set(model_cost) | set(model_tokens)
        rows = [(m, model_cost.get(m, 0.0), model_tokens.get(m, 0)) for m in all_models]
        rows.sort(key=lambda r: r[1], reverse=True)

        return OtelModels(model_rows=rows[:4])

    def _compute_meta_stats(self, usage: OtelUsage, code_impact: CodeImpact) -> MetaStats:
        cost_per_active_hour = (
            usage.cost_24h / usage.active_hours_24h if usage.active_hours_24h > 0 else 0.0
        )
        cost_per_loc_added = (
            usage.cost_24h / code_impact.lines_added_today if code_impact.lines_added_today > 0 else 0.0
        )
        cost_per_commit = (
            usage.cost_24h / code_impact.commits_today if code_impact.commits_today > 0 else 0.0
        )
        cache_denominator = usage.cache_read_tokens_24h + usage.cache_creation_tokens_24h
        cache_hit_rate_pct = (
            100.0 * usage.cache_read_tokens_24h / cache_denominator if cache_denominator > 0 else 0.0
        )
        return MetaStats(
            cost_per_active_hour=cost_per_active_hour,
            cost_per_loc_added=cost_per_loc_added,
            cost_per_commit=cost_per_commit,
            cache_hit_rate_pct=cache_hit_rate_pct,
            total_tokens_24h=usage.total_tokens_24h,
        )

    def _compute_hook_health(
        self, events_24h: list[tuple[str, float, dict[str, object]]]
    ) -> HookHealth:
        hooks_fired = 0
        total_latency_ms = 0.0
        blocking_count = 0
        error_count = 0
        hook_name_counts: dict[str, int] = collections.defaultdict(int)

        for event_type, _ts, attrs in events_24h:
            if event_type != "claude_code.hook_execution_complete":
                continue
            hooks_fired += 1
            total_latency_ms += _safe_float(attrs.get("total_duration_ms", 0), 0.0)
            blocking_count += _safe_int(attrs.get("num_blocking", 0), 0)
            error_count += _safe_int(attrs.get("num_non_blocking_error", 0), 0)
            hook_name_counts[_trunc(attrs.get("hook_name", "unknown"))] += 1

        avg_latency = total_latency_ms / hooks_fired if hooks_fired > 0 else 0.0
        top_hooks = _top_n(hook_name_counts, 3)

        return HookHealth(
            hooks_fired_today=hooks_fired,
            avg_hook_latency_ms=avg_latency,
            blocking_count=blocking_count,
            error_count=error_count,
            hook_names=[name for name, _ in top_hooks],
        )

    def _compute_tool_activity(
        self, events_24h: list[tuple[str, float, dict[str, object]]]
    ) -> ToolActivity:
        tool_decision_count = 0
        accepted = 0
        tool_counts: dict[str, int] = collections.defaultdict(int)
        tool_result_count = 0
        state: dict[str, object] = {
            "tool_errors": 0,
            "bash_calls": 0,
            "bash_errors": 0,
            "total_input_bytes": 0.0,
            "total_output_bytes": 0.0,
        }

        for event_type, _ts, attrs in events_24h:
            if event_type == "claude_code.tool_decision":
                tool_decision_count += 1
                tool_counts[_trunc(attrs.get("tool_name", "unknown"))] += 1
                if str(attrs.get("decision") or "").lower() == "accept":
                    accepted += 1
            elif event_type == "claude_code.tool_result":
                tool_result_count += 1
                _process_tool_result_event(attrs, state)

        bash_calls = _safe_int(state["bash_calls"], 0)
        bash_errors = _safe_int(state["bash_errors"], 0)
        total_input = _safe_float(state["total_input_bytes"], 0.0)
        total_output = _safe_float(state["total_output_bytes"], 0.0)
        accept_rate = 100.0 * accepted / tool_decision_count if tool_decision_count > 0 else 0.0
        bash_error_rate = 100.0 * bash_errors / bash_calls if bash_calls > 0 else 0.0
        avg_input = total_input / tool_result_count if tool_result_count > 0 else 0.0
        avg_output = total_output / tool_result_count if tool_result_count > 0 else 0.0

        return ToolActivity(
            tool_calls_today=tool_result_count,
            accept_rate_pct=accept_rate,
            top_tools=_top_n(tool_counts, 4),
            tool_error_count=_safe_int(state["tool_errors"], 0),
            bash_error_rate_pct=bash_error_rate,
            avg_input_bytes=avg_input,
            avg_output_bytes=avg_output,
        )

    def _compute_code_impact(
        self,
        events_24h: list[tuple[str, float, dict[str, object]]],
        metrics_24h: list[tuple[str, float, dict[str, object]]],
    ) -> CodeImpact:
        lang_counts: dict[str, int] = collections.defaultdict(int)
        counters: dict[str, object] = {
            "lines_added": 0,
            "lines_removed": 0,
            "commits_today": 0,
            "compaction_count": 0,
            "tokens_saved": 0,
            "lang_counts": lang_counts,
        }
        _accumulate_loc_metrics(metrics_24h, counters)
        _accumulate_compaction_events(events_24h, counters)

        return CodeImpact(
            lines_added_today=_safe_int(counters["lines_added"], 0),
            lines_removed_today=_safe_int(counters["lines_removed"], 0),
            top_languages=_top_n(lang_counts, 3),
            commits_today=_safe_int(counters["commits_today"], 0),
            compaction_count=_safe_int(counters["compaction_count"], 0),
            tokens_saved_by_compaction=_safe_int(counters["tokens_saved"], 0),
        )

    def _compute_skills(
        self, events_24h: list[tuple[str, float, dict[str, object]]]
    ) -> Skills:
        skill_counts: dict[str, int] = collections.defaultdict(int)
        for event_type, _ts, attrs in events_24h:
            if event_type == "claude_code.skill_activated":
                skill_counts[_trunc(attrs.get("skill.name", "unknown"))] += 1
        total = sum(skill_counts.values())
        return Skills(top_skills=_top_n(skill_counts, 4), skills_invoked_today=total)

    def _compute_session_patterns(
        self, events_24h: list[tuple[str, float, dict[str, object]]]
    ) -> SessionPatterns:
        prompts_today = 0
        model_counts: dict[str, int] = collections.defaultdict(int)
        api_calls = 0
        agent_calls = 0
        effort_counts: dict[str, int] = collections.defaultdict(int)

        for event_type, _ts, attrs in events_24h:
            if event_type == "claude_code.user_prompt":
                prompts_today += 1
            elif event_type == "claude_code.api_request":
                api_calls += 1
                model_counts[_trunc(attrs.get("model", "unknown"))] += 1
                if str(attrs.get("query_source") or "").startswith("agent:"):
                    agent_calls += 1
                effort_counts[_trunc(attrs.get("effort", "")) or "unknown"] += 1

        agent_call_pct = 100.0 * agent_calls / api_calls if api_calls > 0 else 0.0

        return SessionPatterns(
            prompts_today=prompts_today,
            model_mix=_top_n(model_counts, 3),
            agent_call_pct=agent_call_pct,
            effort_mix=dict(effort_counts),
        )
