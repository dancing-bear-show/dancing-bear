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

logger = logging.getLogger(__name__)


@dataclass
class TokenAccumulators:
    """Mutable per-agent, per-model token count accumulators.

    Each dict keyed by (agent_name, model) except call_count which is keyed by agent_name.
    Fields hold defaultdict(int) so callers can increment without a membership check.
    """

    input: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    output: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    cache_read: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    cache_write: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    call_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def build_agent_row(
    agent_name: str,
    accs: TokenAccumulators,
) -> AgentTokenRow:
    """Collapse per-(agent, model) accumulators into one AgentTokenRow for agent_name.

    Single pass: collect per-model token totals, then compute cost once per model.
    """
    per_model: dict[str, list[int]] = {}  # model -> [in, out, cr, cw]
    for (n, m) in accs.input:
        if n != agent_name:
            continue
        if m not in per_model:
            per_model[m] = [0, 0, 0, 0]
        per_model[m][0] += accs.input[n, m]
        per_model[m][1] += accs.output.get((n, m), 0)
        per_model[m][2] += accs.cache_read.get((n, m), 0)
        per_model[m][3] += accs.cache_write.get((n, m), 0)

    models_used = sorted(m for m in per_model if m)
    total_input = sum(v[0] for v in per_model.values())
    total_output = sum(v[1] for v in per_model.values())
    total_cr = sum(v[2] for v in per_model.values())
    total_cw = sum(v[3] for v in per_model.values())

    if per_model:
        cost = sum(
            compute_cost(TokenMetrics(v[0], v[1], v[2], v[3]), m)
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


def _parse_agent_usage_line(raw_line: str, since: datetime) -> tuple[str, str, dict] | None:
    """Parse one JSONL line into (agent_name, model, usage) if it's a countable
    assistant record on/after ``since``, else None."""
    raw_line = raw_line.strip()
    if not raw_line:
        return None
    try:
        record = json.loads(raw_line)
    except json.JSONDecodeError:
        return None

    if record.get("type") != "assistant":
        return None

    msg = record.get("message", {})
    usage = msg.get("usage")
    if not usage:
        return None

    ts = parse_iso_utc(record.get("timestamp", ""))
    if ts is not None and ts < since:
        return None

    agent_name = record.get("agentName") or "(orchestrator)"
    model = msg.get("model", "") or ""
    return agent_name, model, usage


def _apply_agent_usage(accs: TokenAccumulators, agent_name: str, model: str, usage: dict) -> None:
    """Add one parsed usage record's token counts into accs."""
    key = (agent_name, model)
    accs.input[key] += usage.get("input_tokens", 0)
    accs.output[key] += usage.get("output_tokens", 0)
    accs.cache_read[key] += usage.get("cache_read_input_tokens", 0)
    accs.cache_write[key] += usage.get("cache_creation_input_tokens", 0)
    accs.call_count[agent_name] += 1


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
                if parsed is None:
                    continue
                agent_name, model, usage = parsed
                _apply_agent_usage(accs, agent_name, model, usage)
    except OSError as exc:  # nosec B110 - non-fatal; log and continue
        logger.warning("Could not read JSONL file: %s", exc)
