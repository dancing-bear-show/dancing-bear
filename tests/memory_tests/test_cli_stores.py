"""Coverage for memory.commands.stores: _classify_role branches
(canonical, superseded, orphan-index, no-memory), _newest_mtime_str empty vs
populated, --with-memory-only filtering, and CLI entry dispatch.

Patches discover_stores where it is USED (memory.commands.stores),
per project convention.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import memory.cli
from memory.commands.stores import (
    _classify_role,
    _memory_dir_exists,
    _newest_mtime_str,
)
from memory.models import (
    IndexEntry,
    Memory,
    MemoryFrontmatter,
    MemoryStore,
    SchemaShape,
)

from tests.memory_tests.fixtures import MemoryTestCase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(
    *,
    slug: str = "test-slug",
    root: str = "/nonexistent/test",
    memories: tuple = (),
    non_memory_files: tuple = (),
    index_path: str | None = None,
    index_entries: tuple = (),
    inferred_repo: str | None = None,
    is_worktree: bool = False,
) -> MemoryStore:
    return MemoryStore(
        project_slug=slug,
        root=root,
        memories=memories,
        non_memory_files=non_memory_files,
        index_path=index_path,
        index_entries=index_entries,
        inferred_repo=inferred_repo,
        is_worktree_slug=is_worktree,
    )


def _make_memory(slug: str = "mem", mtime: datetime | None = None) -> Memory:
    if mtime is None:
        mtime = datetime.now(UTC)
    fm = MemoryFrontmatter(
        name=slug,
        description="test memory",
        type=None,
        node_type="memory",
        origin_session_id=None,
        modified=None,
        shape=SchemaShape.ABSENT,
        unknown_keys={},
    )
    return Memory(
        slug=slug,
        path=f"/nonexistent/{slug}.md",
        project_slug="test-slug",
        frontmatter=fm,
        body="test body",
        why=None,
        how_to_apply=None,
        wikilinks=(),
        mtime=mtime,
        size_bytes=100,
        indexed=False,
        index_hook=None,
        index_section=None,
    )


def _make_index_entry(target: str = "mem") -> IndexEntry:
    return IndexEntry(
        target=target,
        title="Memory Title",
        hook="Hook text",
        section="Section",
        line_no=1,
    )


# ---------------------------------------------------------------------------
# _newest_mtime_str
# ---------------------------------------------------------------------------


class TestNewestMtimeStr(MemoryTestCase):
    def test_empty_memories_returns_empty_string(self) -> None:
        store = _make_store(memories=())
        self.assertEqual(_newest_mtime_str(store), "")

    def test_single_memory_returns_isoformat(self) -> None:
        mtime = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        mem = _make_memory(mtime=mtime)
        store = _make_store(memories=(mem,))
        result = _newest_mtime_str(store)
        self.assertIn("2024-06-15", result)

    def test_multiple_memories_returns_newest(self) -> None:
        old_mtime = datetime(2024, 1, 1, tzinfo=UTC)
        new_mtime = datetime(2024, 12, 31, tzinfo=UTC)
        old_mem = _make_memory(slug="old", mtime=old_mtime)
        new_mem = _make_memory(slug="new", mtime=new_mtime)
        store = _make_store(memories=(old_mem, new_mem))
        result = _newest_mtime_str(store)
        self.assertIn("2024-12-31", result)


# ---------------------------------------------------------------------------
# _memory_dir_exists
# ---------------------------------------------------------------------------


class TestMemoryDirExists(MemoryTestCase):
    def test_returns_false_when_no_memories_no_index_no_non_memory(self) -> None:
        store = _make_store()
        self.assertIs(_memory_dir_exists(store), False)

    def test_returns_true_when_memories_present(self) -> None:
        mem = _make_memory()
        store = _make_store(memories=(mem,))
        self.assertIs(_memory_dir_exists(store), True)

    def test_returns_true_when_non_memory_files_present(self) -> None:
        store = _make_store(non_memory_files=("README.txt",))
        self.assertIs(_memory_dir_exists(store), True)

    def test_returns_true_when_index_path_set(self) -> None:
        store = _make_store(index_path="/nonexistent/MEMORY.md")
        self.assertIs(_memory_dir_exists(store), True)


# ---------------------------------------------------------------------------
# _classify_role — all four branches
# ---------------------------------------------------------------------------


class TestClassifyRole(MemoryTestCase):
    def test_canonical_store_returns_canonical(self) -> None:
        store = _make_store(memories=(_make_memory(),))
        self.assertEqual(_classify_role(store, canonicals={id(store)}), "canonical")

    def test_store_with_memories_not_canonical_returns_superseded(self) -> None:
        canonical = _make_store(slug="canonical", memories=(_make_memory(),))
        store = _make_store(slug="other", memories=(_make_memory(),))
        self.assertEqual(_classify_role(store, canonicals={id(canonical)}), "superseded")

    def test_store_with_index_no_memories_returns_orphan_index(self) -> None:
        canonical = _make_store(slug="canonical", memories=(_make_memory(),))
        store = _make_store(
            slug="orphan",
            memories=(),
            index_entries=(_make_index_entry(),),
        )
        self.assertEqual(
            _classify_role(store, canonicals={id(canonical)}), "orphan-index"
        )

    def test_store_with_no_memories_no_index_returns_no_memory(self) -> None:
        canonical = _make_store(slug="canonical", memories=(_make_memory(),))
        store = _make_store(slug="empty", memories=(), index_entries=())
        self.assertEqual(
            _classify_role(store, canonicals={id(canonical)}), "no-memory"
        )

    def test_canonicals_empty_non_canonical_store_with_memories(self) -> None:
        # When canonicals is empty, store is never a member of it.
        store = _make_store(slug="alone", memories=(_make_memory(),))
        self.assertEqual(_classify_role(store, canonicals=set()), "superseded")


# ---------------------------------------------------------------------------
# CLI entry — basic invocation paths
# ---------------------------------------------------------------------------


class TestMainStores(MemoryTestCase):
    def test_no_stores_returns_zero_with_message(self) -> None:
        err_buf = io.StringIO()
        with (
            patch("memory.commands.stores.discover_stores", return_value=()),
            contextlib.redirect_stderr(err_buf),
        ):
            rc = memory.cli.main(["stores"])
        self.assertEqual(rc, 0)
        self.assertIn("No memory stores discovered", err_buf.getvalue())

    def test_json_format_valid_json_with_stores(self) -> None:
        mem = _make_memory()
        store = _make_store(slug="json-test-slug", memories=(mem,), inferred_repo="/repo/a")
        out_buf = io.StringIO()
        with (
            patch("memory.commands.stores.discover_stores", return_value=(store,)),
            contextlib.redirect_stdout(out_buf),
        ):
            memory.cli.main(["stores", "--format", "json"])
        out = out_buf.getvalue().strip()
        if out:
            rows = json.loads(out)
            self.assertIsInstance(rows, list)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["project_slug"], "json-test-slug")
            self.assertEqual(rows[0]["role"], "canonical")

    def test_with_memory_only_excludes_empty_stores(self) -> None:
        mem = _make_memory()
        store_with = _make_store(slug="with-mem", memories=(mem,), inferred_repo="/repo/a")
        store_empty = _make_store(slug="no-mem", memories=(), inferred_repo="/repo/a")
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with (
            patch(
                "memory.commands.stores.discover_stores",
                return_value=(store_with, store_empty),
            ),
            contextlib.redirect_stdout(out_buf),
            contextlib.redirect_stderr(err_buf),
        ):
            memory.cli.main(["stores", "--with-memory-only", "--format", "json"])
        out = out_buf.getvalue().strip()
        rows = json.loads(out)
        slugs = [r["project_slug"] for r in rows]
        self.assertIn("with-mem", slugs)
        self.assertNotIn("no-mem", slugs)

    def test_with_memory_only_shows_all_when_flag_absent(self) -> None:
        mem = _make_memory()
        store_with = _make_store(
            slug="with-mem2", memories=(mem,), inferred_repo="/repo/a"
        )
        store_empty = _make_store(slug="no-mem2", memories=(), inferred_repo="/repo/a")
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with (
            patch(
                "memory.commands.stores.discover_stores",
                return_value=(store_with, store_empty),
            ),
            contextlib.redirect_stdout(out_buf),
            contextlib.redirect_stderr(err_buf),
        ):
            memory.cli.main(["stores", "--format", "json"])
        out = out_buf.getvalue().strip()
        rows = json.loads(out)
        slugs = [r["project_slug"] for r in rows]
        self.assertIn("with-mem2", slugs)
        self.assertIn("no-mem2", slugs)

    def test_all_role_labels_appear_in_output(self) -> None:
        mem = _make_memory()
        canonical_store = _make_store(
            slug="canonical-slug", memories=(mem,), inferred_repo="/repo/a"
        )
        superseded_store = _make_store(
            slug="superseded-slug",
            memories=(_make_memory(slug="s"),),
            inferred_repo="/repo/a",
        )
        orphan_store = _make_store(
            slug="orphan-slug",
            index_entries=(_make_index_entry(),),
            inferred_repo="/repo/a",
        )
        empty_store = _make_store(slug="empty-slug", inferred_repo="/repo/a")

        stores = (canonical_store, superseded_store, orphan_store, empty_store)
        out_buf = io.StringIO()
        with (
            patch("memory.commands.stores.discover_stores", return_value=stores),
            patch(
                "memory.commands.stores.elect_canonical",
                return_value=canonical_store,
            ),
            contextlib.redirect_stdout(out_buf),
        ):
            memory.cli.main(["stores", "--format", "json"])
        rows = json.loads(out_buf.getvalue().strip())
        roles = {r["role"] for r in rows}
        self.assertIn("canonical", roles)
        self.assertIn("superseded", roles)
        self.assertIn("orphan-index", roles)
        self.assertIn("no-memory", roles)

    def test_is_worktree_and_memory_count_reflected_in_rows(self) -> None:
        mem = _make_memory()
        store = _make_store(
            slug="worktree-slug",
            memories=(mem,),
            is_worktree=True,
            inferred_repo="/repo/a",
        )
        out_buf = io.StringIO()
        with (
            patch("memory.commands.stores.discover_stores", return_value=(store,)),
            contextlib.redirect_stdout(out_buf),
        ):
            memory.cli.main(["stores", "--format", "json"])
        rows = json.loads(out_buf.getvalue().strip())
        self.assertEqual(rows[0]["is_worktree"], "True")
        self.assertEqual(rows[0]["memory_count"], 1)


# ---------------------------------------------------------------------------
# CLI entry — no stores dispatch
# ---------------------------------------------------------------------------


class TestStoresMainModule(MemoryTestCase):
    def test_main_stores_exits_cleanly(self) -> None:
        err_buf = io.StringIO()
        with (
            patch("memory.commands.stores.discover_stores", return_value=()),
            contextlib.redirect_stderr(err_buf),
        ):
            rc = memory.cli.main(["stores"])
        self.assertIsInstance(rc, int)


if __name__ == "__main__":
    unittest.main()
