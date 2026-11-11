"""summarize-findings: count a findings JSON array grouped by a named field."""

from __future__ import annotations

import json
from pathlib import Path

UNKNOWN_BUCKET = "unknown"


class FindingsError(ValueError):
    """Input could not be read or is not a JSON array."""


def load_findings(path: str) -> list[object]:
    """Read ``path`` and return its JSON array; raise FindingsError otherwise."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FindingsError(str(exc)) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FindingsError(f"JSON parse error: {exc}") from exc
    if not isinstance(data, list):
        raise FindingsError(f"expected a JSON array, got {type(data).__name__}")
    return data


def count_by(items: list[object], group_by: str) -> dict[str, int]:
    """Count items by ``group_by``; non-objects and missing/null fields go to 'unknown'."""
    counts: dict[str, int] = {}
    for item in items:
        value = item.get(group_by) if isinstance(item, dict) else None
        bucket = UNKNOWN_BUCKET if value is None else str(value)
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts
