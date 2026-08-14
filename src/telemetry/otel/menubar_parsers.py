"""Parsing/accumulation helpers extracted from menubar_provider.py."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from core.fileutil import find_rotated_files, iter_jsonl_file
from telemetry._menubar_budget import _safe_float, _safe_int
from telemetry.otel._constants import METRIC_COST_USAGE

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
_METRIC_TOKEN_USAGE = "claude_code.token.usage"  # nosec B105 - OTel metric name, not a secret


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
    value = _safe_float(dp.get("asDouble", dp.get("asInt", 0)), 0.0)
    raw_attrs = dp.get("attributes", [])
    attrs = _parse_attrs(raw_attrs if isinstance(raw_attrs, list) else [])
    out.append((name, value, attrs))


def _accumulate_loc_delta(
    value: float, attrs: dict[str, object], counters: dict[str, object]
) -> None:
    """Add a lines_of_code datapoint into lines_added/lines_removed by its type attr."""
    loc_type = str(attrs.get("type", ""))
    v = _safe_int(value, 0)
    if loc_type == "added":
        counters["lines_added"] = int(counters["lines_added"]) + v  # type: ignore[arg-type]
    elif loc_type == "removed":
        counters["lines_removed"] = int(counters["lines_removed"]) + v  # type: ignore[arg-type]


def _accumulate_commit_count(
    value: float, attrs: dict[str, object], counters: dict[str, object]  # noqa: ARG001
) -> None:
    """Add a commit.count datapoint into counters['commits_today']."""
    counters["commits_today"] = int(counters["commits_today"]) + _safe_int(value, 0)  # type: ignore[arg-type]


def _accumulate_language_count(
    value: float, attrs: dict[str, object], counters: dict[str, object]
) -> None:
    """Add a code_edit_tool.decision datapoint into counters['lang_counts']."""
    lang_counts: dict[str, int] = counters["lang_counts"]  # type: ignore[assignment]
    lang_counts[_trunc(attrs.get("language", "unknown"))] += _safe_int(value, 0)


# metric name -> accumulator handler, each taking (value, attrs, counters).
_LOC_METRIC_HANDLERS: dict[
    str, Callable[[float, dict[str, object], dict[str, object]], None]
] = {
    "claude_code.lines_of_code.count": _accumulate_loc_delta,
    "claude_code.commit.count": _accumulate_commit_count,
    "claude_code.code_edit_tool.decision": _accumulate_language_count,
}


def _accumulate_loc_metrics(
    metrics_24h: list[tuple[str, float, dict[str, object]]],
    counters: dict[str, object],
) -> None:
    """Accumulate LOC/commit/language metrics from metrics_24h into counters."""
    for name, value, attrs in metrics_24h:
        handler = _LOC_METRIC_HANDLERS.get(name)
        if handler is not None:
            handler(value, attrs, counters)


def _accumulate_compaction_events(
    events_24h: list[tuple[str, float, dict[str, object]]],
    counters: dict[str, object],
) -> None:
    """Accumulate compaction event counts and token savings into counters."""
    for event_type, _ts, attrs in events_24h:
        if event_type == "claude_code.compaction":
            counters["compaction_count"] = int(counters["compaction_count"]) + 1  # type: ignore[arg-type]
            pre = _safe_int(attrs.get("pre_tokens", 0), 0)
            post = _safe_int(attrs.get("post_tokens", 0), 0)
            counters["tokens_saved"] = int(counters["tokens_saved"]) + max(0, pre - post)  # type: ignore[arg-type]


# token_type -> counters key. All four are OTel attribute discriminators, not secrets.
_TOKEN_TYPE_COUNTER_KEYS = frozenset({"input", "output", "cacheRead", "cacheCreation"})  # nosec B105


def _accumulate_token_metric(
    token_type: str,
    value: int,
    counters: dict[str, int],
) -> None:
    """Accumulate a single token metric into counters by token_type."""
    if token_type in _TOKEN_TYPE_COUNTER_KEYS:
        counters[token_type] += value


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
    state["total_input_bytes"] = state["total_input_bytes"] + _safe_float(attrs.get("tool_input_size_bytes", 0), 0.0)  # type: ignore[operator]
    state["total_output_bytes"] = state["total_output_bytes"] + _safe_float(attrs.get("tool_result_size_bytes", 0), 0.0)  # type: ignore[operator]


def _accumulate_cost_metric(
    value: float,
    attrs: dict[str, object],
    cost_holder: list[float],
    model_cost: dict[str, float],
) -> None:
    """Accumulate a cost metric into cost_holder[0] and model_cost breakdown."""
    cost_holder[0] += _safe_float(value, 0.0)
    model = _trunc(attrs.get("model", "unknown"))
    model_cost[model] += _safe_float(value, 0.0)


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
