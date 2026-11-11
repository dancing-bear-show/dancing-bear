"""Agent token aggregation helpers for TranscriptProvider.

Standalone helpers for accumulating per-agent token usage across JSONL
transcript files.  TranscriptProvider delegates to these helpers so the
accumulation logic can be read and tested independently of JSONL parsing
and session discovery.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from telemetry.timeutil import parse_iso_utc
from telemetry.models import AgentTokenRow
from telemetry.pricing import TokenMetrics, compute_cost
from telemetry.providers.transcript_parse import (
    MessageKey,
    extract_cache_creation,
    is_billable_usage,
    message_key,
)

logger = logging.getLogger(__name__)


@dataclass
class TokenAccumulators:
    """Mutable per-agent, per-model token count accumulators.

    Each dict keyed by (agent_name, model) except call_count which is keyed by agent_name.
    Fields hold defaultdict(int) so callers can increment without a membership check.
    ``cache_write_1h`` is the 1-hour-TTL part of ``cache_write``. ``seen`` maps
    each billed call already counted to the output count counted for it, so a
    call repeated across records or files is billed once.
    """

    input: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    output: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    cache_read: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    cache_write: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    cache_write_1h: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    call_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    seen: dict[MessageKey, int] = field(default_factory=dict)


@dataclass
class _AgentUsage:
    """One billed assistant record, reduced to what the agent breakdown needs."""

    agent_name: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_write: int
    cache_write_1h: int
    key: MessageKey | None


def build_agent_row(
    agent_name: str,
    accs: TokenAccumulators,
) -> AgentTokenRow:
    """Collapse per-(agent, model) accumulators into one AgentTokenRow for agent_name.

    Single pass: collect per-model token totals, then compute cost once per model.
    """
    per_model: dict[str, list[int]] = {}  # model -> [in, out, cr, cw, cw_1h]
    for (n, m) in accs.input:
        if n != agent_name:
            continue
        if m not in per_model:
            per_model[m] = [0, 0, 0, 0, 0]
        per_model[m][0] += accs.input[n, m]
        per_model[m][1] += accs.output.get((n, m), 0)
        per_model[m][2] += accs.cache_read.get((n, m), 0)
        per_model[m][3] += accs.cache_write.get((n, m), 0)
        per_model[m][4] += accs.cache_write_1h.get((n, m), 0)

    models_used = sorted(m for m in per_model if m)
    total_input = sum(v[0] for v in per_model.values())
    total_output = sum(v[1] for v in per_model.values())
    total_cr = sum(v[2] for v in per_model.values())
    total_cw = sum(v[3] for v in per_model.values())

    if per_model:
        cost = sum(
            compute_cost(TokenMetrics(v[0], v[1], v[2], v[3], v[4]), m)
            for m, v in per_model.items()
        )
    else:
        cost = 0.0

    return AgentTokenRow(
        agent=agent_name,
        calls=accs.call_count[agent_name],
        input_tokens=total_input,
        output_tokens=total_output,
        cache_read_tokens=total_cr,
        cache_write_tokens=total_cw,
        models=models_used,
        est_cost=cost,
    )


def _parse_agent_usage_line(raw_line: str, since: datetime) -> _AgentUsage | None:
    """Parse one JSONL line into an ``_AgentUsage``, else None.

    Returns None for blank lines, unparseable JSON, non-assistant records,
    records with no billable usage (absent, null, all-zero, or the
    ``<synthetic>`` model), and records whose timestamp is older than ``since``.

    A record whose timestamp is missing or unparseable is COUNTED, not skipped:
    ``parse_iso_utc`` returns None for those, and the cutoff only excludes a
    record when a timestamp actually parsed and fell before ``since``. Dropping
    them instead would silently undercount usage whenever a transcript writer
    omits or malforms the field. This mirrors the pre-refactor inline logic
    exactly -- do not "fix" it into a skip without checking callers.
    """
    raw_line = raw_line.strip()
    if not raw_line:
        return None
    try:
        record = json.loads(raw_line)
    except json.JSONDecodeError:
        return None

    if record.get("type") != "assistant":
        return None

    msg = record.get("message") or {}
    usage = msg.get("usage") or {}
    model = msg.get("model", "") or ""
    cache_write, cache_write_1h = extract_cache_creation(usage)
    if not is_billable_usage(model, usage, cache_write):
        return None

    ts = parse_iso_utc(record.get("timestamp", ""))
    if ts is not None and ts < since:
        return None

    return _AgentUsage(
        agent_name=record.get("agentName") or "(orchestrator)",
        model=model,
        input_tokens=_count(usage.get("input_tokens")),
        output_tokens=_count(usage.get("output_tokens")),
        cache_read=_count(usage.get("cache_read_input_tokens")),
        cache_write=cache_write,
        cache_write_1h=cache_write_1h,
        key=message_key(msg.get("id"), record.get("requestId")),
    )


def _count(value: object) -> int:
    """Return a token count, treating null and non-numeric values as 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _apply_agent_usage(accs: TokenAccumulators, rec: _AgentUsage) -> None:
    """Add one parsed usage record's token counts into accs.

    A later copy of a call already counted (another content block of the same
    turn, or a resumed session's copy) adds only its output growth: every other
    field was final on, and counted from, the first copy.
    """
    key = (rec.agent_name, rec.model)
    if rec.key is not None:
        prev_output = accs.seen.get(rec.key)
        if prev_output is not None:
            if rec.output_tokens > prev_output:
                accs.output[key] += rec.output_tokens - prev_output
                accs.seen[rec.key] = rec.output_tokens
            return
        accs.seen[rec.key] = rec.output_tokens
    accs.input[key] += rec.input_tokens
    accs.output[key] += rec.output_tokens
    accs.cache_read[key] += rec.cache_read
    accs.cache_write[key] += rec.cache_write
    accs.cache_write_1h[key] += rec.cache_write_1h
    accs.call_count[rec.agent_name] += 1


def accumulate_agent_tokens(
    jsonl_file: Path,
    since: datetime,
    accs: TokenAccumulators,
) -> None:
    """Parse one JSONL file and accumulate token counts into accs."""
    try:
        with open(jsonl_file, encoding="utf-8") as fh:
            for raw_line in fh:
                parsed = _parse_agent_usage_line(raw_line, since)
                if parsed is not None:
                    _apply_agent_usage(accs, parsed)
    except OSError as exc:  # nosec B110 - non-fatal; log and continue
        logger.warning("Could not read JSONL file: %s", exc)
