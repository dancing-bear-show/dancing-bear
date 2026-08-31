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

from core.cli_errors import CLIError
from core.cli_output import OutputWriter
from core.pipeline import BaseProducer, RequestConsumer, SafeProcessor
from telemetry.parse_transcripts_emit import ParseResult, _emit_rows
from telemetry.parse_transcripts_io import run_parse_transcripts


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


def _run_parse_transcripts(request: TranscriptParseRequest, fmt: str) -> None:
    """Execute parse-transcripts pipeline and emit results."""
    writer = OutputWriter()
    envelope = TranscriptParseProcessor().process(RequestConsumer(request).consume())
    if envelope.ok():
        TranscriptParseProducer(writer=writer)._produce_success(  # noqa: SLF001 - direct call to pass fmt context
            envelope.unwrap(),
            {"fmt": fmt},
        )
    else:
        msg = (envelope.diagnostics or {}).get("message", "parse-transcripts failed")
        raise CLIError(msg)
