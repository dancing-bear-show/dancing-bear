"""Invariant-check framework for validating proposed changes before applying them.

The plan → dry-run → apply pattern this repo follows requires validating that a
proposed change set looks sane before any mutation occurs.  Each domain
(mail filter sync, calendar schedule apply, phone layout push) previously
hand-rolled its own sanity checks — or skipped them entirely.  This module
provides one vocabulary so callers get consistent, composable pre-apply
validation without rebuilding the plumbing.

This is deliberately small and orthogonal to the job queue in
``src/worker/queue_ops.py``, which owns job state, atomic persistence, retry,
and crash recovery.  ``preflight`` is stateless: given a change list, a
baseline, and a set of check functions, it returns a report.  No disk I/O,
no job IDs.

Usage pattern::

    from core.preflight import evaluate_invariants

    def no_mass_deletes(changes, baseline):
        total = baseline.get("total", len(changes))
        bad = [c for c in changes if c.get("op") == "delete"]
        if total and len(bad) > total / 2:
            return "deletes_more_than_half", bad
        return "deletes_more_than_half", []

    report = evaluate_invariants(changes, baseline, [no_mass_deletes])
    if not report.passed:
        print(report.summary())
        sys.exit(1)
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.secrets import mask_text

__all__ = [
    "InvariantViolation",
    "PreflightReport",
    "CheckFn",
    "evaluate_invariants",
]

# A check function receives the proposed change list and a baseline dict and
# returns a (code, offending_samples) tuple.  A non-empty sample list signals
# a violation.  Define checks as plain functions — no subclassing required.
CheckFn = Callable[
    [list[dict[str, Any]], dict[str, Any]],
    tuple[str, list[dict[str, Any]]],
]


@dataclass(frozen=True)
class InvariantViolation:
    """A single invariant that failed, with evidence."""

    code: str
    """Stable machine-readable identifier, e.g. ``"deletes_more_than_half"``."""

    message: str
    """Human-readable description of what the invariant checks."""

    samples: list[dict[str, Any]]
    """Representative offending items (capped by ``max_samples``)."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "code": self.code,
            "message": self.message,
            "samples": self.samples,
        }


@dataclass(frozen=True)
class PreflightReport:
    """Aggregate result of running all invariant checks."""

    passed: bool
    violations: list[InvariantViolation]
    tallies: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "tallies": self.tallies,
        }

    def summary(self) -> str:
        """Return a short human-readable summary suitable for CLI output."""
        total = self.tallies.get("total_changes", "?")
        n_violations = len(self.violations)
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"{status}: {total} {_plural(total, 'change')}, "
            f"{n_violations} {_plural(n_violations, 'violation')}"
        ]
        for v in self.violations:
            n_samples = len(v.samples)
            lines.append(
                f"  [{v.code}] {v.message} "
                f"({n_samples} {_plural(n_samples, 'sample')})"
            )
        return "\n".join(lines)


def _plural(count: object, noun: str) -> str:
    """Return ``noun`` pluralized for ``count`` (regular -s nouns only)."""
    return noun if count == 1 else f"{noun}s"


def _code_to_message(code: str) -> str:
    """Derive a human-readable message from a snake_case code."""
    return code.replace("_", " ")


def evaluate_invariants(
    changes: list[dict[str, Any]],
    baseline: dict[str, Any],
    checks: list[CheckFn],
    *,
    max_samples: int = 10,
    messages: dict[str, str] | None = None,
) -> PreflightReport:
    """Run every check over the proposed changes and return a consolidated report.

    All checks run regardless of earlier failures — the caller needs the full
    picture, not just the first violation.

    Args:
        changes: The proposed change list, each item a ``dict[str, Any]``.
        baseline: Contextual data for checks (e.g. total item count in the
            mailbox so a check can compute deletion percentages).
        checks: Callables conforming to :data:`CheckFn`.
        max_samples: Maximum number of offending items kept per violation.
        messages: Optional mapping from violation code to human-readable message.
            When absent for a code, the message is derived from the code itself.

    Returns:
        A :class:`PreflightReport` with ``passed=True`` iff no violations were
        found.  A check that raises is recorded as a violation with a distinct
        ``check_error`` code so buggy checks surface loudly rather than silently
        passing.
    """
    violations: list[InvariantViolation] = []

    for check in checks:
        try:
            code, offending = check(changes, baseline)
        except Exception as exc:  # nosec B112 - handler continues; the error is recorded as a violation, never swallowed
            error_code = "check_error"
            error_message = (messages or {}).get(
                error_code, _code_to_message(error_code)
            )
            # This single sample is deliberately exempt from max_samples: it is
            # not one offending item among many but the sole diagnostic for a
            # check that crashed. Truncating it under max_samples=0 would report
            # "a check failed" with no way to tell which one or why.
            #
            # Both the message and the traceback are masked. A check commonly
            # wraps an HTTP or API call, so its exception text and the source
            # lines quoted in the traceback can carry a URL query token or auth
            # header -- and this report is built to be serialized via to_dict().
            violations.append(
                InvariantViolation(
                    code=error_code,
                    message=error_message,
                    samples=[
                        {
                            "check": getattr(check, "__name__", repr(check)),
                            "error": mask_text(str(exc)),
                            "traceback": mask_text(traceback.format_exc()),
                        }
                    ],
                )
            )
            continue

        if not offending:
            continue

        message = (messages or {}).get(code) or _code_to_message(code)
        violations.append(
            InvariantViolation(
                code=code,
                message=message,
                samples=offending[:max_samples],
            )
        )

    tallies: dict[str, Any] = {
        "total_changes": len(changes),
        "violation_count": len(violations),
    }

    return PreflightReport(
        passed=len(violations) == 0,
        violations=violations,
        tallies=tallies,
    )
