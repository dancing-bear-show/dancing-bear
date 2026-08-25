"""Reusable retry and backoff strategies for I/O-bound operations.

Network calls fail transiently — rate limits, transient 5xx, DNS hiccups. The
naive fix (retry immediately) amplifies the problem: when 16 threads all hit a
rate limit simultaneously (as in core/parallel.py), retrying in lockstep
thunders the herd right back into the same wall. Randomised backoff (jitter)
spreads retries across time, reducing collision probability without requiring
coordination between threads.

This module provides three complementary backoff functions and a single
well-parameterised ``@retry`` decorator. The decorator accepts a callable
``backoff`` strategy so callers can plug in any of the three functions (or a
custom one) without a separate wrapper per flavour.

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
from typing import Callable

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
    """

    def __init__(self, attempts: int, last_exception: Exception) -> None:
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(f"Failed after {attempts} attempt(s). Last error: {last_exception}")


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

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt >= max_attempts - 1:
                        break
                    if on_retry is not None:
                        on_retry(attempt, exc)
                    else:
                        _logger.warning(
                            "Retry %d/%d for %s after %s: %s",
                            attempt + 1,
                            max_attempts - 1,
                            func.__name__,
                            type(exc).__name__,
                            exc,
                        )
                    if callable(backoff):
                        sleep_for = backoff(attempt)
                    else:
                        sleep_for = exponential_backoff(
                            attempt, base_delay=delay, multiplier=backoff, max_delay=max_delay
                        )
                    time.sleep(sleep_for)
            if raise_on_exhausted:
                raise RetryExhaustedError(max_attempts, last_exc)  # type: ignore[arg-type]
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator
