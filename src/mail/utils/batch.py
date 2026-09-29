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
    """Call `delete` up to `attempts` times with exponential backoff.

    Returns True on the first success. After the last failure, calls
    `on_failure` with the final exception and returns False.
    """
    last_err: Exception | None = None
    for attempt in range(attempts):
        try:
            delete()
            return True
        except Exception as exc:
            last_err = exc
            time.sleep(exponential_backoff(attempt, base_delay=1.5, multiplier=2.0))
    on_failure(last_err)
    return False
