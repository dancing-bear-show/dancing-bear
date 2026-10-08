"""Count blocking findings in a sweep-findings.json file.

review-fix-threads embeds the same derived-count one-liner in two stages
(refix-dispatch and resweep-regressions). Moving the logic here makes it
owned by executable tests, eliminates the duplication, and keeps inline
YAML stages from growing untested Python.

Blocking severity levels match the gate used by sweep-fix-regressions:
"critical" and "major". The derivation is intentionally fail-closed:
a mismatch between the agent-written "blocking" summary field and the
derived count writes a diagnostic to stderr but does not suppress the
derived count.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO


_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"critical", "major"})


class CountBlockingError(ValueError):
    """The input file is malformed; the count cannot be derived."""


def count_blocking(path: str) -> tuple[int, int | None]:
    """Derive the blocking count from *path* (a sweep-findings.json file).

    Returns ``(derived, reported)`` where:

    - ``derived`` is the count of findings whose severity is "critical" or
      "major", computed from the "findings" list directly.
    - ``reported`` is the value of the agent-written "blocking" summary field,
      or ``None`` when the field is absent.

    Raises :class:`CountBlockingError` when:

    - The file is unreadable or not valid JSON.
    - The top-level value is not a JSON object.
    - The "findings" key is present but is not a list.
    - The "blocking" key is present but is not an integer.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CountBlockingError(f"cannot read {path!r}: {exc.strerror}") from exc
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CountBlockingError(f"not valid JSON: {exc.msg}") from exc
    if not isinstance(doc, dict):
        raise CountBlockingError("top-level value is not a JSON object")
    findings_raw = doc.get("findings", [])
    if not isinstance(findings_raw, list):
        raise CountBlockingError(
            f"'findings' must be a list, got {type(findings_raw).__name__}"
        )
    blocking_raw = doc.get("blocking")
    if blocking_raw is not None and not isinstance(blocking_raw, int):
        raise CountBlockingError(
            f"'blocking' must be an integer, got {type(blocking_raw).__name__}"
        )
    derived = sum(
        1
        for f in findings_raw
        if isinstance(f, dict) and f.get("severity") in _BLOCKING_SEVERITIES
    )
    reported: int | None = blocking_raw if isinstance(blocking_raw, int) else None
    return derived, reported


def cmd_count_blocking(path: str, *, stderr: IO[str] | None = None) -> int:
    """Run the count-blocking command; return the process exit code.

    Prints the derived blocking count to stdout. Writes a
    ``summary_mismatch`` diagnostic to *stderr* (defaults to
    ``sys.stderr``) when the agent-written "blocking" field disagrees with
    the derived count. Returns 2 on malformed input, 0 otherwise.
    """
    err: IO[str] = stderr if stderr is not None else sys.stderr
    try:
        derived, reported = count_blocking(path)
    except CountBlockingError as exc:
        print(f"count-blocking: {exc}", file=err)
        return 2
    print(derived)
    if reported is not None and reported != derived:
        print(
            f"summary_mismatch: reported={reported} derived={derived}",
            file=err,
        )
    return 0
