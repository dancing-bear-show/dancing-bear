"""Phase-1 type-aware staleness scoring — date-based thresholds only, fully offline, no network calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from memory.models import MemoryStore, MemoryType

__all__ = ["DEFAULT_THRESHOLDS", "StaleCandidate", "stale_candidates"]

# Type-aware thresholds in days: in-flight work decays fast, durable rules age
# slowly, reference/user material never goes stale on date alone.
DAYS_PROJECT = 45
DAYS_FEEDBACK = 365

DEFAULT_THRESHOLDS: dict[MemoryType, int | None] = {
    MemoryType.PROJECT: DAYS_PROJECT,
    MemoryType.FEEDBACK: DAYS_FEEDBACK,
    MemoryType.REFERENCE: None,
    MemoryType.USER: None,
}


@dataclass(frozen=True)
class StaleCandidate:
    """One memory's staleness result — never mutates, never deletes."""

    slug: str
    memory_type: MemoryType
    age_days: int
    threshold_days: int | None
    is_stale: bool
    severity: str


def stale_candidates(
    store: MemoryStore,
    *,
    thresholds: dict[MemoryType, int | None] | None = None,
    now: datetime | None = None,
) -> tuple[StaleCandidate, ...]:
    """Find memories exceeding their type's age threshold (date-only, offline).

    Both `now` and each memory's mtime must be timezone-aware; a naive mtime
    raises TypeError rather than producing a silently wrong age. `now` is
    keyword-only and injectable so tests pin a deterministic clock. A memory
    with no type (schema-missing-type) is skipped, not crashed on. Never
    deletes or mutates — emits candidates with severity "warn" (or "info"
    for never-stale types) only.
    """
    active_thresholds = thresholds if thresholds is not None else DEFAULT_THRESHOLDS
    reference_time = now if now is not None else datetime.now(UTC)

    results: list[StaleCandidate] = []
    for memory in store.memories:
        memory_type = memory.frontmatter.type
        if memory_type is None:
            continue

        threshold_days = active_thresholds.get(memory_type)
        age_days = max(0, (reference_time - memory.mtime).days)

        if threshold_days is None:
            is_stale = False
            severity = "info"
        else:
            is_stale = age_days > threshold_days
            severity = "warn" if is_stale else "info"

        results.append(
            StaleCandidate(
                slug=memory.slug,
                memory_type=memory_type,
                age_days=age_days,
                threshold_days=threshold_days,
                is_stale=is_stale,
                severity=severity,
            )
        )

    results.sort(key=lambda r: r.age_days, reverse=True)
    return tuple(results)
