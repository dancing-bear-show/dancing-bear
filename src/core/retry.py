"""Reusable retry and backoff strategies for I/O-bound operations.

Network calls fail transiently — rate limits, transient 5xx, DNS hiccups. The
naive fix (retry immediately) amplifies the problem: when 16 threads all hit a
rate limit simultaneously (as in core/parallel.py), retrying in lockstep
thunders the herd right back into the same wall. Randomised backoff (jitter)
spreads retries across time, reducing collision probability without requiring
coordination between threads.

This module provides three complementary backoff functions and a single
well-parameterised ``@retry`` decorator. Its ``backoff`` parameter takes
either a float — used as the exponential multiplier — or a callable, so
callers can plug in any of the three functions (or a custom one) without a
separate wrapper per flavour.

Design choices:
- stdlib-only (functools, logging, random, time) — no dependency on anything
  optional or third-party.
- Backoff functions are pure, stateless, 0-indexed: easy to unit-test and
  compose.
- ``RetryExhaustedError`` carries both ``attempts`` and ``last_exception`` so
  callers that catch it can inspect or re-raise the underlying error without
  losing it.
"""

from __future__ import annotations

import functools
import logging
import random
import time
from dataclasses import dataclass
from typing import Callable

from core.secrets import mask_text

__all__ = [
    "RetryExhaustedError",
    "exponential_backoff",
    "jitter_backoff",
    "linear_backoff",
    "retry",
]

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class RetryExhaustedError(Exception):
    """Raised when all retry attempts have been consumed.

    Carries the attempt count and the last exception so callers can inspect
    or re-raise the underlying failure without losing it.

    The message text is masked, because this decorator is meant for API and
    other I/O callers whose exceptions routinely quote a request URL or an
    auth header -- printing an unmasked one leaks the credential into logs
    and tracebacks. ``last_exception`` keeps the original object intact for
    callers that need it.
    """

    def __init__(self, attempts: int, last_exception: Exception) -> None:
        self.attempts = attempts
        self.last_exception = last_exception
        detail = mask_text(str(last_exception))
        super().__init__(f"Failed after {attempts} attempt(s). Last error: {detail}")


# ---------------------------------------------------------------------------
# Backoff strategy functions
# ---------------------------------------------------------------------------


def exponential_backoff(
    attempt: int,
    base_delay: float = 1.0,
    multiplier: float = 2.0,
    max_delay: float = 60.0,
) -> float:
    """Return exponential backoff delay for the given 0-indexed attempt.

    Delay grows as ``base_delay * multiplier**attempt``, clamped to
    ``max_delay``.

    OverflowError from the exponentiation is treated as "grew past the cap"
    rather than propagating: ``2.0 ** 10_000`` raises, which would turn a
    capped strategy into a crash at exactly the point the cap was supposed
    to make it safe. Only a multiplier greater than 1 can overflow, so this
    genuinely means the value exceeded ``max_delay`` -- a shrinking or flat
    multiplier (``<= 1``) stays finite and takes the normal path, which
    matters because such a series never reaches the cap at all.
    """
    try:
        return min(base_delay * (multiplier ** attempt), max_delay)
    except OverflowError:
        return max_delay


def linear_backoff(
    attempt: int,
    base_delay: float = 1.0,
    increment: float = 1.0,
    max_delay: float = 60.0,
) -> float:
    """Return linear backoff delay for the given 0-indexed attempt.

    Delay grows as ``base_delay + attempt * increment``, clamped to
    ``max_delay``.
    """
    return min(base_delay + attempt * increment, max_delay)


def jitter_backoff(
    attempt: int,
    base_delay: float = 1.0,
    multiplier: float = 2.0,
    max_delay: float = 60.0,
    jitter_ratio: float = 0.3,
) -> float:
    """Return exponential-with-jitter delay for the given 0-indexed attempt.

    Computes an exponential base (clamped to ``max_delay``) then applies
    +/- ``jitter_ratio`` randomisation. The result is further clamped to a
    minimum of 0.1s so a large negative jitter on a short base never produces
    a near-zero delay. ``random`` is used here for timing spread, not
    cryptography — no security property is implied.
    """
    base = exponential_backoff(attempt, base_delay=base_delay, multiplier=multiplier, max_delay=max_delay)
    spread = base * jitter_ratio
    # random.uniform is for thundering-herd mitigation, not any security-sensitive purpose.
    jittered = base + random.uniform(-spread, spread)  # nosec B311
    return max(0.1, jittered)


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RetryPolicy:
    """The resolved parameters of one ``@retry`` decoration, plus the loop.

    Holding these as fields rather than closure variables keeps ``retry``
    itself a thin validating factory: the attempt loop, the backoff
    resolution and the failure reporting each become a separately readable
    (and separately testable) method instead of three nested scopes.
    """

    max_attempts: int
    delay: float
    backoff: float | Callable[[int], float]
    max_delay: float
    exceptions: tuple[type[Exception], ...]
    on_retry: Callable[[int, Exception], None] | None
    raise_on_exhausted: bool

    def notify(self, attempt: int, exc: Exception, func_name: str) -> None:
        """Report one about-to-retry attempt via callback or the default log."""
        if self.on_retry is not None:
            self.on_retry(attempt, exc)
            return
        # Masked: a retried call is usually an HTTP or API request, and its
        # exception text often quotes the URL or auth header that failed.
        _logger.warning(
            "Retry %d/%d for %s after %s: %s",
            attempt + 1,
            self.max_attempts - 1,
            func_name,
            type(exc).__name__,
            mask_text(str(exc)),
        )

    def sleep_duration(self, attempt: int) -> float:
        """Resolve the sleep for this attempt from the backoff parameter."""
        if callable(self.backoff):
            return self.backoff(attempt)
        return exponential_backoff(
            attempt, base_delay=self.delay, multiplier=self.backoff, max_delay=self.max_delay
        )

    def exhausted(self, last_exc: Exception | None):
        """Raise the terminal error after every attempt has been consumed.

        ``call`` only lands here after an attempt was caught -- either via the
        ``break`` on the last attempt, or by exhausting a loop that
        ``max_attempts >= 1`` guarantees ran at least once. Asserting that
        invariant lets both raises drop their ``# type: ignore``, and turns a
        future control-flow change that broke it into a clear AssertionError
        rather than a confusing ``raise None``.
        """
        assert last_exc is not None, "exhausted() called with no caught exception"
        if self.raise_on_exhausted:
            # `from None` suppresses the implicit __context__ chain. The
            # raise already sits outside the except block, so the context
            # happens to be clear today -- but the masked message is only
            # worth anything if an unmasked original cannot ride along in
            # the printed traceback, and that should not depend on where
            # this statement sits. last_exc stays reachable via
            # RetryExhaustedError.last_exception for callers that want it.
            raise RetryExhaustedError(self.max_attempts, last_exc) from None
        # Re-raising the original is the documented opt-out: the caller
        # asked for the underlying exception, so it is not masked here.
        raise last_exc

    def call(self, func: Callable, args: tuple, kwargs: dict):
        """Run ``func``, retrying per this policy until it succeeds or runs out."""
        last_exc: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                return func(*args, **kwargs)
            except self.exceptions as exc:
                last_exc = exc
                if attempt >= self.max_attempts - 1:
                    break
                self.notify(attempt, exc, func.__name__)
                time.sleep(self.sleep_duration(attempt))
        return self.exhausted(last_exc)


def retry(
    *,
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float | Callable[[int], float] = 2.0,
    max_delay: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[int, Exception], None] | None = None,
    raise_on_exhausted: bool = True,
) -> Callable:
    """Decorator that retries a function on specified exceptions.

    Parameters
    ----------
    max_attempts:
        Total number of attempts (1 = no retry).
    delay:
        Base delay in seconds for the first retry (attempt 0).
    backoff:
        When a ``float``, used as the exponential multiplier (standard
        exponential backoff). When a ``Callable[[int], float]``, called with
        the 0-indexed attempt number to compute the sleep duration — use this
        to pass ``jitter_backoff`` or ``linear_backoff`` directly.
    max_delay:
        Maximum sleep duration between retries when ``backoff`` is a float.
        Ignored when ``backoff`` is a callable (the callable controls its own
        cap).
    exceptions:
        Only these exception types trigger a retry; anything else propagates
        immediately.
    on_retry:
        Optional callback invoked with ``(attempt_number, exception)`` before
        each sleep. When provided, the default ``logging`` call is suppressed.
    raise_on_exhausted:
        When ``True`` (default), raise ``RetryExhaustedError`` after the last
        attempt. When ``False``, re-raise the last exception directly.

    Raises:
        ValueError: If ``max_attempts`` is less than 1. A zero or negative
            value would make the decorated function never run at all and
            fail with RetryExhaustedError carrying no underlying error --
            a silent no-op that is far harder to diagnose than a loud
            rejection at decoration time.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")

    policy = _RetryPolicy(
        max_attempts=max_attempts,
        delay=delay,
        backoff=backoff,
        max_delay=max_delay,
        exceptions=exceptions,
        on_retry=on_retry,
        raise_on_exhausted=raise_on_exhausted,
    )

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return policy.call(func, args, kwargs)
        return wrapper
    return decorator
