from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import TypeVar

from core.parallel import chunked
from core.retry import exponential_backoff

T = TypeVar("T")


def apply_in_chunks(func: Callable[[list[T]], None], seq: Iterable[T], size: int) -> None:
    """Apply `func` to each chunk of items from `seq`."""
    for group in chunked(seq, size):
        func(group)


def delete_with_retry(
    delete: Callable[[], object],
    *,
    on_failure: Callable[[Exception | None], None],
    attempts: int = 3,
) -> bool:
    """Call `delete` up to `attempts` times, backing off between attempts.

    Returns True on the first success. After the last failure, calls
    `on_failure` with the final exception and returns False.

    Raises:
        ValueError: If `attempts` is less than 1, which would report a
            failure without ever trying.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1, got {attempts}")
    last_err: Exception | None = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(exponential_backoff(attempt - 1, base_delay=1.5, multiplier=2.0))
        try:
            delete()
            return True
        except Exception as exc:
            last_err = exc
    on_failure(last_err)
    return False
