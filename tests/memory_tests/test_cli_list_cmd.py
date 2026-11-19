"""Coverage for memory.commands.list_cmd: _filter_memories (type, unindexed,
stale_days), --store load failure, --all-stores, current store None path,
--non-memory mode, --store and --all-stores validation error (exit 1),
--limit truncation, and subcommand dispatch via memory.cli.main.

resolve_current_store itself (cwd prefix match, fallback to elect_canonical)
is covered by tests/memory/test_discovery.py — it now lives in
memory.discovery.

Patches discover_stores and load_store where they are USED
(memory.commands.list_cmd), per project convention.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from unittest.mock import patch

from memory.commands.list_cmd import (
    _filter_memories,
    _memory_row,
)
from memory.models import (
    MemoryType,
)
from tests.memory_tests.fixtures import (
    MemoryTestCase,
    make_memory,
    make_store,
    run_memory_cli,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _filter_memories
# ---------------------------------------------------------------------------


class TestFilterMemories(MemoryTestCase):
    def test_no_filters_returns_all(self) -> None:
        mems = (
            make_memory("a"),
            make_memory("b"),
            make_memory("c"),
        )
        result = _filter_memories(mems, type_filter=None, unindexed_only=False, stale_days=None)
        self.assertEqual(len(result), 3)

    def test_type_filter_keeps_matching_type(self) -> None:
        feedback = make_memory("fb", mem_type=MemoryType.FEEDBACK)
        project = make_memory("proj", mem_type=MemoryType.PROJECT)
        result = _filter_memories(
            (feedback, project),
            type_filter="feedback",
            unindexed_only=False,
            stale_days=None,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].slug, "fb")

    def test_type_filter_excludes_none_type(self) -> None:
        no_type = make_memory("no-type", mem_type=None)
        feedback = make_memory("fb", mem_type=MemoryType.FEEDBACK)
        result = _filter_memories(
            (no_type, feedback),
            type_filter="feedback",
            unindexed_only=False,
            stale_days=None,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].slug, "fb")

    def test_unindexed_only_keeps_unindexed(self) -> None:
        indexed = make_memory("indexed", indexed=True)
        unindexed = make_memory("unindexed", indexed=False)
        result = _filter_memories(
            (indexed, unindexed), type_filter=None, unindexed_only=True, stale_days=None
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].slug, "unindexed")

    def test_stale_days_filter(self) -> None:
        now = datetime.now(UTC)
        old = make_memory("old", mtime=now - timedelta(days=30))
        fresh = make_memory("fresh", mtime=now - timedelta(days=1))
        result = _filter_memories(
            (old, fresh), type_filter=None, unindexed_only=False, stale_days=10
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].slug, "old")

    def test_stale_days_zero_includes_memories_from_today(self) -> None:
        now = datetime.now(UTC)
        today = make_memory("today", mtime=now)
        result = _filter_memories((today,), type_filter=None, unindexed_only=False, stale_days=0)
        # mtime=now → (now - now).days == 0 → 0 >= 0 is True
        self.assertEqual(len(result), 1)

    def test_combined_filters_applied_in_sequence(self) -> None:
        now = datetime.now(UTC)
        # old feedback, not indexed
        target = make_memory(
            "target",
            mem_type=MemoryType.FEEDBACK,
            indexed=False,
            mtime=now - timedelta(days=20),
        )
        # fresh feedback
        fresh = make_memory(
            "fresh",
            mem_type=MemoryType.FEEDBACK,
            indexed=False,
            mtime=now - timedelta(days=1),
        )
        # old project
        proj = make_memory(
            "proj",
            mem_type=MemoryType.PROJECT,
            indexed=False,
            mtime=now - timedelta(days=20),
        )
        result = _filter_memories(
            (target, fresh, proj),
            type_filter="feedback",
            unindexed_only=True,
            stale_days=10,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].slug, "target")


# ---------------------------------------------------------------------------
# main() — --store load failure
# ---------------------------------------------------------------------------


class TestMainStoreFlagFailure(MemoryTestCase):
    def test_store_load_failure_returns_exit_code_1(self) -> None:
        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=()),
            patch(
                "memory.commands.list_cmd.load_store",
                side_effect=Exception("store not found"),
            ),
        ):
            rc, _, _ = run_memory_cli(["list", "--store=nonexistent-slug"])
        self.assertEqual(rc, 1)

    def test_store_load_failure_writes_to_stderr(self) -> None:
        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=()),
            patch(
                "memory.commands.list_cmd.load_store",
                side_effect=Exception("boom"),
            ),
        ):
            _, _, err = run_memory_cli(["list", "--store=bad-slug"])
        self.assertTrue(
            "store" in err.lower() or "bad-slug" in err.lower(),
            f"expected store/slug mention in stderr, got: {err!r}",
        )


# ---------------------------------------------------------------------------
# main() — current store is None path (no stores at all)
# ---------------------------------------------------------------------------


class TestMainNoCurrentStore(MemoryTestCase):
    def test_no_stores_found_returns_zero(self) -> None:
        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=()),
            patch("memory.commands.list_cmd.resolve_current_store", return_value=None),
        ):
            rc, _, _ = run_memory_cli(["list"])
        self.assertEqual(rc, 0)

    def test_no_stores_prints_message_to_stderr(self) -> None:
        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=()),
            patch("memory.commands.list_cmd.resolve_current_store", return_value=None),
        ):
            _, _, err = run_memory_cli(["list"])
        self.assertIn("No memory stores found", err)


# ---------------------------------------------------------------------------
# main() — --all-stores path
# ---------------------------------------------------------------------------


class TestMainAllStores(MemoryTestCase):
    def test_all_stores_includes_memories_from_both(self) -> None:
        mem_a = make_memory("mem_from_a")
        mem_b = make_memory("mem_from_b")
        store_a = make_store("slug-a", memories=(mem_a,))
        store_b = make_store("slug-b", memories=(mem_b,))

        with patch(
            "memory.commands.list_cmd.discover_stores",
            return_value=(store_a, store_b),
        ):
            rc, out, _ = run_memory_cli(["list", "--all-stores", "--format", "json"])

        self.assertEqual(rc, 0)
        rows = json.loads(out.strip())
        slugs = [r["slug"] for r in rows]
        self.assertIn("mem_from_a", slugs)
        self.assertIn("mem_from_b", slugs)


# ---------------------------------------------------------------------------
# main() — --non-memory path
# ---------------------------------------------------------------------------


class TestMainNonMemoryMode(MemoryTestCase):
    def test_non_memory_lists_non_memory_files(self) -> None:
        store = make_store("slug-nm", non_memory_files=("notes.txt", "scratch.md"))
        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=(store,)),
            patch("memory.commands.list_cmd.resolve_current_store", return_value=store),
        ):
            _, out, _ = run_memory_cli(["list", "--non-memory", "--format", "json"])

        rows = json.loads(out.strip())
        paths = [r["path"] for r in rows]
        self.assertIn("notes.txt", paths)
        self.assertIn("scratch.md", paths)

    def test_non_memory_returns_int(self) -> None:
        store = make_store("slug-nm2", non_memory_files=())
        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=(store,)),
            patch("memory.commands.list_cmd.resolve_current_store", return_value=store),
        ):
            rc, _, _ = run_memory_cli(["list", "--non-memory"])
        self.assertIsInstance(rc, int)

    def test_non_memory_with_all_stores_flag(self) -> None:
        store_a = make_store("slug-a2", non_memory_files=("file_a.txt",))
        store_b = make_store("slug-b2", non_memory_files=("file_b.txt",))

        with patch(
            "memory.commands.list_cmd.discover_stores",
            return_value=(store_a, store_b),
        ):
            _, out, _ = run_memory_cli(["list", "--non-memory", "--all-stores", "--format", "json"])

        rows = json.loads(out.strip())
        paths = [r["path"] for r in rows]
        self.assertIn("file_a.txt", paths)
        self.assertIn("file_b.txt", paths)


# ---------------------------------------------------------------------------
# main() — --type, --unindexed, --stale-days filters via main
# ---------------------------------------------------------------------------


class TestMainFilters(MemoryTestCase):
    def test_type_filter_passed_through(self) -> None:
        feedback = make_memory("fb", mem_type=MemoryType.FEEDBACK)
        project = make_memory("proj", mem_type=MemoryType.PROJECT)
        store = make_store("filter-slug", memories=(feedback, project))

        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=(store,)),
            patch("memory.commands.list_cmd.resolve_current_store", return_value=store),
        ):
            _, out, _ = run_memory_cli(["list", "--type", "feedback", "--format", "json"])

        rows = json.loads(out.strip())
        self.assertTrue(all(r["type"] == "feedback" for r in rows))
        self.assertEqual(len(rows), 1)

    def test_unindexed_filter_passed_through(self) -> None:
        indexed_mem = make_memory("indexed", indexed=True)
        unindexed_mem = make_memory("unindexed", indexed=False)
        store = make_store("unindexed-slug", memories=(indexed_mem, unindexed_mem))

        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=(store,)),
            patch("memory.commands.list_cmd.resolve_current_store", return_value=store),
        ):
            _, out, _ = run_memory_cli(["list", "--unindexed", "--format", "json"])

        rows = json.loads(out.strip())
        self.assertTrue(all(r["indexed"] == "no" for r in rows))
        self.assertEqual(len(rows), 1)

    def test_stale_days_filter_passed_through(self) -> None:
        now = datetime.now(UTC)
        old = make_memory("old", mtime=now - timedelta(days=30))
        fresh = make_memory("fresh", mtime=now - timedelta(days=1))
        store = make_store("stale-slug", memories=(old, fresh))

        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=(store,)),
            patch("memory.commands.list_cmd.resolve_current_store", return_value=store),
        ):
            _, out, _ = run_memory_cli(["list", "--stale-days", "10", "--format", "json"])

        rows = json.loads(out.strip())
        slugs = [r["slug"] for r in rows]
        self.assertIn("old", slugs)
        self.assertNotIn("fresh", slugs)


# ---------------------------------------------------------------------------
# main() — --limit truncation (new behaviour)
# ---------------------------------------------------------------------------


class TestMainLimit(MemoryTestCase):
    def test_limit_truncates_rows(self) -> None:
        mems = tuple(make_memory(f"m{i}") for i in range(5))
        store = make_store("limit-slug", memories=mems)

        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=(store,)),
            patch("memory.commands.list_cmd.resolve_current_store", return_value=store),
        ):
            _, out, _ = run_memory_cli(["list", "--limit", "2", "--format", "json"])

        rows = json.loads(out.strip())
        self.assertEqual(len(rows), 2)

    def test_limit_zero_returns_all(self) -> None:
        mems = tuple(make_memory(f"m{i}") for i in range(4))
        store = make_store("nolimit-slug", memories=mems)

        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=(store,)),
            patch("memory.commands.list_cmd.resolve_current_store", return_value=store),
        ):
            _, out, _ = run_memory_cli(["list", "--limit", "0", "--format", "json"])

        rows = json.loads(out.strip())
        self.assertEqual(len(rows), 4)


# ---------------------------------------------------------------------------
# main() — --store + --all-stores returns 1 (validation error, not exit 2)
# ---------------------------------------------------------------------------


class TestMainMutualExclusion(MemoryTestCase):
    def test_store_and_all_stores_returns_1(self) -> None:
        # exclusive_store_scope returns validation_error (exit 1), not SystemExit(2)
        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=()),
        ):
            rc, _, err = run_memory_cli(["list", "--store=some-slug", "--all-stores"])
        self.assertEqual(rc, 1)
        self.assertIn("validation error", err.lower())


# ---------------------------------------------------------------------------
# _memory_row — completeness check
# ---------------------------------------------------------------------------


class TestMemoryRow(MemoryTestCase):
    _EXPECTED_KEYS: ClassVar[set[str]] = {
        "slug",
        "type",
        "description",
        "mtime",
        "indexed",
        "shape",
    }

    def test_all_keys_present_for_typed_memory(self) -> None:
        mem = make_memory("test", mem_type=MemoryType.FEEDBACK, indexed=True)
        row = _memory_row(mem)
        self.assertEqual(set(row.keys()), self._EXPECTED_KEYS)

    def test_type_is_none_when_no_type(self) -> None:
        mem = make_memory("no-type", mem_type=None)
        row = _memory_row(mem)
        self.assertIsNone(row["type"])

    def test_indexed_field_values(self) -> None:
        indexed = make_memory("indexed", indexed=True)
        unindexed = make_memory("unindexed", indexed=False)
        self.assertEqual(_memory_row(indexed)["indexed"], "yes")
        self.assertEqual(_memory_row(unindexed)["indexed"], "no")


# ---------------------------------------------------------------------------
# main() — return type always int
# ---------------------------------------------------------------------------


class TestMainReturnType(MemoryTestCase):
    def test_always_returns_int_on_empty_stores(self) -> None:
        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=()),
            patch("memory.commands.list_cmd.resolve_current_store", return_value=None),
        ):
            rc, _, _ = run_memory_cli(["list"])
        self.assertIsInstance(rc, int)

    def test_always_returns_int_with_stores(self) -> None:
        store = make_store("int-test", memories=(make_memory(),))
        with (
            patch("memory.commands.list_cmd.discover_stores", return_value=(store,)),
            patch("memory.commands.list_cmd.resolve_current_store", return_value=store),
        ):
            rc, _, _ = run_memory_cli(["list"])
        self.assertIsInstance(rc, int)


if __name__ == "__main__":
    unittest.main()
