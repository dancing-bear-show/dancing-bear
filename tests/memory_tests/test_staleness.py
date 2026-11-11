"""Test per-type staleness thresholds with an injected clock."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from memory.models import MemoryStore, MemoryType
from memory.staleness import DEFAULT_THRESHOLDS, StaleCandidate, stale_candidates
from tests.memory_tests.fixtures import MemoryTestCase

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store_with_memory(
    tmp_path: Path,
    slug: str,
    mem_type: MemoryType,
    age_days: int,
    now: datetime,
) -> MemoryStore:
    """Build a MemoryStore with a single memory of the given type and age."""
    from memory.parser import parse_memory_file

    mem_dir = tmp_path / slug / "memory"
    mem_dir.mkdir(parents=True)

    type_yaml = f"metadata:\n  type: {mem_type.value}\n  node_type: memory\n"
    content = f"---\n{type_yaml}---\n\n**Why:** Test.\n\n**How to apply:** Test.\n"

    mem_file = mem_dir / f"{slug}_mem.md"
    mem_file.write_text(content, encoding="utf-8")

    mtime_ts = (now - timedelta(days=age_days)).timestamp()
    os.utime(str(mem_file), (mtime_ts, mtime_ts))

    memory = parse_memory_file(mem_file, project_slug=slug)

    return MemoryStore(
        project_slug=slug,
        root=str(tmp_path / slug),
        memories=(memory,),
        non_memory_files=(),
        index_path=None,
        index_entries=(),
        inferred_repo=None,
        is_worktree_slug=False,
    )


# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------


class TestDefaultThresholds(unittest.TestCase):
    def test_project_threshold_is_45(self) -> None:
        self.assertEqual(DEFAULT_THRESHOLDS[MemoryType.PROJECT], 45)

    def test_feedback_threshold_is_365(self) -> None:
        self.assertEqual(DEFAULT_THRESHOLDS[MemoryType.FEEDBACK], 365)

    def test_reference_threshold_is_none(self) -> None:
        self.assertIsNone(DEFAULT_THRESHOLDS[MemoryType.REFERENCE])

    def test_user_threshold_is_none(self) -> None:
        self.assertIsNone(DEFAULT_THRESHOLDS[MemoryType.USER])


# ---------------------------------------------------------------------------
# Per-type threshold parametrize
# ---------------------------------------------------------------------------


class TestPerTypeThresholds(MemoryTestCase):
    CASES = [
        # PROJECT: warns strictly past 45 days
        (MemoryType.PROJECT, 44, False),
        (MemoryType.PROJECT, 45, False),  # age > threshold required (not >=)
        (MemoryType.PROJECT, 46, True),
        (MemoryType.PROJECT, 100, True),
        # FEEDBACK: warns strictly past 365 days
        (MemoryType.FEEDBACK, 364, False),
        (MemoryType.FEEDBACK, 365, False),  # age > threshold required
        (MemoryType.FEEDBACK, 366, True),
        (MemoryType.FEEDBACK, 730, True),
        # REFERENCE: never warns at any age
        (MemoryType.REFERENCE, 1, False),
        (MemoryType.REFERENCE, 365, False),
        (MemoryType.REFERENCE, 1000, False),
        # USER: never warns at any age
        (MemoryType.USER, 1, False),
        (MemoryType.USER, 365, False),
        (MemoryType.USER, 1000, False),
    ]

    def test_per_type_thresholds(self) -> None:
        """Verify staleness thresholds per memory type with a pinned clock."""
        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
        for mem_type, age_days, expected_stale in self.CASES:
            with self.subTest(mem_type=mem_type.value, age_days=age_days):
                slug = f"test_{mem_type.value}_{age_days}"
                store = _make_store_with_memory(self.tmp, slug, mem_type, age_days, now)
                candidates = stale_candidates(store, now=now)
                self.assertEqual(len(candidates), 1)
                candidate = candidates[0]
                self.assertIsInstance(candidate, StaleCandidate)
                self.assertEqual(candidate.slug, f"{slug}_mem")
                self.assertEqual(candidate.memory_type, mem_type)
                self.assertEqual(candidate.age_days, age_days)
                self.assertEqual(
                    candidate.is_stale,
                    expected_stale,
                    f"{mem_type.value} aged {age_days}d: expected is_stale={expected_stale}, "
                    f"got {candidate.is_stale} (threshold={candidate.threshold_days})",
                )


# ---------------------------------------------------------------------------
# Severity field
# ---------------------------------------------------------------------------


class TestSeverityField(MemoryTestCase):
    def test_stale_project_has_warn_severity(self) -> None:
        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
        store = _make_store_with_memory(self.tmp, "stale_proj", MemoryType.PROJECT, 100, now)
        candidates = stale_candidates(store, now=now)
        self.assertEqual(candidates[0].severity, "warn")

    def test_not_stale_project_has_info_severity(self) -> None:
        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
        store = _make_store_with_memory(self.tmp, "fresh_proj", MemoryType.PROJECT, 10, now)
        candidates = stale_candidates(store, now=now)
        self.assertEqual(candidates[0].severity, "info")

    def test_reference_always_info(self) -> None:
        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
        store = _make_store_with_memory(self.tmp, "old_ref", MemoryType.REFERENCE, 2000, now)
        candidates = stale_candidates(store, now=now)
        self.assertEqual(candidates[0].severity, "info")
        self.assertFalse(candidates[0].is_stale)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestStalenessEdgeCases(MemoryTestCase):
    def test_empty_store_returns_empty_tuple(self) -> None:
        store = MemoryStore(
            project_slug="empty",
            root="/fake",
            memories=(),
            non_memory_files=(),
            index_path=None,
            index_entries=(),
            inferred_repo=None,
            is_worktree_slug=False,
        )
        result = stale_candidates(store)
        self.assertEqual(result, ())

    def test_memory_with_no_type_is_skipped(self) -> None:
        from memory.parser import parse_memory_file

        mem_dir = self.tmp / "notype" / "memory"
        mem_dir.mkdir(parents=True)
        f = mem_dir / "notype_mem.md"
        f.write_text("---\nname: no_type\n---\n\nContent.\n", encoding="utf-8")
        memory = parse_memory_file(f, project_slug="notype")

        store = MemoryStore(
            project_slug="notype",
            root=str(self.tmp / "notype"),
            memories=(memory,),
            non_memory_files=(),
            index_path=None,
            index_entries=(),
            inferred_repo=None,
            is_worktree_slug=False,
        )
        result = stale_candidates(store)
        self.assertEqual(result, ())

    def test_custom_thresholds_respected(self) -> None:
        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
        store = _make_store_with_memory(self.tmp, "custom_thresh", MemoryType.PROJECT, 10, now)

        custom: dict[MemoryType, int | None] = {MemoryType.PROJECT: 5}
        candidates = stale_candidates(store, thresholds=custom, now=now)
        self.assertTrue(candidates[0].is_stale)

    def test_results_sorted_by_age_descending(self) -> None:
        from memory.parser import parse_memory_file

        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
        mem_dir = self.tmp / "sorted_test" / "memory"
        mem_dir.mkdir(parents=True)

        memories = []
        for i, age in enumerate([10, 50, 30]):
            f = mem_dir / f"mem_{i}.md"
            f.write_text(
                "---\nmetadata:\n  type: feedback\n  node_type: memory\n---\n\nBody.\n",
                encoding="utf-8",
            )
            ts = (now - timedelta(days=age)).timestamp()
            os.utime(str(f), (ts, ts))
            memories.append(parse_memory_file(f, project_slug="sorted_test"))

        store = MemoryStore(
            project_slug="sorted_test",
            root=str(self.tmp / "sorted_test"),
            memories=tuple(memories),
            non_memory_files=(),
            index_path=None,
            index_entries=(),
            inferred_repo=None,
            is_worktree_slug=False,
        )
        candidates = stale_candidates(store, now=now)
        ages = [c.age_days for c in candidates]
        self.assertEqual(ages, sorted(ages, reverse=True))
