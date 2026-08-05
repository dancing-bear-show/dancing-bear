"""Pure record-parsing helpers for parse-transcripts (no file I/O).

Extracted from parse_transcripts_io.py to reduce complexity.
"""

from __future__ import annotations

import json

from telemetry.parse_transcripts_emit import _token_estimate

INPUT_PREVIEW_LEN = 200


def _extract_tool_preview(raw_input: object) -> str:
    """Serialize raw_input to a truncated string preview for indexing."""
    try:
        input_str = json.dumps(raw_input) if isinstance(raw_input, dict) else str(raw_input)
    except (TypeError, ValueError):
        input_str = ""
    return input_str[:INPUT_PREVIEW_LEN]


def _append_bash_command(
    name: str,
    raw_input: object,
    session_index: dict[str, object],
) -> int:
    """Append a Bash command to session_index if name is 'Bash' and command is non-empty.

    Returns 1 if a command was appended, 0 otherwise.
    """
    if name != "Bash":
        return 0
    cmd = str((raw_input if isinstance(raw_input, dict) else {}).get("command", ""))
    if not cmd:
        return 0
    bash_commands = session_index["bash_commands"]
    assert isinstance(bash_commands, list)  # nosec B101 - type narrowing; caller always initializes this list
    bash_commands.append(cmd)
    return 1


def _process_tool_use_blocks(
    content_blocks: list[object],
    session_index: dict[str, object],
) -> int:
    """Iterate tool_use blocks in content_blocks and append to session_index.

    Returns bash_added count.
    """
    bash_added = 0
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_use":
            continue
        name = str(block.get("name") or "")
        raw_input = block.get("input") or {}
        preview = _extract_tool_preview(raw_input)
        tool_calls = session_index["tool_calls"]
        assert isinstance(tool_calls, list)  # nosec B101 - type narrowing; caller always initializes this list
        tool_calls.append({"name": name, "input_preview": preview})
        bash_added += _append_bash_command(name, raw_input, session_index)
    return bash_added


def _process_user_role_record(
    record: dict[str, object],
    session_index: dict[str, object],
    prompt_index_base: int,
    prompts_added: int,
) -> int:
    """Handle a role == "user" record and append prompt entries to session_index.

    Returns the number of prompts added by this record.

    Claude Code JSONL user records have message.content as a plain str (the prompt
    text). Tool-result records (also role=user) have content as a list of tool_result
    blocks — those are skipped here since they contain no user-authored text.
    """
    msg = record.get("message") or {}
    if not isinstance(msg, dict):
        msg = {}
    content = msg.get("content") or record.get("content")

    # Plain-string content — the normal user-prompt case.
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return 0
        prompts = session_index["prompts"]
        assert isinstance(prompts, list)  # nosec B101 - type narrowing; caller always initializes this list
        prompts.append({
            "prompt_index": prompt_index_base + prompts_added,
            "text": text,
            "token_estimate": _token_estimate(text),
            "tool_calls_after": 0,
        })
        return 1

    # List content — may be tool_result blocks; extract any text blocks present.
    if not isinstance(content, list):
        return 0
    added = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        prompts = session_index["prompts"]
        assert isinstance(prompts, list)  # nosec B101 - type narrowing; caller always initializes this list
        prompts.append({
            "prompt_index": prompt_index_base + prompts_added + added,
            "text": text,
            "token_estimate": _token_estimate(text),
            "tool_calls_after": 0,
        })
        added += 1
    return added


def _parse_content_blocks(record: dict[str, object], msg: dict[str, object]) -> list[object]:
    """Extract content as a list of blocks from a message dict.

    Assistant records have message.content as a list of typed blocks.
    Returns [] for plain-string content (user prompts) — those are handled
    by _process_user_role_record instead.
    """
    raw = (msg.get("content") or []) if msg else (record.get("content") or [])
    return raw if isinstance(raw, list) else []


def _process_one_record(
    record: dict[str, object],
    session_index: dict[str, object],
    prompt_index_base: int,
    prompts_added: int,
) -> tuple[int, int]:
    """Dispatch a single parsed JSONL record into session_index.

    Returns (prompts_delta, bash_delta) for this record.

    Claude Code JSONL wraps role inside message: record["message"]["role"].
    """
    msg = record.get("message") or {}
    if not isinstance(msg, dict):
        msg = {}

    role = msg.get("role") or record.get("role")
    if not role:
        return 0, 0

    prompts_delta = 0
    if role == "user":
        prompts_delta = _process_user_role_record(
            record, session_index, prompt_index_base, prompts_added
        )

    # Tool-use blocks live in assistant records' content list.
    content_blocks = _parse_content_blocks(record, msg)
    bash_delta = _process_tool_use_blocks(content_blocks, session_index)
    return prompts_delta, bash_delta
