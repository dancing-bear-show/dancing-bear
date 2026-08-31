"""File-level I/O, session management, and orchestration for parse-transcripts.

Extracted from parse_transcripts.py to reduce complexity.
Record-parsing helpers (no I/O) live in _transcript_record_parser.py.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from core.cli_errors import CLIError
from core.fileutil import atomic_write_json, safe_load_json
from telemetry.timeutil import now_utc, parse_window
from telemetry.parse_transcripts_emit import ParseResult
from telemetry._transcript_record_parser import _process_one_record

DEFAULT_INDEX_DIR = Path.home() / ".config" / "dancing-bear" / "work" / "prompt-index"
STATE_FILE = ".state.json"
LOCK_FILE = ".lock"


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
                raise CLIError(
                    f"Cannot parse time window: {since!r}. Use e.g. 7d, 30d, all."
                )
            break
    else:
        # No recognized suffix — includes bare integers and unknown suffixes
        raise CLIError(f"Cannot parse time window: {since!r}. Use e.g. 7d, 30d, all.")
    try:
        return now_utc() - parse_window(since)
    except ValueError:
        raise CLIError(f"Cannot parse time window: {since!r}. Use e.g. 7d, 30d, all.")


def _passes_since_filter(p: Path, since_dt: datetime | None) -> bool:
    """Return True when p should be included given the since_dt mtime cutoff."""
    if since_dt is None:
        return True
    try:
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return False
    return mtime >= since_dt


def _find_jsonl_files(projects_dir: Path, since_dt: datetime | None) -> list[Path]:
    """Return all .jsonl files under projects_dir, optionally filtered by mtime."""
    if not projects_dir.exists():
        return []
    return [
        p
        for p in projects_dir.rglob("*.jsonl")
        if p.is_file() and _passes_since_filter(p, since_dt)
    ]


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


def _process_one_line(
    raw_line: bytes,
    session_index: dict[str, object],
    prompt_index_base: int,
    prompts_added_so_far: int,
) -> tuple[int, int] | None:
    """Parse and apply one raw JSONL line to session_index.

    Returns (prompts_delta, bash_delta) for a valid record, or None when the
    line is blank, malformed JSON, or not a JSON object — all of which still
    count as "processed" bytes but contribute no record deltas.
    """
    line = raw_line.decode("utf-8", errors="replace").strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    return _process_one_record(record, session_index, prompt_index_base, prompts_added_so_far)


def _stream_jsonl_lines(
    f: BinaryIO,
    effective_offset: int,
    session_index: dict[str, object],
) -> tuple[int, int, int, int]:
    """Iterate complete lines from an open binary file handle, applying each.

    Returns (prompts_added, bash_added, bytes_processed, new_offset).
    """
    prompt_index_base = len(session_index.get("prompts", []))  # type: ignore[arg-type]
    prompts_added = 0
    bash_added = 0
    bytes_processed = 0
    # new_offset tracks the HWM — only advances past complete lines (lines
    # ending with \n). A partial line at EOF is left for the next run to
    # retry, keeping peak memory proportional to one line.
    new_offset = effective_offset

    for raw_line in f:
        if not raw_line.endswith(b"\n"):
            # Partial record at EOF — stop without advancing HWM.
            break
        new_offset += len(raw_line)
        bytes_processed += len(raw_line)
        deltas = _process_one_line(raw_line, session_index, prompt_index_base, prompts_added)
        if deltas is not None:
            prompts_added += deltas[0]
            bash_added += deltas[1]

    return prompts_added, bash_added, bytes_processed, new_offset


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
            prompts_added, bash_added, bytes_processed, new_offset = _stream_jsonl_lines(
                f, effective_offset, session_index
            )
    except OSError:
        return 0, 0, 0, start_offset

    session_index["prompt_count"] = len(session_index["prompts"])  # type: ignore[arg-type]
    session_index["bash_count"] = len(session_index["bash_commands"])  # type: ignore[arg-type]
    session_index["last_updated"] = now_utc().isoformat()
    session_index["project_path"] = project_path

    return prompts_added, bash_added, bytes_processed, new_offset


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
    import fcntl

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

    except CLIError:
        raise  # propagate bad --since values to the CLI layer for user-facing error
    except Exception as exc:  # noqa: BLE001
        print(f"[parse-transcripts] unexpected error: {exc}", file=sys.stderr)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

    return results
