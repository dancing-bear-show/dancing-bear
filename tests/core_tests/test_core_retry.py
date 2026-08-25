"""Unit tests for core/retry.py."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class TestExponentialBackoff(unittest.TestCase):
    """exponential_backoff grows as base*multiplier**attempt and clamps to max_delay."""

    def setUp(self) -> None:
        from core.retry import exponential_backoff
        self.fn = exponential_backoff

    def test_attempt_zero(self) -> None:
        self.assertAlmostEqual(self.fn(0), 1.0)

    def test_attempt_one(self) -> None:
        self.assertAlmostEqual(self.fn(1), 2.0)

    def test_attempt_two(self) -> None:
        self.assertAlmostEqual(self.fn(2), 4.0)

    def test_custom_base_and_multiplier(self) -> None:
        self.assertAlmostEqual(self.fn(3, base_delay=0.5, multiplier=3.0), 13.5)

    def test_clamps_to_max_delay(self) -> None:
        result = self.fn(100, max_delay=10.0)
        self.assertAlmostEqual(result, 10.0)

    def test_max_delay_exact_boundary(self) -> None:
        # attempt 3 with base=1, mult=2: 8.0; max=8 => exactly 8
        self.assertAlmostEqual(self.fn(3, base_delay=1.0, multiplier=2.0, max_delay=8.0), 8.0)


class TestLinearBackoff(unittest.TestCase):
    """linear_backoff grows linearly and clamps to max_delay."""

    def setUp(self) -> None:
        from core.retry import linear_backoff
        self.fn = linear_backoff

    def test_attempt_zero(self) -> None:
        self.assertAlmostEqual(self.fn(0), 1.0)

    def test_attempt_one(self) -> None:
        self.assertAlmostEqual(self.fn(1), 2.0)

    def test_attempt_four(self) -> None:
        self.assertAlmostEqual(self.fn(4), 5.0)

    def test_custom_increment(self) -> None:
        self.assertAlmostEqual(self.fn(3, base_delay=2.0, increment=0.5), 3.5)

    def test_clamps_to_max_delay(self) -> None:
        result = self.fn(100, max_delay=5.0)
        self.assertAlmostEqual(result, 5.0)


class TestJitterBackoff(unittest.TestCase):
    """jitter_backoff stays within expected bounds and never drops below 0.1s."""

    def setUp(self) -> None:
        from core.retry import jitter_backoff
        self.fn = jitter_backoff

    def test_within_jitter_bounds_attempt_zero(self) -> None:
        # base=1.0, jitter_ratio=0.3 → range [0.7, 1.3]
        results = [self.fn(0) for _ in range(200)]
        for v in results:
            self.assertGreaterEqual(v, 0.7)
            self.assertLessEqual(v, 1.3)

    def test_within_jitter_bounds_attempt_two(self) -> None:
        # base=4.0, jitter_ratio=0.3 → range [2.8, 5.2]
        results = [self.fn(2) for _ in range(200)]
        for v in results:
            self.assertGreaterEqual(v, 2.8)
            self.assertLessEqual(v, 5.2)

    def test_minimum_floor_of_0_1(self) -> None:
        # Patch core.retry.random.uniform to return a maximally negative value so
        # the 0.1s floor clamp is exercised — no global RNG mutation.
        with patch("core.retry.random.uniform", return_value=-0.003):
            results = [self.fn(0, base_delay=0.01, max_delay=0.01) for _ in range(100)]
        for v in results:
            self.assertGreaterEqual(v, 0.1)

    def test_respects_max_delay_before_jitter(self) -> None:
        # With max_delay=2.0 and jitter_ratio=0.0, result should be exactly 2.0 for large attempts.
        result = self.fn(100, max_delay=2.0, jitter_ratio=0.0)
        self.assertAlmostEqual(result, 2.0)

    def test_produces_variation(self) -> None:
        # jitter should not produce the same value every time (with reasonable prob).
        results = {self.fn(1) for _ in range(50)}
        self.assertGreater(len(results), 1, "jitter produced no variation over 50 samples")


class TestRetryDecoratorSuccess(unittest.TestCase):
    """@retry passes through immediately when no exception is raised."""

    def test_succeeds_first_try_no_sleep(self) -> None:
        from core.retry import retry

        calls = []

        @retry(max_attempts=3)
        def fn() -> str:
            calls.append(1)
            return "ok"

        with patch("core.retry.time.sleep") as mock_sleep:
            result = fn()

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 1)
        mock_sleep.assert_not_called()


class TestRetryDecoratorRetryThenSucceed(unittest.TestCase):
    """@retry retries on failure then succeeds when a later attempt passes."""

    def test_retries_then_succeeds(self) -> None:
        from core.retry import retry

        attempt_count = [0]

        @retry(max_attempts=3, delay=0.1)
        def flaky() -> str:
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                raise ValueError("not yet")
            return "done"

        with patch("core.retry.time.sleep"):
            result = flaky()

        self.assertEqual(result, "done")
        self.assertEqual(attempt_count[0], 3)

    def test_sleep_called_between_attempts(self) -> None:
        from core.retry import retry

        attempt_count = [0]

        @retry(max_attempts=3, delay=1.0, backoff=2.0)
        def flaky() -> str:
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                raise IOError("boom")
            return "ok"

        with patch("core.retry.time.sleep") as mock_sleep:
            flaky()

        # 3 attempts → 2 sleeps (between attempt 0→1 and 1→2)
        self.assertEqual(mock_sleep.call_count, 2)


class TestRetryDecoratorExhausted(unittest.TestCase):
    """@retry raises RetryExhaustedError when all attempts fail."""

    def test_raises_retry_exhausted_error(self) -> None:
        from core.retry import RetryExhaustedError, retry

        @retry(max_attempts=3, delay=0.1)
        def always_fails() -> None:
            raise RuntimeError("permanent")

        with patch("core.retry.time.sleep"):
            with self.assertRaises(RetryExhaustedError) as ctx:
                always_fails()

        err = ctx.exception
        self.assertEqual(err.attempts, 3)
        self.assertIsInstance(err.last_exception, RuntimeError)
        self.assertIn("3", str(err))

    def test_error_message_contains_last_exception(self) -> None:
        from core.retry import RetryExhaustedError, retry

        @retry(max_attempts=2, delay=0.0)
        def fails() -> None:
            raise ValueError("bad input")

        with patch("core.retry.time.sleep"):
            with self.assertRaises(RetryExhaustedError) as ctx:
                fails()

        self.assertIn("bad input", str(ctx.exception))


class TestRetryDecoratorRaiseOnExhaustedFalse(unittest.TestCase):
    """raise_on_exhausted=False re-raises the original exception type."""

    def test_reraises_original_exception(self) -> None:
        from core.retry import retry

        @retry(max_attempts=2, delay=0.0, raise_on_exhausted=False)
        def fails() -> None:
            raise TypeError("original")

        with patch("core.retry.time.sleep"):
            with self.assertRaises(TypeError) as ctx:
                fails()

        self.assertIn("original", str(ctx.exception))

    def test_does_not_raise_retry_exhausted(self) -> None:
        from core.retry import retry

        @retry(max_attempts=2, delay=0.0, raise_on_exhausted=False)
        def fails() -> None:
            raise OSError("disk")

        with patch("core.retry.time.sleep"):
            with self.assertRaises(OSError):
                fails()


class TestRetryDecoratorExceptionFilter(unittest.TestCase):
    """Only listed exception types trigger a retry; others propagate immediately."""

    def test_unlisted_exception_propagates_without_retry(self) -> None:
        from core.retry import retry

        call_count = [0]

        @retry(max_attempts=5, exceptions=(ValueError,))
        def raises_key_error() -> None:
            call_count[0] += 1
            raise KeyError("unlisted")

        with patch("core.retry.time.sleep"):
            with self.assertRaises(KeyError):
                raises_key_error()

        # Should have been called exactly once — no retry for unlisted exception.
        self.assertEqual(call_count[0], 1)

    def test_listed_exception_triggers_retry(self) -> None:
        from core.retry import RetryExhaustedError, retry

        call_count = [0]

        @retry(max_attempts=3, exceptions=(ValueError,), delay=0.0)
        def raises_value_error() -> None:
            call_count[0] += 1
            raise ValueError("listed")

        with patch("core.retry.time.sleep"):
            with self.assertRaises(RetryExhaustedError):
                raises_value_error()

        self.assertEqual(call_count[0], 3)


class TestRetryDecoratorOnRetryCallback(unittest.TestCase):
    """on_retry callback fires with the correct attempt number and exception."""

    def test_callback_fires_with_correct_args(self) -> None:
        from core.retry import RetryExhaustedError, retry

        recorded: list[tuple[int, Exception]] = []

        def on_retry(attempt: int, exc: Exception) -> None:
            recorded.append((attempt, exc))

        @retry(max_attempts=3, delay=0.0, on_retry=on_retry)
        def fails() -> None:
            raise IOError("net")

        with patch("core.retry.time.sleep"):
            with self.assertRaises(RetryExhaustedError):
                fails()

        # 3 attempts → 2 retries (attempt 0 and 1 fire callback; attempt 2 exhausts)
        self.assertEqual(len(recorded), 2)
        self.assertEqual(recorded[0][0], 0)
        self.assertEqual(recorded[1][0], 1)
        self.assertIsInstance(recorded[0][1], IOError)

    def test_callback_suppresses_default_log(self) -> None:
        from core.retry import RetryExhaustedError, retry

        callback = MagicMock()

        @retry(max_attempts=2, delay=0.0, on_retry=callback)
        def fails() -> None:
            raise RuntimeError("x")

        with patch("core.retry.time.sleep"), patch("core.retry._logger") as mock_log:
            with self.assertRaises(RetryExhaustedError):
                fails()

        mock_log.warning.assert_not_called()
        callback.assert_called_once()


class TestRetryDecoratorCallableBackoff(unittest.TestCase):
    """When backoff is callable it is invoked with the attempt number."""

    def test_callable_backoff_is_called(self) -> None:
        from core.retry import RetryExhaustedError, retry

        strategy = MagicMock(return_value=0.5)

        @retry(max_attempts=3, backoff=strategy)
        def fails() -> None:
            raise RuntimeError("x")

        with patch("core.retry.time.sleep") as mock_sleep:
            with self.assertRaises(RetryExhaustedError):
                fails()

        # 2 sleeps for 3 attempts
        self.assertEqual(strategy.call_count, 2)
        strategy.assert_any_call(0)
        strategy.assert_any_call(1)
        mock_sleep.assert_called_with(0.5)


class TestRetryDecoratorPreservesMetadata(unittest.TestCase):
    """@retry preserves the wrapped function's __name__ and __doc__."""

    def test_wraps_preserves_name(self) -> None:
        from core.retry import retry

        @retry(max_attempts=1)
        def my_function() -> None:
            """My docstring."""

        self.assertEqual(my_function.__name__, "my_function")
        self.assertEqual(my_function.__doc__, "My docstring.")


class TestHttpSleepForRetryWithJitter(unittest.TestCase):
    """_sleep_for_retry: jitter never reduces delay below a server-specified Retry-After."""

    def _make_requests_stub(self) -> types.ModuleType:
        """Build a minimal requests stub without touching sys.modules."""
        requests = types.ModuleType("requests")
        exceptions_mod = types.ModuleType("requests.exceptions")

        class _ConnError(Exception):
            pass

        class _Timeout(Exception):
            pass

        class _HTTPError(Exception):
            pass

        exceptions_mod.ConnectionError = _ConnError  # type: ignore[attr-defined]
        exceptions_mod.Timeout = _Timeout  # type: ignore[attr-defined]
        exceptions_mod.HTTPError = _HTTPError  # type: ignore[attr-defined]
        requests.exceptions = exceptions_mod  # type: ignore[attr-defined]

        class _Session:
            def request(self, *args, **kwargs):
                pass

        requests.Session = _Session  # type: ignore[attr-defined]
        return requests

    def _make_client(self):
        import importlib
        requests_stub = self._make_requests_stub()

        # Inject stub and schedule teardown so sys.modules is always restored.
        original = sys.modules.get("requests")
        sys.modules["requests"] = requests_stub
        if original is None:
            self.addCleanup(sys.modules.pop, "requests", None)
        else:
            self.addCleanup(sys.modules.__setitem__, "requests", original)

        import core.http as http_mod
        importlib.reload(http_mod)
        # Restore http_mod to its real state after this test.
        self.addCleanup(importlib.reload, http_mod)

        return http_mod.HttpClient("https://example.com", session=requests_stub.Session())

    def test_retry_after_floor_held(self) -> None:
        """Delay must be >= retry_after regardless of jitter."""
        client = self._make_client()
        retry_after = 30

        sleep_calls = []
        with patch("core.http.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
            for attempt in range(10):
                client._sleep_for_retry(attempt, retry_after)

        for delay in sleep_calls:
            self.assertGreaterEqual(
                delay, retry_after,
                f"delay {delay} dropped below retry_after={retry_after}",
            )

    def test_no_retry_after_uses_jitter(self) -> None:
        """Without Retry-After the delay comes from jitter_backoff (max 10s)."""
        client = self._make_client()

        sleep_calls = []
        with patch("core.http.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
            for attempt in range(5):
                client._sleep_for_retry(attempt, None)

        for delay in sleep_calls:
            self.assertGreaterEqual(delay, 0.1)
            self.assertLessEqual(delay, 10.0 * 1.3 + 0.01)  # max_delay + max jitter

    def test_jitter_delay_never_exceeds_max_when_no_retry_after(self) -> None:
        """Jitter does not push delay beyond max_delay * (1 + jitter_ratio)."""
        client = self._make_client()
        upper = 10.0 * (1.0 + 0.3) + 0.01  # generous upper bound

        sleep_calls = []
        with patch("core.http.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
            for attempt in range(20):
                client._sleep_for_retry(attempt, None)

        for delay in sleep_calls:
            self.assertLessEqual(delay, upper, f"delay {delay} exceeded expected upper bound")


if __name__ == "__main__":
    unittest.main()


class TestPRFeedbackFixes(unittest.TestCase):
    """Regressions found in review of PR #237."""

    def test_large_attempt_returns_cap_instead_of_overflowing(self) -> None:
        # 2.0 ** 10_000 raises OverflowError if evaluated before the clamp,
        # turning a capped strategy into a crash at exactly the point the cap
        # was meant to make it safe.
        from core.retry import exponential_backoff

        self.assertEqual(exponential_backoff(10_000, max_delay=60.0), 60.0)
        self.assertEqual(exponential_backoff(1_000_000, max_delay=5.0), 5.0)

    def test_large_attempt_is_safe_for_jitter_too(self) -> None:
        from core.retry import jitter_backoff

        value = jitter_backoff(10_000, max_delay=10.0)
        self.assertGreaterEqual(value, 0.1)
        self.assertLessEqual(value, 13.0)

    def test_non_positive_max_attempts_is_rejected(self) -> None:
        # A zero/negative value previously produced a decorated function that
        # never ran and failed with RetryExhaustedError carrying no error.
        from core.retry import retry

        for bad in (0, -1):
            with self.subTest(max_attempts=bad):
                with self.assertRaises(ValueError):
                    retry(max_attempts=bad)

    def test_max_attempts_of_one_still_runs_once(self) -> None:
        from core.retry import retry

        calls = []

        @retry(max_attempts=1)
        def once() -> str:
            calls.append(1)
            return "ok"

        self.assertEqual(once(), "ok")
        self.assertEqual(len(calls), 1)


class TestNonGrowingMultipliers(unittest.TestCase):
    """A multiplier <= 1 never reaches the cap, so it must not be shortcut.

    The first overflow guard short-circuited to max_delay past a fixed attempt
    ceiling regardless of multiplier, so exponential_backoff(512, multiplier=1.0)
    returned the cap instead of base_delay — a flat series reported as maxed out.
    """

    def test_flat_multiplier_returns_base_delay(self) -> None:
        from core.retry import exponential_backoff

        self.assertEqual(
            exponential_backoff(512, base_delay=1.0, multiplier=1.0, max_delay=60.0),
            1.0,
        )

    def test_shrinking_multiplier_decays_toward_zero(self) -> None:
        from core.retry import exponential_backoff

        value = exponential_backoff(
            512, base_delay=1.0, multiplier=0.5, max_delay=60.0
        )
        self.assertLess(value, 1.0)
        self.assertGreaterEqual(value, 0.0)

    def test_growing_multiplier_still_caps(self) -> None:
        from core.retry import exponential_backoff

        self.assertEqual(
            exponential_backoff(10_000, multiplier=2.0, max_delay=60.0), 60.0
        )

    def test_normal_series_is_unaffected(self) -> None:
        from core.retry import exponential_backoff

        self.assertEqual(exponential_backoff(0, max_delay=60.0), 1.0)
        self.assertEqual(exponential_backoff(3, max_delay=60.0), 8.0)


class TestHttpBackoffCeiling(unittest.TestCase):
    """_sleep_for_retry must not exceed the ceiling the old code guaranteed.

    jitter_backoff applies its +/-30% band after its own clamp, so a 10s
    max_delay yields up to 13s. The previous min(2 ** attempt, 10) was a hard
    10s ceiling, so HttpClient clamps a second time.
    """

    def _sleeps_for(self, attempt: int, retry_after=None, samples: int = 400):
        from unittest.mock import patch

        from core.http import HttpClient

        client = HttpClient.__new__(HttpClient)
        recorded: list[float] = []
        with patch("core.http.time.sleep", side_effect=recorded.append):
            for _ in range(samples):
                client._sleep_for_retry(attempt, retry_after)
        return recorded

    def test_delay_never_exceeds_ten_seconds(self) -> None:
        for delay in self._sleeps_for(attempt=20):
            self.assertLessEqual(delay, 10.0)

    def test_jitter_still_varies_below_the_ceiling(self) -> None:
        # Clamping must not flatten every sample onto the ceiling — that would
        # reintroduce the lockstep retries jitter exists to prevent.
        delays = self._sleeps_for(attempt=20)
        self.assertGreater(len(set(delays)), 1)
        self.assertTrue(any(d < 10.0 for d in delays))

    def test_retry_after_may_exceed_the_ceiling(self) -> None:
        # The server's instruction wins over our own cap.
        for delay in self._sleeps_for(attempt=1, retry_after=30, samples=20):
            self.assertEqual(delay, 30)
