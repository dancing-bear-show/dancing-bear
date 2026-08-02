"""JSONL record parsing helpers for TranscriptProvider.

Standalone functions that parse raw JSONL records from Claude Code transcript
files into SessionEvent and AgentSummary model objects.  TranscriptProvider
delegates to these helpers so the per-record parse logic can be read, tested,
and reasoned about independently of session discovery and aggregation.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path

from telemetry.timeutil import parse_iso_utc
from telemetry.models import AgentSummary, SessionEvent

logger = logging.getLogger(__name__)

_JSONL_GLOB = "*.jsonl"
_SUBDIR_GLOB = "*/subagents/*.jsonl"

CostFn = Callable[[str, int, int, int, int], float]


def parse_assistant_record(
    record: dict,
    agent_tool_inputs: dict[str, dict],
    sequence: int,
    compute_cost_fn: CostFn,
) -> tuple[list[SessionEvent], int]:
    """Parse one assistant JSONL record into SessionEvent objects.

    Returns (new_events, updated_sequence).

    Args:
        record: Raw decoded JSONL record dict.
        agent_tool_inputs: Mutable map of tool_use_id -> Agent tool input,
            updated in-place when an Agent tool_use block is encountered.
        sequence: Current sequence counter; incremented for each new event.
        compute_cost_fn: Callable(model, input, output, cache_read, cache_create)
            returning a float USD cost.
    """
    new_events: list[SessionEvent] = []
    session_id = record.get("sessionId", "")
    ts = parse_iso_utc(record.get("timestamp", "")) or datetime.now(timezone.utc)
    msg = record.get("message", {})
    usage = msg.get("usage", {})
    model = msg.get("model", "")
    content = msg.get("content", [])

    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_create = usage.get("cache_creation_input_tokens", 0)

    cost = 0.0
    if usage:
        cost = compute_cost_fn(model, input_tokens, output_tokens, cache_read, cache_create)
        sequence += 1
        new_events.append(SessionEvent(
            timestamp=ts,
            event_type="api_request",
            sequence=sequence,
            session_id=session_id,
            model=model,
            cost_usd=cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_create,
        ))

    tool_blocks = [b for b in content if b.get("type") == "tool_use"]
    per_tool_cost = cost / len(tool_blocks) if usage and tool_blocks else 0.0

    for block in tool_blocks:
        tool_name = block.get("name", "")
        tool_id = block.get("id", "")
        tool_input = block.get("input", {})
        if tool_name == "Agent":
            agent_tool_inputs[tool_id] = tool_input
        sequence += 1
        new_events.append(SessionEvent(
            timestamp=ts,
            event_type="tool_use",
            sequence=sequence,
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            model=model,
            cost_usd=per_tool_cost,
            cost_is_estimated=True,
        ))

    return new_events, sequence


def parse_user_record(
    record: dict,
    agent_tool_inputs: dict[str, dict],
    compute_cost_fn: CostFn,
) -> AgentSummary | None:
    """Parse one user JSONL record into an AgentSummary, or None if not an agent result.

    Args:
        record: Raw decoded JSONL record dict.
        agent_tool_inputs: Map of tool_use_id -> Agent tool input built from
            preceding assistant records.
        compute_cost_fn: Callable(model, input, output, cache_read, cache_create)
            returning a float USD cost.
    """
    tool_use_result = record.get("toolUseResult")
    if not tool_use_result or "agentId" not in tool_use_result:
        return None

    agent_id = tool_use_result["agentId"]
    agent_type = tool_use_result.get("agentType", "")
    total_tokens = tool_use_result.get("totalTokens", 0)
    total_tool_uses = tool_use_result.get("totalToolUseCount", 0)
    duration_ms = tool_use_result.get("totalDurationMs", 0)
    sub_usage = tool_use_result.get("usage", {})

    sub_input = sub_usage.get("input_tokens", 0)
    sub_output = sub_usage.get("output_tokens", 0)
    sub_cache_read = sub_usage.get("cache_read_input_tokens", 0)
    sub_cache_create = sub_usage.get("cache_creation_input_tokens", 0)

    content_blocks = record.get("message", {}).get("content", [])
    tool_use_id = next(
        (b.get("tool_use_id") for b in content_blocks if b.get("type") == "tool_result"),
        None,
    )
    agent_input = agent_tool_inputs.get(tool_use_id or "", {})
    description = agent_input.get("description", "")
    agent_model = agent_input.get("model", "")

    cost = compute_cost_fn(agent_model, sub_input, sub_output, sub_cache_read, sub_cache_create)
    return AgentSummary(
        agent_id=agent_id,
        agent_type=agent_type,
        description=description,
        model=agent_model,
        duration_ms=duration_ms,
        total_tokens=total_tokens,
        total_tool_uses=total_tool_uses,
        cost_usd=cost,
    )


def parse_session_file(  # noqa: S3776 - JSONL file parser; loop+try/except+message-type dispatch is irreducible
    path: Path,
    compute_cost_fn: CostFn,
) -> tuple[list[SessionEvent], list[AgentSummary]]:
    """Parse a JSONL transcript file and return (events, agents).

    For each assistant message with usage, one ``api_request`` SessionEvent is
    emitted.  For each tool_use block inside that assistant message, one
    ``tool_use`` SessionEvent is emitted.  If a user message carries a
    ``toolUseResult`` with an ``agentId``, an AgentSummary is created.

    Args:
        path: Path to a ``.jsonl`` transcript file.
        compute_cost_fn: Callable(model, input, output, cache_read, cache_create)
            returning a float USD cost.
    """
    events: list[SessionEvent] = []
    agents: list[AgentSummary] = []
    agent_tool_inputs: dict[str, dict] = {}
    sequence = 0

    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            msg_type = record.get("type")
            if msg_type == "assistant":
                new_evts, sequence = parse_assistant_record(
                    record, agent_tool_inputs, sequence, compute_cost_fn
                )
                events.extend(new_evts)
            elif msg_type == "user":
                agent = parse_user_record(record, agent_tool_inputs, compute_cost_fn)
                if agent is not None:
                    agents.append(agent)

    return events, agents


def iter_jsonl_files(project_dir: Path) -> Iterator[tuple[Path, str]]:
    """Yield (jsonl_path, session_id) for all JSONL files under project_dir.

    Handles two storage layouts:
    - New (post-Apr 2026): ``<project>/<session-uuid>.jsonl``
      session_id = file stem
    - Old (pre-Apr 2026): ``<project>/<session-uuid>/subagents/<agent-id>.jsonl``
      session_id = the ``<session-uuid>`` directory name
    """
    for jsonl_file in project_dir.glob(_JSONL_GLOB):
        yield jsonl_file, jsonl_file.stem
    for jsonl_file in project_dir.glob(_SUBDIR_GLOB):
        # path is <project>/<session-uuid>/subagents/<agent-id>.jsonl
        # parent is <project>/<session-uuid>/subagents
        # parent.parent is <project>/<session-uuid>
        yield jsonl_file, jsonl_file.parent.parent.name
