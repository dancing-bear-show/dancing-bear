"""Lightweight parallel execution helpers (stdlib-only)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

__all__ = ["chunked", "parallel_map"]

T = TypeVar("T")
R = TypeVar("R")


def chunked(seq: Sequence[T], size: int) -> Iterator[list[T]]:
    """Yield lists of up to ``size`` elements from ``seq``."""
    n = max(1, int(size or 1))
    for i in range(0, len(seq or []), n):
        yield list(seq[i : i + n])


def parallel_map(
    func: Callable[[T], R],
    items: Iterable[T],
    *,
    max_workers: int = 16,
    return_exceptions: bool = False,
) -> list[R | Exception | None]:
    """Run ``func`` over ``items`` in a thread pool; return order-preserving results.

    On per-item failure: inserts the exception if ``return_exceptions=True``,
    otherwise inserts ``None``.
    """
    it_list: list[T] = list(items)
    n = max(1, int(max_workers or 1))
    results: list[R | Exception | None] = [None] * len(it_list)
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(func, it): idx for idx, it in enumerate(it_list)}
        for fut in as_completed(futs):
            idx = futs[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:  # nosec B110 - capture per-item failures, caller decides
                results[idx] = e if return_exceptions else None
    return results
