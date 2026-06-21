"""Shared utilities for the workflow module.

Keep this module thin — only add things that are genuinely shared
across 3+ submodules and have no domain-specific logic.
"""

from __future__ import annotations

from typing import Hashable, TypeVar

T = TypeVar("T", bound=Hashable)


def dedupe_preserving_order(values: list[T] | tuple[T, ...]) -> list[T]:
    """Return a list with duplicates removed, preserving first-occurrence order.

    >>> dedupe_preserving_order(["a", "b", "a", "c", "b"])
    ['a', 'b', 'c']
    >>> dedupe_preserving_order([])
    []
    >>> dedupe_preserving_order(("x", "x", "y"))
    ['x', 'y']
    """
    seen: set[T] = set()
    out: list[T] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
