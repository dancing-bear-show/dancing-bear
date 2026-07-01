from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import TypeVar

from core.parallel import chunked as _chunked_seq

T = TypeVar("T")


def chunked(seq: Iterable[T], size: int) -> Iterator[list[T]]:
    """Yield lists of up to `size` items from `seq`."""
    items: Sequence[T] = seq if isinstance(seq, (list, tuple)) else list(seq)
    return _chunked_seq(items, size)


def apply_in_chunks(func: Callable[[list[T]], None], seq: Iterable[T], size: int) -> None:
    """Apply `func` to each chunk of items from `seq`."""
    for group in chunked(seq, size):
        func(group)
