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
    - Any finding lacks a "severity" field, has a non-string "severity",
      or has an empty or whitespace-only "severity".
    - The "blocking" key is present with a value that is not absent: null,
      bool (JSON true/false), float, string, or negative integer all exit 2.
      Only a plain Python ``int`` (``type(x) is int``) that is >= 0 is
      accepted; bool subclasses int so ``isinstance`` alone is not sufficient.
      Absent "blocking" is allowed (summary field, not required).
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = exc.strerror if isinstance(exc, OSError) else str(exc)
        raise CountBlockingError(f"cannot read {path!r}: {msg}") from exc
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
        _validate_finding(i, item)
    blocking_raw = doc.get("blocking")
    if "blocking" in doc:
        _validate_blocking(blocking_raw)
    derived = sum(
        1
        for f in findings_raw
        if f.get("severity") not in _NON_BLOCKING_SEVERITIES
    )
    reported: int | None = None
    if isinstance(blocking_raw, int) and not isinstance(blocking_raw, bool):
        reported = blocking_raw
    return derived, reported


def _validate_finding(i: int, item: object) -> None:
    """Raise :class:`CountBlockingError` if findings[*i*] is malformed."""
    if not isinstance(item, dict):
        raise CountBlockingError(
            f"findings[{i}] is not an object, got {type(item).__name__}"
        )
    sev = item.get("severity")
    if sev is None:
        raise CountBlockingError(f"findings[{i}] is missing the 'severity' field")
    if not isinstance(sev, str):
        raise CountBlockingError(
            f"findings[{i}].severity must be a string, got {type(sev).__name__}"
        )
    if not sev.strip():
        raise CountBlockingError(f"findings[{i}].severity must be non-empty")


def _validate_blocking(value: object) -> None:
    """Raise :class:`CountBlockingError` if the 'blocking' field is malformed.

    Absent is allowed (caller only calls this when the key is present).
    Accepts only a plain non-negative ``int``; bools are rejected first
    (``bool`` subclasses ``int`` in Python), then any non-int, then negatives.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CountBlockingError(
            f"'blocking' must be a non-negative integer, "
            f"got {type(value).__name__!r} {value!r}"
        )


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
