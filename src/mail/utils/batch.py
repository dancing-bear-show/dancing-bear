from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from core.parallel import chunked

T = TypeVar("T")


def apply_in_chunks(func: Callable[[list[T]], None], seq: Iterable[T], size: int) -> None:
    """Apply `func` to each chunk of items from `seq`."""
    for group in chunked(seq, size):
        func(group)
