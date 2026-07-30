"""Parse Claude Code JSONL transcripts into a structured JSON index.

Pre-parses transcripts so workflow stages can read a compact index instead
of streaming raw JSONL inline, eliminating the INLINE_LARGE_DATA anti-pattern.

This module is a thin re-export shim. Implementation lives in:
  - parse_transcripts_emit.py  — ParseResult, _token_estimate, _emit_rows
  - parse_transcripts_io.py    — file I/O, record parsing, run_parse_transcripts
"""

from __future__ import annotations

import sys
from pathlib import Path  # noqa: F401 — re-exported; tests patch telemetry.parse_transcripts.Path

import click

from telemetry.parse_transcripts_emit import (  # noqa: F401
    ParseResult,
    _emit_rows,
    _token_estimate,
)
from telemetry.parse_transcripts_io import (  # noqa: F401
    DEFAULT_INDEX_DIR,
    INPUT_PREVIEW_LEN,
    LOCK_FILE,
    STATE_FILE,
    _append_bash_command,
    _extract_tool_preview,
    _find_jsonl_files,
    _load_json_nullable,
    _load_or_init_session_index,
    _parse_content_blocks,
    _parse_since_window,
    _process_jsonl_file,
    _process_one_file,
    _process_one_record,
    _process_tool_use_blocks,
    _process_user_role_record,
    _safe_mtime,
    _session_id_from_path,
    run_parse_transcripts,
)


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
