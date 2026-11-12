"""Poll loop: verdicts, deadline handling, tick hook. Clock and sleep are injected."""

from __future__ import annotations

import unittest

from core.cli_errors import ExitCode
from monitor_poll.engine import (
    ConditionError,
    Outcome,
    PollResult,
    Probe,
    Verdict,
    run_poll,
)


class FakeClock:
    """Deterministic clock whose ``sleep`` advances time without waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def scripted(*outcomes: Outcome):
    """A condition replaying ``outcomes`` in order, then repeating the last."""
    calls = {"n": 0}

    def condition() -> Probe:
        idx = min(calls["n"], len(outcomes) - 1)
        calls["n"] += 1
        return Probe(outcomes[idx], f"call {calls['n']}")

    return condition, calls


class RunPollTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()

    def _run(self, condition, **kwargs) -> PollResult:
        kwargs.setdefault("timeout", 100)
        kwargs.setdefault("interval", 5)
        return run_poll(condition, clock=self.clock, sleep=self.clock.sleep, **kwargs)

    def test_succeeds_immediately_without_sleeping(self):
        cond, calls = scripted(Outcome.SUCCESS)
        result = self._run(cond)
        self.assertEqual(result.verdict, Verdict.PASSED)
        self.assertEqual((result.polls, calls["n"]), (1, 1))
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(result.exit_code, int(ExitCode.SUCCESS))

    def test_pending_then_success_sleeps_one_interval_per_pending(self):
        cond, _ = scripted(Outcome.PENDING, Outcome.PENDING, Outcome.SUCCESS)
        result = self._run(cond, interval=5)
        self.assertEqual(result.verdict, Verdict.PASSED)
        self.assertEqual(result.polls, 3)
        self.assertEqual(self.clock.sleeps, [5, 5])
        self.assertEqual(result.elapsed_s, 10)
        self.assertEqual(result.detail, "call 3")

    def test_failure_outcome_ends_poll_with_exit_one(self):
        cond, _ = scripted(Outcome.PENDING, Outcome.FAILURE)
        result = self._run(cond)
        self.assertEqual(result.verdict, Verdict.FAILED)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.polls, 2)

    def test_timeout_keeps_last_detail_and_exits_one(self):
        cond, _ = scripted(Outcome.PENDING)
        result = self._run(cond, timeout=12, interval=5)
        self.assertEqual(result.verdict, Verdict.TIMED_OUT)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.detail, f"call {result.polls}")

    def test_last_sleep_is_capped_by_remaining_time(self):
        cond, _ = scripted(Outcome.PENDING)
        self._run(cond, timeout=12, interval=5)
        self.assertEqual(self.clock.sleeps, [5, 5, 2])

    def test_timeout_zero_checks_exactly_once(self):
        cond, calls = scripted(Outcome.PENDING)
        result = self._run(cond, timeout=0)
        self.assertEqual(result.verdict, Verdict.TIMED_OUT)
        self.assertEqual((result.polls, calls["n"]), (1, 1))
        self.assertEqual(self.clock.sleeps, [])

    def test_condition_error_yields_error_verdict_with_exit_two(self):
        def broken() -> Probe:
            raise ConditionError("gh not installed")

        result = self._run(broken)
        self.assertEqual(result.verdict, Verdict.ERROR)
        self.assertEqual(result.detail, "gh not installed")
        self.assertEqual(result.exit_code, 2)

    def test_condition_error_after_pending_counts_the_failed_poll(self):
        seq = iter([Probe(Outcome.PENDING), None])

        def flaky() -> Probe:
            item = next(seq)
            if item is None:
                raise ConditionError("auth failed")
            return item

        result = self._run(flaky)
        self.assertEqual(result.verdict, Verdict.ERROR)
        self.assertEqual(result.polls, 2)

    def test_unexpected_exception_propagates(self):
        def boom() -> Probe:
            raise RuntimeError("bug")

        with self.assertRaises(RuntimeError):
            self._run(boom)

    def test_on_tick_sees_every_evaluation_including_the_last(self):
        cond, _ = scripted(Outcome.PENDING, Outcome.SUCCESS)
        seen: list[tuple[int, Outcome, float]] = []
        self._run(cond, on_tick=lambda n, probe, el: seen.append((n, probe.outcome, el)))
        self.assertEqual(seen, [(1, Outcome.PENDING, 0), (2, Outcome.SUCCESS, 5)])


if __name__ == "__main__":
    unittest.main()
