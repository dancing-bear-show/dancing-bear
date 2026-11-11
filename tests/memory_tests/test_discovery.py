"""Covers decode_project_slug, is_worktree_slug, load_store, discover_stores,
elect_canonical, resolve_current_store."""

from __future__ import annotations

import contextlib
import io
import os
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from tests.memory_tests.fixtures import (
    SLUG_EMPTY,
    SLUG_MAIN,
    SLUG_WORKTREE,
    MemoryTestCase,
    make_projects_root,
)
from memory.discovery import (
    decode_project_slug,
    discover_stores,
    elect_canonical,
    is_worktree_slug,
    load_store,
    resolve_current_store,
)
from memory.models import MemoryStore


# ---------------------------------------------------------------------------
# File-local helper
# ---------------------------------------------------------------------------


def _make_store(slug: str, *, inferred_repo: str | None = None) -> MemoryStore:
    return MemoryStore(
        project_slug=slug,
        root=f"/nonexistent/{slug}",
        memories=(),
        non_memory_files=(),
        index_path=None,
        index_entries=(),
        inferred_repo=inferred_repo,
        is_worktree_slug=False,
    )


# ---------------------------------------------------------------------------
# TestDecodeProjectSlug
# ---------------------------------------------------------------------------


class TestDecodeProjectSlug(MemoryTestCase):
    def test_decode_project_slug_parametrized(self):
        cases = [
            # Normal decodable slug (SLUG_MAIN)
            (SLUG_MAIN, "/Users/alice/code/proj"),
            # Multi-segment repo name
            ("-Users-bob-code-my-awesome-repo", "/Users/bob/code/my-awesome-repo"),
            # Worktree slug — decode_project_slug concatenates everything after 'code'
            (
                SLUG_WORKTREE,
                "/Users/alice/code/proj--claude-worktrees-my-feature-run",
            ),
            # Empty slug
            ("", None),
            # No 'Users' prefix
            ("regular-project-slug", None),
            # Parts[0] is not '' (no leading -)
            ("Users-alice-code-repo", None),
            # Has Users but no 'code' token
            ("-Users-alice-nocode-repo", None),
            # Too short (less than 4 parts)
            ("-Users-x", None),
        ]
        for slug, expected in cases:
            with self.subTest(slug=slug):
                result = decode_project_slug(slug)
                self.assertEqual(
                    result,
                    expected,
                    f"slug={slug!r}: expected {expected!r}, got {result!r}",
                )

    def test_name_with_multiple_hyphens(self):
        # alice-marie between Users and code
        result = decode_project_slug("-Users-alice-marie-code-myrepo")
        self.assertEqual(result, "/Users/alice-marie/code/myrepo")


# ---------------------------------------------------------------------------
# TestIsWorktreeSlug
# ---------------------------------------------------------------------------


class TestIsWorktreeSlug(MemoryTestCase):
    def test_normal_slug_returns_false(self):
        self.assertFalse(is_worktree_slug(SLUG_MAIN))

    def test_undecodable_slug_returns_false(self):
        self.assertFalse(is_worktree_slug(""))
        self.assertFalse(is_worktree_slug("no-users-prefix"))

    def test_worktree_marker_in_slug_returns_true(self):
        # Claude Code's on-disk slug encoding replaces every '/' with '-', so
        # a worktree path segment ('.claude/worktrees/<name>') survives as the
        # literal substring '-claude-worktrees-' in the RAW slug.
        self.assertTrue(is_worktree_slug(SLUG_WORKTREE))

    def test_worktree_marker_absent_returns_false(self):
        slug = SLUG_MAIN + "-feature-branch"
        self.assertFalse(is_worktree_slug(slug))


# ---------------------------------------------------------------------------
# TestLoadStore
# ---------------------------------------------------------------------------


class TestLoadStore(MemoryTestCase):
    def test_load_store_with_memories(self):
        projects_root = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_root)

        self.assertIsInstance(store, MemoryStore)
        self.assertEqual(store.project_slug, SLUG_MAIN)
        self.assertGreaterEqual(len(store.memories), 1)

    def test_load_store_no_memory_dir_yields_empty_store(self):
        projects_root = make_projects_root(self.tmp)
        store = load_store(SLUG_EMPTY, projects_root=projects_root)

        self.assertEqual(store.memories, ())
        self.assertEqual(store.non_memory_files, ())
        self.assertEqual(store.index_entries, ())

    def test_load_store_missing_slug_dir_yields_empty_store(self):
        projects_root = self.tmp / "projects"
        projects_root.mkdir()
        store = load_store("nonexistent-slug", projects_root=projects_root)

        self.assertEqual(store.memories, ())
        self.assertIsNone(store.index_path)

    def test_load_store_rejects_empty_slug(self):
        projects_root = self.tmp / "projects"
        projects_root.mkdir()
        with self.assertRaisesRegex(ValueError, "slug must not be empty"):
            load_store("", projects_root=projects_root)

    def test_load_store_rejects_path_traversal_slug(self):
        """slug is user-controlled; a value like '../../etc' must not escape projects_root."""
        projects_root = self.tmp / "projects"
        projects_root.mkdir()
        secret_dir = self.tmp / "secret"
        secret_dir.mkdir()
        (secret_dir / "memory").mkdir()

        with self.assertRaisesRegex(ValueError, "outside the projects root"):
            load_store("../secret", projects_root=projects_root)

    def test_load_store_rejects_absolute_path_slug(self):
        """An absolute-path slug must not bypass projects_root entirely."""
        projects_root = self.tmp / "projects"
        projects_root.mkdir()
        with self.assertRaisesRegex(ValueError, "outside the projects root"):
            load_store(str(self.tmp / "secret"), projects_root=projects_root)

    def test_load_store_inferred_repo(self):
        projects_root = make_projects_root(self.tmp)
        store = load_store(SLUG_MAIN, projects_root=projects_root)
        self.assertEqual(store.inferred_repo, "/Users/alice/code/proj")

    def test_load_store_is_worktree_slug_true_for_worktree_form(self):
        # is_worktree_slug matches the '-claude-worktrees-' marker against the
        # raw slug (not the lossily-decoded path), so a real worktree-form
        # slug is correctly detected.
        projects_root = make_projects_root(self.tmp)
        store = load_store(SLUG_WORKTREE, projects_root=projects_root)
        self.assertTrue(store.is_worktree_slug)

    def test_load_store_non_memory_files_classified(self):
        projects_root = self.tmp / "projects"
        slug = "-Users-alice-code-myrepo"
        memory_dir = projects_root / slug / "memory"
        memory_dir.mkdir(parents=True)

        # No-frontmatter file should land in non_memory_files
        (memory_dir / "scratch.md").write_text(
            "# No frontmatter\n\nJust prose.\n", encoding="utf-8"
        )

        store = load_store(slug, projects_root=projects_root)
        self.assertEqual(len(store.non_memory_files), 1)
        self.assertEqual(store.memories, ())

    def test_load_store_with_index(self):
        projects_root = self.tmp / "projects"
        slug = "-Users-alice-code-indexed-repo"
        memory_dir = projects_root / slug / "memory"
        memory_dir.mkdir(parents=True)

        (memory_dir / "MEMORY.md").write_text(
            "## Feedback\n- [mymem.md](mymem.md) — my hook\n",
            encoding="utf-8",
        )
        (memory_dir / "mymem.md").write_text(
            "---\nmetadata:\n  type: feedback\n  node_type: memory\nname: mymem\n---\n\nBody.\n",
            encoding="utf-8",
        )

        store = load_store(slug, projects_root=projects_root)
        self.assertEqual(len(store.memories), 1)
        self.assertTrue(store.memories[0].indexed)
        self.assertEqual(store.memories[0].index_hook, "my hook")
        self.assertIsNotNone(store.index_path)


# ---------------------------------------------------------------------------
# TestDiscoverStores
# ---------------------------------------------------------------------------


class TestDiscoverStores(MemoryTestCase):
    def test_discovers_all_slugs(self):
        projects_root = make_projects_root(self.tmp)
        stores = discover_stores(root=projects_root)
        slugs = {s.project_slug for s in stores}
        self.assertIn(SLUG_MAIN, slugs)
        self.assertIn(SLUG_EMPTY, slugs)

    def test_missing_root_returns_empty(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            result = discover_stores(root=self.tmp / "nonexistent")
        self.assertEqual(result, ())
        self.assertIn("Warning", buf.getvalue())

    def test_sorted_by_slug(self):
        projects_root = make_projects_root(self.tmp)
        stores = discover_stores(root=projects_root)
        slugs = [s.project_slug for s in stores]
        self.assertEqual(slugs, sorted(slugs))


# ---------------------------------------------------------------------------
# TestElectCanonical
# ---------------------------------------------------------------------------


class TestElectCanonical(MemoryTestCase):
    def test_empty_input_returns_none(self):
        self.assertIsNone(elect_canonical(()))

    def test_returns_memory_store_not_string(self):
        projects_root = make_projects_root(self.tmp)
        stores = discover_stores(root=projects_root)
        result = elect_canonical(stores)
        self.assertIsInstance(result, MemoryStore)

    def test_single_store_elected(self):
        projects_root = self.tmp / "projects"
        slug = "-Users-alice-code-onlyone"
        memory_dir = projects_root / slug / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "mem.md").write_text(
            "---\ntype: feedback\n---\n\nContent.\n", encoding="utf-8"
        )
        stores = discover_stores(root=projects_root)
        result = elect_canonical(stores)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, MemoryStore)

    def test_newest_mtime_wins_when_no_existing_path(self):
        """When no store's decoded repo path exists on disk, newest mtime wins."""
        from datetime import timedelta

        projects_root = self.tmp / "projects"

        slug_old = "-Users-alice-code-older-repo"
        slug_new = "-Users-alice-code-newer-repo"

        for slug in (slug_old, slug_new):
            mem_dir = projects_root / slug / "memory"
            mem_dir.mkdir(parents=True)
            f = mem_dir / "mem.md"
            f.write_text(
                "---\nmetadata:\n  type: feedback\n  node_type: memory\n---\n\nContent.\n",
                encoding="utf-8",
            )

        # Set older mtime on slug_old
        now = datetime.now(UTC)
        f_old = projects_root / slug_old / "memory" / "mem.md"
        f_new = projects_root / slug_new / "memory" / "mem.md"
        ts_old = (now - timedelta(days=30)).timestamp()
        ts_new = (now - timedelta(days=1)).timestamp()
        os.utime(str(f_old), (ts_old, ts_old))
        os.utime(str(f_new), (ts_new, ts_new))

        stores = discover_stores(root=projects_root)
        canonical = elect_canonical(stores)
        self.assertIsNotNone(canonical)
        self.assertEqual(canonical.project_slug, slug_new)


# ---------------------------------------------------------------------------
# TestResolveCurrentStore
# ---------------------------------------------------------------------------


class TestResolveCurrentStore(MemoryTestCase):
    def test_matching_inferred_repo_prefix_returns_that_store(self):
        repo = "/Users/alice/code/my-repo"
        store = _make_store("slug-a", inferred_repo=repo)
        other = _make_store("slug-b", inferred_repo="/other/path")

        with patch(
            "memory.discovery.os.getcwd",
            return_value=repo + "/src/module",
        ):
            result = resolve_current_store((store, other))

        self.assertIs(result, store)

    def test_exact_cwd_match_on_inferred_repo_root(self):
        """cwd exactly equal to inferred_repo (no trailing path segment) must still match."""
        repo = "/Users/alice/code/repo"
        store = _make_store("slug-a", inferred_repo=repo)
        other = _make_store(
            "slug-b", inferred_repo="/Users/alice/code/repo-extended"
        )

        with patch("memory.discovery.os.getcwd", return_value=repo):
            result = resolve_current_store((store, other))

        self.assertIs(result, store)

    def test_sibling_repo_name_prefix_does_not_false_match(self):
        """cwd under a repo whose name is a superstring of another store's
        inferred_repo must not match the shorter store via a bare startswith."""
        repo_store = _make_store("slug-a", inferred_repo="/Users/alice/code/repo")
        extended_store = _make_store(
            "slug-b", inferred_repo="/Users/alice/code/repo-extended"
        )

        with patch(
            "memory.discovery.os.getcwd",
            return_value="/Users/alice/code/repo-extended/src",
        ):
            result = resolve_current_store((repo_store, extended_store))

        self.assertIs(result, extended_store)

    def test_none_inferred_repo_store_is_skipped(self):
        no_repo = _make_store("no-repo-slug", inferred_repo=None)
        with_repo = _make_store(
            "with-repo-slug", inferred_repo="/Users/alice/code/repo"
        )

        with patch(
            "memory.discovery.os.getcwd",
            return_value="/Users/alice/code/repo/subdir",
        ):
            result = resolve_current_store((no_repo, with_repo))

        self.assertIs(result, with_repo)

    def test_no_prefix_match_falls_back_to_elect_canonical(self):
        store = _make_store("slug-a", inferred_repo="/unrelated/path")

        with (
            patch(
                "memory.discovery.os.getcwd",
                return_value="/completely/different",
            ),
            patch(
                "memory.discovery.elect_canonical", return_value=store
            ) as mock_elect,
        ):
            result = resolve_current_store((store,))

        mock_elect.assert_called_once()
        self.assertIs(result, store)

    def test_empty_stores_returns_none(self):
        with patch(
            "memory.discovery.os.getcwd",
            return_value="/unrelated/path",
        ):
            result = resolve_current_store(())

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
