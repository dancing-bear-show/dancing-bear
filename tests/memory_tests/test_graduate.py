"""Covers graduate_memory: promotion, skip-identical, error-if-canonical, dry-run, index update,
diverged-requires-yes, and the graduate CLI subcommand via memory.cli.main."""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.memory_tests.fixtures import MemoryTestCase
from memory.graduate import GraduateError, graduate_memory, _find_memory_by_slug
from memory.models import MemoryStore


# ---------------------------------------------------------------------------
# File-local helpers
# ---------------------------------------------------------------------------

_SHARED_INFERRED_REPO = "/Users/alice/code/shared-repo"

_FEEDBACK_CONTENT = (
    "---\n"
    "name: {name}\n"
    "description: {desc}\n"
    "metadata:\n"
    "  type: feedback\n"
    "  node_type: memory\n"
    "---\n\n"
    "**Why:** Testing.\n\n**How to apply:** Use in tests.\n"
)


def _feedback(name: str, desc: str) -> str:
    return _FEEDBACK_CONTENT.format(name=name, desc=desc)


def _make_store(
    base: Path,
    slug: str,
    files: dict,
    *,
    inferred_repo: str | None = _SHARED_INFERRED_REPO,
    is_worktree_slug: bool = False,
    with_index: bool = False,
) -> MemoryStore:
    """Build a MemoryStore with real files on disk."""
    from memory.index import append_entry
    from memory.parser import parse_memory_file

    store_root = base / slug
    mem_dir = store_root / "memory"
    mem_dir.mkdir(parents=True)

    memories = []
    for filename, content in files.items():
        f = mem_dir / filename
        f.write_text(content, encoding="utf-8")
        mem = parse_memory_file(f, project_slug=slug)
        memories.append(mem)

    index_path = None
    if with_index:
        index_file = mem_dir / "MEMORY.md"
        for mem in memories:
            append_entry(index_file, mem)
        index_path = str(index_file)

    return MemoryStore(
        project_slug=slug,
        root=str(store_root),
        memories=tuple(memories),
        non_memory_files=(),
        index_path=index_path,
        index_entries=(),
        inferred_repo=inferred_repo,
        is_worktree_slug=is_worktree_slug,
    )


def _run_cli(*args, suppress_output: bool = True) -> int:
    """Run memory.cli.main with the given argv, optionally suppressing output."""
    from memory.cli import main as memory_main

    if suppress_output:
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            return memory_main(list(args))
    return memory_main(list(args))


# ---------------------------------------------------------------------------
# TestFindMemoryBySlug
# ---------------------------------------------------------------------------


class TestFindMemoryBySlug(MemoryTestCase):
    """Unit tests for _find_memory_by_slug prefix/ambiguous branches."""

    def test_prefix_match_resolves_unique(self):
        """A unique prefix resolves to the matching memory."""
        store = _make_store(
            self.tmp,
            "source-store",
            {
                "feedback_worktree.md": _feedback("feedback_worktree", "w"),
                "project_state.md": _feedback("project_state", "p"),
            },
        )
        # "feedback" uniquely prefixes "feedback_worktree"
        mem = _find_memory_by_slug(store, "feedback")
        self.assertEqual(mem.slug, "feedback_worktree")

    def test_ambiguous_prefix_raises(self):
        """Multiple prefix matches raise GraduateError with ambiguity message."""
        store = _make_store(
            self.tmp,
            "source-store",
            {
                "feed_one.md": _feedback("feed_one", "a"),
                "feed_two.md": _feedback("feed_two", "b"),
            },
        )
        with self.assertRaisesRegex(GraduateError, "ambiguous"):
            _find_memory_by_slug(store, "feed")

    def test_no_match_raises(self):
        """A slug with no matches raises GraduateError with no-match message."""
        store = _make_store(
            self.tmp,
            "source-store",
            {"myslug.md": _feedback("myslug", "x")},
        )
        with self.assertRaisesRegex(GraduateError, "no memory matches"):
            _find_memory_by_slug(store, "completely_nonexistent")

    def test_dot_md_suffix_stripped(self):
        """Slug with .md suffix resolves identically to slug without it."""
        store = _make_store(
            self.tmp,
            "source-store",
            {"myslug.md": _feedback("myslug", "x")},
        )
        mem = _find_memory_by_slug(store, "myslug.md")
        self.assertEqual(mem.slug, "myslug")


# ---------------------------------------------------------------------------
# TestGraduateMemory
# ---------------------------------------------------------------------------


class TestGraduateMemory(MemoryTestCase):
    def test_graduate_moves_memory_to_canonical(self):
        source = _make_store(
            self.tmp,
            "worktree-store",
            {"myslug.md": _feedback("myslug", "a memory")},
            is_worktree_slug=True,
        )
        canonical = _make_store(self.tmp, "canonical-store", {})

        result = graduate_memory("myslug", source, canonical)

        self.assertEqual(result.action, "graduated")
        self.assertEqual(result.slug, "myslug")
        dest = Path(canonical.root) / "memory" / "myslug.md"
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_text(encoding="utf-8"), _feedback("myslug", "a memory"))

    def test_graduate_identical_memory_is_skipped(self):
        content = _feedback("myslug", "same content")
        source = _make_store(
            self.tmp,
            "worktree-store",
            {"myslug.md": content},
            is_worktree_slug=True,
        )
        canonical = _make_store(self.tmp, "canonical-store", {"myslug.md": content})

        result = graduate_memory("myslug", source, canonical)

        self.assertEqual(result.action, "skipped")
        self.assertEqual(result.slug, "myslug")

    def test_graduate_already_canonical_errors(self):
        store = _make_store(
            self.tmp,
            "canonical-store",
            {"myslug.md": _feedback("myslug", "a memory")},
        )

        with self.assertRaisesRegex(GraduateError, "already the canonical store"):
            graduate_memory("myslug", store, store)

    def test_graduate_dry_run_writes_nothing(self):
        source = _make_store(
            self.tmp,
            "worktree-store",
            {"myslug.md": _feedback("myslug", "a memory")},
            is_worktree_slug=True,
        )
        canonical = _make_store(self.tmp, "canonical-store", {})

        result = graduate_memory("myslug", source, canonical, dry_run=True)

        self.assertEqual(result.action, "dry-run")
        dest = Path(canonical.root) / "memory" / "myslug.md"
        self.assertFalse(dest.exists())

    def test_graduate_updates_index_when_indexed(self):
        """When the memory was indexed in the source, canonical MEMORY.md is updated."""
        from memory.index import parse_index

        _make_store(
            self.tmp,
            "worktree-store",
            {"myslug.md": _feedback("myslug", "a memory")},
            is_worktree_slug=True,
            with_index=True,
        )
        # Canonical starts with an existing index file (empty)
        canonical_root = self.tmp / "canonical-store"
        mem_dir = canonical_root / "memory"
        mem_dir.mkdir(parents=True)
        index_file = mem_dir / "MEMORY.md"
        index_file.write_text("", encoding="utf-8")

        canonical = MemoryStore(
            project_slug="canonical-store",
            root=str(canonical_root),
            memories=(),
            non_memory_files=(),
            index_path=str(index_file),
            index_entries=(),
            inferred_repo=_SHARED_INFERRED_REPO,
            is_worktree_slug=False,
        )

        # Re-load source to pick up indexed=True
        from memory.discovery import load_store

        source_reloaded = load_store("worktree-store", projects_root=self.tmp)

        graduate_memory("myslug", source_reloaded, canonical)

        entries = parse_index(index_file)
        self.assertTrue(any("myslug.md" in e.target for e in entries))

    def test_graduate_diverged_requires_yes(self):
        source = _make_store(
            self.tmp,
            "worktree-store",
            {"myslug.md": _feedback("myslug", "version A")},
            is_worktree_slug=True,
        )
        canonical = _make_store(
            self.tmp,
            "canonical-store",
            {"myslug.md": _feedback("myslug", "version B — different content")},
        )

        with self.assertRaisesRegex(GraduateError, "--yes"):
            graduate_memory("myslug", source, canonical)

        # With yes=True it proceeds
        result = graduate_memory("myslug", source, canonical, yes=True)
        self.assertEqual(result.action, "graduated")


# ---------------------------------------------------------------------------
# TestGraduateCliMain — exercises memory.cli.main(["graduate", ...])
# ---------------------------------------------------------------------------


class TestGraduateCliMain(MemoryTestCase):
    def test_missing_slug_errors(self):
        source = _make_store(self.tmp, "src", {})
        with (
            patch(
                "memory.commands.graduate.discover_stores",
                return_value=(source,),
            ),
            patch(
                "memory.commands.graduate.resolve_current_store",
                return_value=source,
            ),
        ):
            rc = _run_cli("graduate")
        self.assertNotEqual(rc, 0)

    def test_no_stores_found_errors(self):
        with (
            patch("memory.commands.graduate.discover_stores", return_value=()),
            patch(
                "memory.commands.graduate.resolve_current_store", return_value=None
            ),
        ):
            rc = _run_cli("graduate", "any-slug")
        self.assertNotEqual(rc, 0)

    def test_load_store_failure_errors(self):
        with (
            patch("memory.commands.graduate.discover_stores", return_value=()),
            patch(
                "memory.commands.graduate.load_store",
                side_effect=RuntimeError("not found"),
            ),
        ):
            rc = _run_cli("graduate", "any-slug", "--store", "missing-slug")
        self.assertNotEqual(rc, 0)

    def test_no_canonical_errors(self):
        source = _make_store(
            self.tmp, "only-store", {"mem.md": _feedback("mem", "x")}
        )
        with (
            patch(
                "memory.commands.graduate.discover_stores", return_value=(source,)
            ),
            patch(
                "memory.commands.graduate.resolve_current_store",
                return_value=source,
            ),
            patch("memory.commands.graduate.elect_canonical", return_value=None),
        ):
            rc = _run_cli("graduate", "mem")
        self.assertNotEqual(rc, 0)

    def test_graduate_success_emits_row(self):
        source = _make_store(
            self.tmp,
            "wt-slug",
            {"mem.md": _feedback("mem", "a memory")},
            is_worktree_slug=True,
        )
        canonical = _make_store(self.tmp, "main-slug", {})

        with (
            patch(
                "memory.commands.graduate.discover_stores",
                return_value=(source, canonical),
            ),
            patch(
                "memory.commands.graduate.resolve_current_store",
                return_value=source,
            ),
            patch(
                "memory.commands.graduate.elect_canonical", return_value=canonical
            ),
        ):
            rc = _run_cli("graduate", "mem", "--format", "json")
        self.assertEqual(rc, 0)

    def test_graduate_error_slug_not_found(self):
        source = _make_store(
            self.tmp,
            "wt-slug",
            {"mem.md": _feedback("mem", "x")},
            is_worktree_slug=True,
        )
        canonical = _make_store(self.tmp, "main-slug", {})

        with (
            patch(
                "memory.commands.graduate.discover_stores",
                return_value=(source, canonical),
            ),
            patch(
                "memory.commands.graduate.resolve_current_store",
                return_value=source,
            ),
        ):
            rc = _run_cli("graduate", "nonexistent-slug")
        self.assertNotEqual(rc, 0)

    def test_source_with_none_repo_errors_before_election(self):
        """A source store with inferred_repo=None must fail before elect_canonical is called.

        This guards against the case where elect_canonical would pick from an
        unrelated pool of None-repo stores instead of raising safely.
        """
        none_store = _make_store(
            self.tmp,
            "linux-slug",
            {"mem.md": _feedback("mem", "a memory")},
            inferred_repo=None,
        )
        other_none_store = _make_store(
            self.tmp,
            "other-linux-slug",
            {"other.md": _feedback("other", "unrelated project memory")},
            inferred_repo=None,
        )

        with (
            patch(
                "memory.commands.graduate.discover_stores",
                return_value=(none_store, other_none_store),
            ),
            patch(
                "memory.commands.graduate.resolve_current_store",
                return_value=none_store,
            ),
        ):
            rc = _run_cli("graduate", "mem")
        # Must error, not graduate into the wrong store
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
