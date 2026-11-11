"""Poll loop: call a condition until it resolves or the deadline passes.

The loop takes its clock and sleep as parameters so tests run instantly.
Verdicts map to exit codes in ``EXIT_CODES``: 0 passed, 1 failed/timed out,
2 the condition could not be evaluated.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from core.cli_errors import CLIError, ExitCode


class Outcome(str, Enum):
    """What one evaluation of a condition observed."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"


class Verdict(str, Enum):
    """How a whole poll ended."""

    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ERROR = "error"


EXIT_CODES: dict[Verdict, int] = {
    Verdict.PASSED: int(ExitCode.SUCCESS),
    Verdict.FAILED: int(ExitCode.ERROR),
    Verdict.TIMED_OUT: int(ExitCode.ERROR),
    Verdict.ERROR: int(ExitCode.USAGE),
}


@dataclass(frozen=True)
class Probe:
    """One observation: the outcome plus a short human-readable detail."""

    outcome: Outcome
    detail: str = ""


class ConditionError(CLIError):
    """The condition cannot be evaluated at all (bad input, tool missing, auth)."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message, ExitCode.USAGE, hint)


@dataclass(frozen=True)
class PollResult:
    """Terminal result of a poll."""

    verdict: Verdict
    polls: int
    elapsed_s: float
    detail: str = ""

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.verdict]


Condition = Callable[[], Probe]
TickHook = Callable[[int, Probe, float], None]

_OUTCOME_VERDICT = {
    Outcome.SUCCESS: Verdict.PASSED,
    Outcome.FAILURE: Verdict.FAILED,
}


def run_poll(
    condition: Condition,
    *,
    timeout: float,
    interval: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    on_tick: TickHook | None = None,
) -> PollResult:
    """Evaluate ``condition`` every ``interval`` seconds for up to ``timeout``.

    The condition is always evaluated at least once, so ``timeout=0`` is a
    single check. Each sleep is capped by the time left, so the poll never
    outlasts the deadline by a whole interval. A ``ConditionError`` ends the
    poll with ``Verdict.ERROR``.
    """
    start = clock()
    deadline = start + timeout
    polls = 0
    last = Probe(Outcome.PENDING)
    while True:
        try:
            last = condition()
        except ConditionError as exc:
            return PollResult(Verdict.ERROR, polls + 1, clock() - start, str(exc))
        polls += 1
        elapsed = clock() - start
        if on_tick is not None:
            on_tick(polls, last, elapsed)
        verdict = _OUTCOME_VERDICT.get(last.outcome)
        if verdict is not None:
            return PollResult(verdict, polls, elapsed, last.detail)
        remaining = deadline - clock()
        if remaining <= 0:
            return PollResult(Verdict.TIMED_OUT, polls, elapsed, last.detail)
        sleep(min(interval, remaining))
