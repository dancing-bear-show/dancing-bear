"""Count blocking findings in a sweep-findings.json file.

review-fix-threads embeds the same derived-count one-liner in two stages
(refix-dispatch and resweep-regressions). Moving the logic here makes it
owned by executable tests, eliminates the duplication, and keeps inline
YAML stages from growing untested Python.

Blocking severity levels match the gate used by sweep-fix-regressions:
"critical" and "major". The derivation is intentionally fail-closed:

- The "findings" key must be present and a list. A missing or wrongly-typed
  "findings" field (e.g. a fix-results.json passed by accident) is malformed
  and raises :class:`CountBlockingError` (CLI exit 2) — a missing key must
  not silently read as zero findings, because a garbled or absent
  sweep-findings.json would then make refix skip and resweep pass.
- Every element of "findings" must be a JSON object. A non-object element is
  malformed (exit 2) rather than silently skipped.
- Every finding must have a "severity" field that is a non-empty string. A
  finding with a missing or non-string severity is malformed (exit 2).
- An unknown severity string (not "critical", "major", "minor", or "info")
  is treated as blocking (counted as 1). This is fail-closed: a future
  severity level added to the guide is never silently ignored.
- The "blocking" summary field is optional. When absent, no mismatch is
  reported. When present, it must be an integer; a wrong type is malformed
  (exit 2). A present "blocking" that disagrees with the derived count writes
  a summary_mismatch diagnostic to stderr but does not change the derived
  count (fail-closed: a mismatch never reduces the count below derived).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO


#: Severity levels that are NOT blocking. Everything else (including unknown
#: values) counts as blocking so a new severity level is never silently ignored.
_NON_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"minor", "info"})

#: All recognised severity levels, for documentation.
_ALL_SEVERITIES: frozenset[str] = frozenset({"critical", "major", "minor", "info"})


class CountBlockingError(ValueError):
    """The input file is malformed; the count cannot be derived."""


def count_blocking(path: str) -> tuple[int, int | None]:
    """Derive the blocking count from *path* (a sweep-findings.json file).

    Returns ``(derived, reported)`` where:

    - ``derived`` is the count of blocking findings. A finding is blocking
      when its "severity" is not in the non-blocking set {"minor", "info"} —
      unknown severities count as blocking (fail-closed).
    - ``reported`` is the value of the agent-written "blocking" summary field,
      or ``None`` when the field is absent.

    Raises :class:`CountBlockingError` when:

    - The file is unreadable or not valid JSON.
    - The top-level value is not a JSON object.
    - The "findings" key is absent (a garbled file must not read as zero).
    - The "findings" value is not a list.
    - Any element of "findings" is not a JSON object.
    - Any finding lacks a "severity" field or has a non-string "severity".
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
    if "findings" not in doc:
        raise CountBlockingError("'findings' key is missing")
    findings_raw = doc["findings"]
    if not isinstance(findings_raw, list):
        raise CountBlockingError(
            f"'findings' must be a list, got {type(findings_raw).__name__}"
        )
    for i, item in enumerate(findings_raw):
        if not isinstance(item, dict):
            raise CountBlockingError(
                f"findings[{i}] is not an object, got {type(item).__name__}"
            )
        sev = item.get("severity")
        if sev is None:
            raise CountBlockingError(
                f"findings[{i}] is missing the 'severity' field"
            )
        if not isinstance(sev, str):
            raise CountBlockingError(
                f"findings[{i}].severity must be a string, got {type(sev).__name__}"
            )
    blocking_raw = doc.get("blocking")
    if blocking_raw is not None and not isinstance(blocking_raw, int):
        raise CountBlockingError(
            f"'blocking' must be an integer, got {type(blocking_raw).__name__}"
        )
    derived = sum(
        1
        for f in findings_raw
        if f.get("severity") not in _NON_BLOCKING_SEVERITIES
    )
    reported: int | None = blocking_raw if isinstance(blocking_raw, int) else None
    return derived, reported


def cmd_count_blocking(path: str, *, stderr: IO[str] | None = None) -> int:
    """Run the count-blocking command; return the process exit code.

    Prints the derived blocking count to stdout. Writes a
    ``summary_mismatch`` diagnostic to *stderr* (defaults to
    ``sys.stderr``) when the agent-written "blocking" field disagrees with
    the derived count. Returns 2 on malformed input, 0 otherwise. Stdout
    is empty on exit 2: a caller that captured the number must treat a
    non-zero exit as "could not derive count" and fail the stage.
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
