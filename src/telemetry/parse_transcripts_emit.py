"""Output/emit helpers and shared types for parse-transcripts.

Extracted from parse_transcripts.py to reduce complexity.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ParseResult:
    session_id: str
    prompts_added: int
    bash_added: int
    bytes_processed: int
    status: str


def _token_estimate(text: str) -> int:
    # Rough heuristic: ~4 chars per token
    return max(1, len(text) // 4)


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
            widths[c] = max(widths[c], len(str(row.get(c) or "")))
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    sep = "  ".join("-" * widths[c] for c in cols)
    print(header, file=sys.stdout)
    print(sep, file=sys.stdout)
    for row in rows:
        print("  ".join(str(row.get(c) or "").ljust(widths[c]) for c in cols), file=sys.stdout)
