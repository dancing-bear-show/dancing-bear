"""Parse Claude Code JSONL transcripts into a structured JSON index.

Pre-parses transcripts so workflow stages can read a compact index instead
of streaming raw JSONL inline, eliminating the INLINE_LARGE_DATA anti-pattern.

Implementation lives in:
  - parse_transcripts_emit.py        — ParseResult, _token_estimate, _emit_rows
  - _transcript_record_parser.py     — pure record-parsing helpers (no I/O)
  - parse_transcripts_io.py          — file I/O, session management, run_parse_transcripts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click

from core.cli_output import OutputWriter
from core.pipeline import BaseProducer, RequestConsumer, SafeProcessor
from telemetry.parse_transcripts_emit import ParseResult, _emit_rows
from telemetry.parse_transcripts_io import DEFAULT_INDEX_DIR, run_parse_transcripts


@dataclass(frozen=True)
class TranscriptParseRequest:
    """Request to parse JSONL transcripts into a structured index."""

    since: str
    projects_dir: Path | None
    index_dir: Path
    force: bool
    limit: int


@dataclass
class TranscriptParseResult:
    """Result of parsing JSONL transcripts."""

    results: list[ParseResult] = field(default_factory=list)


class TranscriptParseProcessor(SafeProcessor[TranscriptParseRequest, TranscriptParseResult]):
    """Parse JSONL transcripts and build a structured index."""

    def _process_safe(self, payload: TranscriptParseRequest) -> TranscriptParseResult:
        results = run_parse_transcripts(
            since=payload.since,
            projects_dir=payload.projects_dir,
            index_dir=payload.index_dir,
            force=payload.force,
            limit=payload.limit,
        )
        return TranscriptParseResult(results=results)


class TranscriptParseProducer(BaseProducer):
    """Render transcript parse results via OutputWriter."""

    def _produce_success(
        self, payload: TranscriptParseResult, diagnostics: dict[str, Any] | None
    ) -> None:
        fmt = (diagnostics or {}).get("fmt", "table")
        w = self._writer
        if fmt == "json":
            rows = [
                {
                    "session_id": r.session_id,
                    "prompts_added": r.prompts_added,
                    "bash_added": r.bash_added,
                    "bytes_processed": r.bytes_processed,
                    "status": r.status,
                }
                for r in payload.results
            ]
            _emit_rows(rows, fmt="json")
            return

        if not payload.results:
            w.print("No sessions processed.")
            return

        rows = [
            {
                "session_id": r.session_id[:24],
                "prompts": str(r.prompts_added),
                "bash_cmds": str(r.bash_added),
                "new_bytes": str(r.bytes_processed),
                "status": r.status,
            }
            for r in payload.results
        ]
        _emit_rows(
            rows,
            fmt="table",
            headers=["session_id", "prompts", "bash_cmds", "new_bytes", "status"],
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

    resolved_request = TranscriptParseRequest(
        since=since,
        projects_dir=resolved_projects,
        index_dir=resolved_index,
        force=force,
        limit=limit,
    )
    writer = OutputWriter()
    envelope = TranscriptParseProcessor().process(RequestConsumer(resolved_request).consume())
    if envelope.ok():
        TranscriptParseProducer(writer=writer)._produce_success(  # noqa: SLF001 - direct call to pass fmt context
            envelope.unwrap(),
            {"fmt": fmt},
        )
    else:
        msg = (envelope.diagnostics or {}).get("message", "parse-transcripts failed")
        raise click.ClickException(msg)
