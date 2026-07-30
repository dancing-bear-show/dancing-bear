"""Shared collection utilities.

Generic functions for list manipulation, deduplication, etc.
"""
from __future__ import annotations

from typing import Callable, Hashable, List, Optional, TypeVar

__all__ = ["dedupe"]

T = TypeVar("T")


def dedupe(items: List[T], key_fn: Optional[Callable[[T], Hashable]] = None) -> List[T]:
    """Remove duplicates from a list while preserving order.

    Args:
        items: List of items to deduplicate.
        key_fn: Optional function to extract a hashable key from each item.
                If None, uses the item itself as the key.

    Returns:
        Deduplicated list with original order preserved.

    Examples:
        dedupe([1, 2, 2, 3, 1]) -> [1, 2, 3]
        dedupe([{'a': 1}, {'a': 1}, {'a': 2}], key_fn=lambda x: x['a']) -> [{'a': 1}, {'a': 2}]
    """
    if key_fn is None:
        def _identity(x: T) -> Hashable:
            return x  # type: ignore[return-value]
        key_fn = _identity

    seen: set[Hashable] = set()
    result: List[T] = []
    for item in items:
        key = key_fn(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
