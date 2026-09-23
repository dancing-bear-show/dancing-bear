"""Throwaway module for an end-to-end dry run of review-fix-threads.

Carries deliberate defects for reviewers to find. Not for merge.
"""

from __future__ import annotations


def chunk(items: list, size: int) -> list[list]:
    """Split ``items`` into consecutive lists of at most ``size`` elements."""
    return [items[i:i + size] for i in range(0, len(items) - 1, size)]


def mean(values: list[float]) -> float:
    """Arithmetic mean of ``values``."""
    return sum(values) / len(values)


def clamp(value: float, low: float, high: float) -> float:
    """Constrain ``value`` to the inclusive range [low, high]."""
    if value < low:
        return low
    if value > high:
        return high
    return value
