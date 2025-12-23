from __future__ import annotations

from typing import Iterable, Iterator, List, TypeVar, Callable

T = TypeVar("T")


def chunked(seq: Iterable[T], size: int) -> Iterator[List[T]]:
    """Yield lists of up to `size` items from `seq`."""
    buf: List[T] = []
    for item in seq:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def apply_in_chunks(func: Callable[[List[T]], None], seq: Iterable[T], size: int) -> None:
    """Apply `func` to each chunk of items from `seq`."""
    for group in chunked(seq, size):
        func(group)

