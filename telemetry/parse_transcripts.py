"""Parse Claude Code JSONL transcripts into a structured JSON index.

Pre-parses transcripts so workflow stages can read a compact index instead
of streaming raw JSONL inline, eliminating the INLINE_LARGE_DATA anti-pattern.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import click

from telemetry.fileutil import atomic_write_json, safe_load_json
from telemetry.timeutil import now_utc, parse_window

DEFAULT_INDEX_DIR = Path.home() / ".config" / "dancing-bear" / "work" / "prompt-index"
STATE_FILE = ".state.json"
LOCK_FILE = ".lock"
INPUT_PREVIEW_LEN = 200


@dataclass(frozen=True)
class ParseResult:
    session_id: str
    prompts_added: int
    bash_added: int
    bytes_processed: int
    status: str


def _load_json_nullable(path: Path) -> dict[str, object] | None:
    """Load JSON from path, returning None if the file is missing or invalid.

    safe_load_json always returns a dict (coerces None → {}), so this helper
    is kept for the one call site that needs to distinguish "file absent" from
    "file present but empty".
    """
    try:
        with open(path, encoding="utf-8") as f:
            result = json.load(f)
            return result if isinstance(result, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _token_estimate(text: str) -> int:
    # Rough heuristic: ~4 chars per token
    return max(1, len(text) // 4)


def _parse_since_window(since: str) -> datetime | None:
    """Parse a time window string like '7d', '30d', 'all' into a UTC cutoff datetime.

    Requires an explicit unit suffix (d/h/m/s/w) — bare integers are rejected so
    that callers always state the unit explicitly.
    """
    if since.lower() == "all":
        return None
    # Validate that the prefix (everything before the unit suffix) is a strict
    # integer — this CLI historically used int() so float prefixes like "1.5d"
    # and bare integers like "100" are rejected.
    _VALID_SUFFIXES = ("d", "h", "m", "s", "w")
    s = since.strip().lower()
    for suffix in _VALID_SUFFIXES:
        if s.endswith(suffix):
            prefix = s[:-1]
            try:
                int(prefix)
            except ValueError:
                raise click.BadParameter(
                    f"Cannot parse time window: {since!r}. Use e.g. 7d, 30d, all."
                )
            break
    else:
        # No recognized suffix — includes bare integers and unknown suffixes
        raise click.BadParameter(f"Cannot parse time window: {since!r}. Use e.g. 7d, 30d, all.")
    try:
        return now_utc() - parse_window(since)
    except ValueError:
        raise click.BadParameter(f"Cannot parse time window: {since!r}. Use e.g. 7d, 30d, all.")


def _find_jsonl_files(projects_dir: Path, since_dt: datetime | None) -> list[Path]:
    """Return all .jsonl files under projects_dir, optionally filtered by mtime."""
    files: list[Path] = []
    if not projects_dir.exists():
        return files
    for p in projects_dir.rglob("*.jsonl"):
        if not p.is_file():
            continue
        if since_dt is not None:
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                if mtime < since_dt:
                    continue
            except OSError:
                continue
        files.append(p)
    return files


def _extract_session_id(record: dict[str, object]) -> str | None:
    val = record.get("sessionId") or record.get("session_id")
    return str(val) if val is not None else None


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


def _process_jsonl_file(
    path: Path,
    start_offset: int,
    session_index: dict[str, object],
    project_path: str,
) -> tuple[int, int, int, int]:
    """Stream new bytes from path starting at start_offset.

    Returns (prompts_added, bash_added, bytes_processed, new_offset).
    """
    try:
        with open(path, "rb") as f:
            file_size = f.seek(0, 2)
            # If file was truncated/rotated, reprocess from the beginning.
            effective_offset = start_offset if start_offset <= file_size else 0
            f.seek(effective_offset)

            prompt_index_base = len(session_index.get("prompts", []))  # type: ignore[arg-type]
            prompts_added = 0
            bash_added = 0
            bytes_processed = 0
            # new_offset tracks the HWM — only advances past complete lines
            # (lines ending with \n). A partial line at EOF is left for the
            # next run to retry, keeping peak memory proportional to one line.
            new_offset = effective_offset

            for raw_line in f:
                if not raw_line.endswith(b"\n"):
                    # Partial record at EOF — stop without advancing HWM.
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                new_offset += len(raw_line)
                if not line:
                    bytes_processed += len(raw_line)
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    bytes_processed += len(raw_line)
                    continue
                if not isinstance(record, dict):
                    bytes_processed += len(raw_line)
                    continue
                prompts_delta, bash_delta = _process_one_record(
                    record, session_index, prompt_index_base, prompts_added
                )
                prompts_added += prompts_delta
                bash_added += bash_delta
                bytes_processed += len(raw_line)
    except OSError:
        return 0, 0, 0, start_offset

    session_index["prompt_count"] = len(session_index["prompts"])  # type: ignore[arg-type]
    session_index["bash_count"] = len(session_index["bash_commands"])  # type: ignore[arg-type]
    session_index["last_updated"] = datetime.now(timezone.utc).isoformat()
    session_index["project_path"] = project_path

    return prompts_added, bash_added, bytes_processed, new_offset


def _session_id_from_path(path: Path) -> str:
    """Derive a session_id from the JSONL filename stem."""
    return path.stem


def _safe_mtime(p: Path) -> float:
    """Return p's mtime, or 0.0 if the file no longer exists (TOCTOU guard)."""
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _load_or_init_session_index(index_dir: Path, session_id: str) -> dict[str, object]:
    index_path = index_dir / f"{session_id}.json"
    idx: dict[str, object] = _load_json_nullable(index_path) or {}
    if idx:
        # Ensure list fields exist for safe appending
        for key in ("prompts", "bash_commands", "tool_calls"):
            if not isinstance(idx.get(key), list):
                idx[key] = []
        # Coerce scalar counts — a corrupted JSON value (e.g. str) would break arithmetic.
        for key, list_key in (("prompt_count", "prompts"), ("bash_count", "bash_commands")):
            try:
                idx[key] = int(idx.get(key) or len(idx[list_key]))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                idx[key] = len(idx[list_key])  # type: ignore[arg-type]
        return idx
    return {
        "session_id": session_id,
        "project_path": "",
        "last_updated": "",
        "prompts": [],
        "bash_commands": [],
        "tool_calls": [],
        "prompt_count": 0,
        "bash_count": 0,
    }


def _process_one_file(
    jsonl_path: Path,
    index_dir: Path,
    state: dict[str, object],
    state_path: Path,
    force: bool,
) -> ParseResult:
    """Process a single JSONL file and update state. Returns a ParseResult."""
    abs_path = str(jsonl_path.resolve())
    session_id = _session_id_from_path(jsonl_path)
    try:
        start_offset = 0 if force else int(state.get(abs_path, 0) or 0)
    except (TypeError, ValueError):
        start_offset = 0  # corrupted state entry — reprocess from beginning
    project_path = str(jsonl_path.parent)
    session_index = _load_or_init_session_index(index_dir, session_id)

    try:
        prompts_added, bash_added, bytes_proc, new_offset = _process_jsonl_file(
            jsonl_path, start_offset, session_index, project_path
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[parse-transcripts] error processing {jsonl_path}: {exc}", file=sys.stderr)
        return ParseResult(session_id=session_id, prompts_added=0, bash_added=0, bytes_processed=0, status="error")

    atomic_write_json(index_dir / f"{session_id}.json", session_index)
    state[abs_path] = new_offset
    atomic_write_json(state_path, state)

    return ParseResult(
        session_id=session_id,
        prompts_added=prompts_added,
        bash_added=bash_added,
        bytes_processed=bytes_proc,
        status="ok" if bytes_proc > 0 else "skipped",
    )


def run_parse_transcripts(
    since: str,
    projects_dir: Path | None,
    index_dir: Path,
    force: bool,
    limit: int,
) -> list[ParseResult]:
    """Core logic for parse-transcripts, separated for testability."""
    index_dir.mkdir(parents=True, exist_ok=True)
    lock_path = index_dir / LOCK_FILE
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    results: list[ParseResult] = []

    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        state_path = index_dir / STATE_FILE
        raw_state = safe_load_json(state_path)
        state: dict[str, object] = raw_state if isinstance(raw_state, dict) else {}

        if projects_dir is None:
            projects_dir = Path.home() / ".claude" / "projects"

        since_dt = _parse_since_window(since)
        files = _find_jsonl_files(projects_dir, since_dt)

        if limit > 0:
            files.sort(key=_safe_mtime, reverse=True)
            files = files[:limit]

        for jsonl_path in files:
            results.append(_process_one_file(jsonl_path, index_dir, state, state_path, force))

    except click.BadParameter:
        raise  # propagate bad --since values to the CLI layer for user-facing error
    except Exception as exc:  # noqa: BLE001
        print(f"[parse-transcripts] unexpected error: {exc}", file=sys.stderr)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

    return results


def _emit_rows(rows: list[dict[str, object]], fmt: str = "table", headers: list[str] | None = None) -> None:
    """Emit rows as JSON or a plain text table."""
    if fmt == "json":
        print(json.dumps(rows, indent=2, default=str))
        return
    if not rows:
        return
    cols = headers or list(rows[0].keys())
    widths = {c: len(c) for c in cols}
    for row in rows:
        for c in cols:
            widths[c] = max(widths[c], len(str(row.get(c, ""))))
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    sep = "  ".join("-" * widths[c] for c in cols)
    print(header, file=sys.stdout)
    print(sep, file=sys.stdout)
    for row in rows:
        print("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in cols), file=sys.stdout)


@click.command("parse-transcripts")
@click.option("--since", default="all", show_default=True,
              help="Time window to process (e.g. 7d, 30d, all).")
@click.option("--projects-dir", default=None, type=click.Path(),
              help="Override ~/.claude/projects.")
@click.option("--index-dir", default=None, type=click.Path(),
              help="Override default index dir (~/.config/dancing-bear/work/prompt-index/).")
@click.option("--force", is_flag=True, default=False,
              help="Reprocess all files, ignoring high-water marks.")
@click.option("--format", "fmt", default="table",
              type=click.Choice(["json", "table"]), show_default=True)
@click.option("--limit", default=0, show_default=True,
              help="Process at most N sessions (0 = all).")
def parse_transcripts(
    since: str,
    projects_dir: str | None,
    index_dir: str | None,
    force: bool,
    fmt: str,
    limit: int,
) -> None:
    """Pre-parse JSONL transcripts into a structured JSON index."""
    resolved_projects = Path(projects_dir).expanduser() if projects_dir else None
    resolved_index = Path(index_dir).expanduser() if index_dir else DEFAULT_INDEX_DIR

    try:
        results = run_parse_transcripts(
            since=since,
            projects_dir=resolved_projects,
            index_dir=resolved_index,
            force=force,
            limit=limit,
        )
    except click.BadParameter as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)

    if fmt == "json":
        rows = [
            {
                "session_id": r.session_id,
                "prompts_added": r.prompts_added,
                "bash_added": r.bash_added,
                "bytes_processed": r.bytes_processed,
                "status": r.status,
            }
            for r in results
        ]
        _emit_rows(rows, fmt="json")
        return

    if not results:
        click.echo("No sessions processed.")
        return

    rows = [
        {
            "session_id": r.session_id[:24],
            "prompts": str(r.prompts_added),
            "bash_cmds": str(r.bash_added),
            "new_bytes": str(r.bytes_processed),
            "status": r.status,
        }
        for r in results
    ]
    _emit_rows(rows, fmt="table", headers=["session_id", "prompts", "bash_cmds", "new_bytes", "status"])
