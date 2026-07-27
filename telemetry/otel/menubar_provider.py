"""OtelMenubarProvider — compute display-ready metrics from OTLP JSONL files.

Reads all rotation files (metrics*.jsonl, events*.jsonl) within the requested
time window, skipping files whose mtime predates the cutoff to keep I/O bounded.
Returns frozen dataclasses ready for menubar rendering.
"""

from __future__ import annotations

import collections
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.fileutil import find_rotated_files, iter_jsonl_file
from telemetry.otel._constants import METRIC_COST_USAGE
from telemetry.otel.reader import EVENTS_FILE, METRICS_FILE, OTLPDataDir

# ── Constants ──────────────────────────────────────────────────────────────────

_COLLECTOR_STALE_SECS = 600
_DEFAULT_TAIL_LINES = 5000
_TAIL_LINES_BY_WINDOW: dict[str, int] = {
    "1h": 500,
    "24h": 5000,
    "7d": 35_000,
    "30d": 150_000,
}
_WINDOW_24H_SECS = 86400
_WINDOW_7D_SECS = 604_800
_WINDOW_SECS: dict[str, int] = {
    "1h": 3600,
    "24h": 86400,
    "7d": 604_800,
    "30d": 2_592_000,
}
_MAX_ATTR_LEN = 64
_METRIC_COST = METRIC_COST_USAGE
_METRIC_TOKEN_USAGE = "claude_code.token.usage"


# ── Output dataclasses ─────────────────────────────────────────────────────────


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


# ── Internal helpers ───────────────────────────────────────────────────────────


def _read_rotated_jsonl(base_path: Path, cutoff: float) -> list[dict[str, object]]:
    """Read all rotation files for *base_path*, returning records with timestamps >= cutoff.

    Skips any rotated file whose mtime predates ``cutoff`` by more than 1 hour (clock-skew
    grace), since such files can only contain older records.
    """
    result: list[dict[str, object]] = []
    for fpath in find_rotated_files(base_path):
        try:
            if fpath.stat().st_mtime < cutoff - 3600:
                continue
        except OSError:
            continue
        try:
            result.extend(iter_jsonl_file(fpath, tolerant=True))
        except OSError:
            continue
    return result


def _parse_attrs(attr_list: list[dict[str, object]]) -> dict[str, object]:
    """Flatten an OTLP attribute list into {key: value}."""
    out: dict[str, object] = {}
    for attr in attr_list:
        key = attr.get("key", "")
        val = attr.get("value", {})
        if not isinstance(val, dict):
            out[key] = None
            continue
        if "stringValue" in val:
            out[key] = val["stringValue"]
        elif "intValue" in val:
            out[key] = val["intValue"]
        elif "doubleValue" in val:
            out[key] = val["doubleValue"]
        elif "boolValue" in val:
            out[key] = val["boolValue"]
        else:
            out[key] = None
    return out


def _safe_float(v: object) -> float:
    """Coerce v to float, returning 0.0 on failure."""
    if isinstance(v, bool):
        return 0.0
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v: object) -> int:
    """Coerce v to int, returning 0 on failure."""
    if isinstance(v, bool):
        return 0
    try:
        return int(float(v))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


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


def _parse_nano_ts(value: object) -> int:
    """Parse a timeUnixNano field to int, returning 0 on malformed input."""
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return 0


def _trunc(s: object, n: int = _MAX_ATTR_LEN) -> str:
    """Truncate any attribute value to *n* chars to bound memory usage."""
    return str(s)[:n] if s is not None else ""


def _top_n(counts: dict[str, int | float], n: int) -> list[tuple[str, int | float]]:
    """Return the top *n* items from *counts* sorted by value descending."""
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:n]


def _is_event_success(attrs: dict[str, object]) -> bool:
    """Return True unless the *success* attribute is explicitly falsy."""
    v = attrs.get("success", "true")
    return str(v).lower() not in ("false", "0", "no")


def _iter_log_records(raw_objs: list[dict[str, object]]) -> Iterator[dict[str, object]]:
    """Yield every logRecord dict from a list of decoded OTLP resourceLogs objects."""
    for obj in raw_objs:
        for rl in obj.get("resourceLogs", []):
            for sl in rl.get("scopeLogs", []):
                yield from sl.get("logRecords", [])


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


# ── Parsing helpers ────────────────────────────────────────────────────────────


def _accumulate_datapoint(
    dp: dict[str, object],
    name: str,
    cutoff: float,
    out: list[tuple[str, float, dict[str, object]]],
) -> None:
    """Append (name, value, attrs) to *out* if the datapoint timestamp >= cutoff."""
    ts_nano = _parse_nano_ts(dp.get("timeUnixNano", 0))
    if ts_nano / 1e9 < cutoff:
        return
    value = _safe_float(dp.get("asDouble", dp.get("asInt", 0)))
    raw_attrs = dp.get("attributes", [])
    attrs = _parse_attrs(raw_attrs if isinstance(raw_attrs, list) else [])
    out.append((name, value, attrs))


def _accumulate_loc_metrics(
    metrics_24h: list[tuple[str, float, dict[str, object]]],
    counters: dict[str, object],
) -> None:
    """Accumulate LOC/commit/language metrics from metrics_24h into counters."""
    lang_counts: dict[str, int] = counters["lang_counts"]  # type: ignore[assignment]
    for name, value, attrs in metrics_24h:
        if name == "claude_code.lines_of_code.count":
            loc_type = str(attrs.get("type", ""))
            v = _safe_int(value)
            if loc_type == "added":
                counters["lines_added"] = int(counters["lines_added"]) + v  # type: ignore[arg-type]
            elif loc_type == "removed":
                counters["lines_removed"] = int(counters["lines_removed"]) + v  # type: ignore[arg-type]
        elif name == "claude_code.commit.count":
            counters["commits_today"] = int(counters["commits_today"]) + _safe_int(value)  # type: ignore[arg-type]
        elif name == "claude_code.code_edit_tool.decision":
            lang_counts[_trunc(attrs.get("language", "unknown"))] += _safe_int(value)


def _accumulate_compaction_events(
    events_24h: list[tuple[str, float, dict[str, object]]],
    counters: dict[str, object],
) -> None:
    """Accumulate compaction event counts and token savings into counters."""
    for event_type, _ts, attrs in events_24h:
        if event_type == "claude_code.compaction":
            counters["compaction_count"] = int(counters["compaction_count"]) + 1  # type: ignore[arg-type]
            pre = _safe_int(attrs.get("pre_tokens", 0))
            post = _safe_int(attrs.get("post_tokens", 0))
            counters["tokens_saved"] = int(counters["tokens_saved"]) + max(0, pre - post)  # type: ignore[arg-type]


def _accumulate_token_metric(
    token_type: str,
    value: int,
    counters: dict[str, int],
) -> None:
    """Accumulate a single token metric into counters by token_type."""
    if token_type == "input":
        counters["input"] += value
    elif token_type == "output":
        counters["output"] += value
    elif token_type == "cacheRead":
        counters["cacheRead"] += value
    elif token_type == "cacheCreation":
        counters["cacheCreation"] += value


def _process_tool_result_event(
    attrs: dict[str, object],
    state: dict[str, object],
) -> None:
    """Update mutable *state* counters for a single tool_result event."""
    tool_name = _trunc(attrs.get("tool_name", "unknown"))
    is_success = _is_event_success(attrs)
    if not is_success:
        state["tool_errors"] = state["tool_errors"] + 1  # type: ignore[operator]
    if tool_name.lower() == "bash":
        state["bash_calls"] = state["bash_calls"] + 1  # type: ignore[operator]
        if not is_success:
            state["bash_errors"] = state["bash_errors"] + 1  # type: ignore[operator]
    state["total_input_bytes"] = state["total_input_bytes"] + _safe_float(attrs.get("tool_input_size_bytes", 0))  # type: ignore[operator]
    state["total_output_bytes"] = state["total_output_bytes"] + _safe_float(attrs.get("tool_result_size_bytes", 0))  # type: ignore[operator]


def _accumulate_cost_metric(
    value: float,
    attrs: dict[str, object],
    cost_holder: list[float],
    model_cost: dict[str, float],
) -> None:
    """Accumulate a cost metric into cost_holder[0] and model_cost breakdown."""
    cost_holder[0] += _safe_float(value)
    model = _trunc(attrs.get("model", "unknown"))
    model_cost[model] += _safe_float(value)


def _iter_metric_datapoints(
    raw: dict[str, object],
) -> Iterator[tuple[str, dict[str, object]]]:
    """Yield (metric_name, datapoint_dict) pairs from a single raw metrics JSONL record."""
    for rm in raw.get("resourceMetrics", []):
        for sm in rm.get("scopeMetrics", []):
            for metric in sm.get("metrics", []):
                name = metric.get("name", "")
                gauge = metric.get("gauge", {})
                sum_data = metric.get("sum", {})
                data_points = gauge.get("dataPoints") or sum_data.get("dataPoints", [])
                for dp in data_points:
                    yield name, dp


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
            collected_at=datetime.now(tz=timezone.utc),
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
                _accumulate_token_metric(attrs.get("type", ""), _safe_int(value), token_counters)
            elif name == _METRIC_COST:
                _accumulate_cost_metric(value, attrs, cost_holder, model_cost)
            elif name == "claude_code.active_time.total":
                active_secs_24h += _safe_float(value)

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
                model_cost[model] += _safe_float(value)
            elif name == _METRIC_TOKEN_USAGE:
                model_tokens[model] += _safe_int(value)

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
            total_latency_ms += _safe_float(attrs.get("total_duration_ms", 0))
            blocking_count += _safe_int(attrs.get("num_blocking", 0))
            error_count += _safe_int(attrs.get("num_non_blocking_error", 0))
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
                if str(attrs.get("decision", "")).lower() == "accept":
                    accepted += 1
            elif event_type == "claude_code.tool_result":
                tool_result_count += 1
                _process_tool_result_event(attrs, state)

        bash_calls = int(state["bash_calls"])  # type: ignore[arg-type]
        bash_errors = int(state["bash_errors"])  # type: ignore[arg-type]
        total_input = float(state["total_input_bytes"])  # type: ignore[arg-type]
        total_output = float(state["total_output_bytes"])  # type: ignore[arg-type]
        accept_rate = 100.0 * accepted / tool_decision_count if tool_decision_count > 0 else 0.0
        bash_error_rate = 100.0 * bash_errors / bash_calls if bash_calls > 0 else 0.0
        avg_input = total_input / tool_result_count if tool_result_count > 0 else 0.0
        avg_output = total_output / tool_result_count if tool_result_count > 0 else 0.0

        return ToolActivity(
            tool_calls_today=tool_result_count,
            accept_rate_pct=accept_rate,
            top_tools=_top_n(tool_counts, 4),
            tool_error_count=int(state["tool_errors"]),  # type: ignore[arg-type]
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
            lines_added_today=int(counters["lines_added"]),  # type: ignore[arg-type]
            lines_removed_today=int(counters["lines_removed"]),  # type: ignore[arg-type]
            top_languages=_top_n(lang_counts, 3),
            commits_today=int(counters["commits_today"]),  # type: ignore[arg-type]
            compaction_count=int(counters["compaction_count"]),  # type: ignore[arg-type]
            tokens_saved_by_compaction=int(counters["tokens_saved"]),  # type: ignore[arg-type]
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
                if str(attrs.get("query_source", "")).startswith("agent:"):
                    agent_calls += 1
                effort_counts[_trunc(attrs.get("effort", "")) or "unknown"] += 1

        agent_call_pct = 100.0 * agent_calls / api_calls if api_calls > 0 else 0.0

        return SessionPatterns(
            prompts_today=prompts_today,
            model_mix=_top_n(model_counts, 3),
            agent_call_pct=agent_call_pct,
            effort_mix=dict(effort_counts),
        )
