"""Tests for memory.consolidate — file classification, zero-loss property, divergence strategies,
archive-not-delete, and TOCTOU abort.
"""

from __future__ import annotations

import io
import time
import unittest
from datetime import datetime
from pathlib import Path

from memory.consolidate import (
    ConsolidationPlan,
    ConsolidationResult,
    apply_plan,
    plan_consolidation,
)
from memory.models import MemoryStore
from tests.memory_tests.fixtures import MemoryTestCase

_SHARED_INFERRED_REPO = "/Users/alice/code/shared-repo"


def _make_store(
    tmp_path: Path,
    slug: str,
    files: dict[str, str],
    *,
    inferred_repo: str | None = _SHARED_INFERRED_REPO,
    is_worktree_slug: bool = False,
) -> MemoryStore:
    """Build a MemoryStore with real files on disk and the given inferred_repo."""
    from memory.parser import parse_memory_file

    store_root = tmp_path / slug
    mem_dir = store_root / "memory"
    mem_dir.mkdir(parents=True)

    memories = []
    for filename, content in files.items():
        f = mem_dir / filename
        f.write_text(content, encoding="utf-8")
        mem = parse_memory_file(f, project_slug=slug)
        memories.append(mem)

    return MemoryStore(
        project_slug=slug,
        root=str(store_root),
        memories=tuple(memories),
        non_memory_files=(),
        index_path=None,
        index_entries=(),
        inferred_repo=inferred_repo,
        is_worktree_slug=is_worktree_slug,
    )


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


# ---------------------------------------------------------------------------
# plan_consolidation
# ---------------------------------------------------------------------------


class TestPlanConsolidation(MemoryTestCase):
    def test_invalid_divergence_strategy_raises(self) -> None:
        with self.assertRaises(ValueError, msg="on_divergence"):
            plan_consolidation((), on_divergence="invalid-strategy")

    def test_empty_stores_returns_plan_with_no_actions(self) -> None:
        plan = plan_consolidation(())
        self.assertEqual(plan.identical, ())
        self.assertEqual(plan.to_copy, ())
        self.assertEqual(plan.conflicts, ())
        self.assertEqual(plan.to_archive, ())

    def test_all_stores_inferred_repo_none_returns_empty_plan(self) -> None:
        # Reproduces the Linux crash: _group_by_repo pops the None key, leaving
        # groups empty, so max(groups, ...) raises ValueError.
        store = _make_store(
            self.tmp,
            "some-slug",
            {"mem_a.md": _feedback("mem_a", "memory a")},
            inferred_repo=None,
        )
        plan = plan_consolidation((store,))
        self.assertEqual(plan.identical, ())
        self.assertEqual(plan.to_copy, ())
        self.assertEqual(plan.conflicts, ())
        self.assertEqual(plan.to_archive, ())

    def test_single_store_no_actions(self) -> None:
        store = _make_store(
            self.tmp,
            "main-slug",
            {"mem_a.md": _feedback("mem_a", "memory a")},
        )
        plan = plan_consolidation((store,))
        self.assertEqual(plan.to_copy, ())
        self.assertEqual(plan.to_archive, ())
        self.assertEqual(plan.canonical.project_slug, "main-slug")

    def test_identical_files_classified(self) -> None:
        shared_content = _feedback("shared_mem", "shared memory")
        store1 = _make_store(self.tmp, "main-slug", {"shared.md": shared_content})
        store2 = _make_store(
            self.tmp,
            "worktree-slug",
            {"shared.md": shared_content},
            is_worktree_slug=True,
        )
        plan = plan_consolidation((store1, store2))
        self.assertEqual(len(plan.identical), 1)
        self.assertEqual(plan.to_copy, ())

    def test_unique_secondary_files_classified_as_to_copy(self) -> None:
        store1 = _make_store(
            self.tmp,
            "main-slug",
            {"canonical_only.md": _feedback("canonical_only", "only in canonical")},
        )
        store2 = _make_store(
            self.tmp,
            "worktree-slug",
            {"secondary_only.md": _feedback("secondary_only", "only in secondary")},
            is_worktree_slug=True,
        )
        plan = plan_consolidation((store1, store2))
        self.assertEqual(len(plan.to_copy), 1)

    def test_diverged_files_classified_as_conflicts(self) -> None:
        store1 = _make_store(
            self.tmp,
            "main-slug",
            {"diverged.md": _feedback("diverged_canonical", "canonical version")},
        )
        store2 = _make_store(
            self.tmp,
            "worktree-slug",
            {"diverged.md": _feedback("diverged_secondary", "secondary version")},
            is_worktree_slug=True,
        )
        plan = plan_consolidation((store1, store2))
        self.assertEqual(len(plan.conflicts), 1)

    def test_plan_is_pure_no_side_effects(self) -> None:
        store = _make_store(
            self.tmp,
            "pure-slug",
            {"pure.md": _feedback("pure", "pure memory")},
        )
        plan = plan_consolidation((store,))
        self.assertIsInstance(plan, ConsolidationPlan)
        self.assertIsInstance(plan.scanned_at, datetime)
        self.assertIsNotNone(plan.scanned_at.tzinfo)

    def test_non_canonical_stores_added_to_archive(self) -> None:
        store1 = _make_store(
            self.tmp,
            "main-slug",
            {"mem.md": _feedback("mem", "memory")},
        )
        store2 = _make_store(
            self.tmp,
            "worktree-slug",
            {"other.md": _feedback("other", "other")},
            is_worktree_slug=True,
        )
        plan = plan_consolidation((store1, store2))
        self.assertGreaterEqual(len(plan.to_archive), 1)


# ---------------------------------------------------------------------------
# apply_plan — dry_run
# ---------------------------------------------------------------------------


class TestApplyPlanDryRun(MemoryTestCase):
    def test_dry_run_writes_nothing(self) -> None:
        store1 = _make_store(
            self.tmp,
            "dry-main",
            {"canonical_mem.md": _feedback("canonical_mem", "canonical")},
        )
        store2 = _make_store(
            self.tmp,
            "dry-worktree",
            {"secondary_mem.md": _feedback("secondary_mem", "secondary")},
            is_worktree_slug=True,
        )
        plan = plan_consolidation((store1, store2))

        archive_dest = self.tmp / "archive_dry"
        result = apply_plan(plan, archive_dest=archive_dest, dry_run=True)

        self.assertIsInstance(result, ConsolidationResult)
        self.assertTrue(result.dry_run)
        self.assertFalse(result.applied)
        if archive_dest.exists():
            self.assertFalse(
                any(archive_dest.rglob("*.md")),
                "dry_run must not write any .md files",
            )

    def test_dry_run_enumerates_actions(self) -> None:
        store1 = _make_store(
            self.tmp,
            "enum-main",
            {
                "identical.md": _feedback("identical", "same content"),
                "canonical_unique.md": _feedback("canonical_unique", "only in canonical"),
            },
        )
        store2 = _make_store(
            self.tmp,
            "enum-worktree",
            {
                "identical.md": _feedback("identical", "same content"),
                "worktree_unique.md": _feedback("worktree_unique", "only in worktree"),
            },
            is_worktree_slug=True,
        )
        plan = plan_consolidation((store1, store2))

        result = apply_plan(plan, dry_run=True)

        all_accounted = list(result.copied) + list(result.archived)
        self.assertGreaterEqual(len(all_accounted), 1)

    def test_dry_run_default_is_true(self) -> None:
        store = _make_store(
            self.tmp,
            "default-dryrun",
            {"mem.md": _feedback("mem", "memory")},
        )
        plan = plan_consolidation((store,))
        result = apply_plan(plan)  # no dry_run kwarg
        self.assertTrue(result.dry_run)
        self.assertFalse(result.applied)


# ---------------------------------------------------------------------------
# apply_plan — real apply
# ---------------------------------------------------------------------------


class TestApplyPlanReal(MemoryTestCase):
    def test_zero_loss_property(self) -> None:
        """Input file count must equal canonical + archived file count after apply."""
        shared = _feedback("shared", "shared memory")
        unique1 = _feedback("unique1", "unique to canonical")
        unique2 = _feedback("unique2", "unique to secondary")

        store1 = _make_store(
            self.tmp,
            "zeroloss-main",
            {
                "shared.md": shared,
                "unique1.md": unique1,
            },
        )
        store2 = _make_store(
            self.tmp,
            "zeroloss-worktree",
            {
                "shared.md": shared,
                "unique2.md": unique2,
            },
            is_worktree_slug=True,
        )
        plan = plan_consolidation((store1, store2))

        archive_dest = self.tmp / "archive_real"
        result = apply_plan(plan, archive_dest=archive_dest, dry_run=False)

        self.assertTrue(result.applied)
        self.assertFalse(result.dry_run)

        canonical_root = Path(plan.canonical.root) / "memory"
        canonical_files = {f.name for f in canonical_root.glob("*.md")}
        self.assertIn("unique2.md", canonical_files)

    def test_archive_not_delete(self) -> None:
        """Identical files from non-canonical store must be archived, not deleted."""
        shared = _feedback("shared", "shared")

        store1 = _make_store(self.tmp, "archive-main", {"shared.md": shared})
        store2 = _make_store(
            self.tmp, "archive-worktree", {"shared.md": shared}, is_worktree_slug=True
        )
        plan = plan_consolidation((store1, store2))

        archive_dest = self.tmp / "archive_nd"
        result = apply_plan(plan, archive_dest=archive_dest, dry_run=False)

        self.assertGreaterEqual(len(result.archived), 1)

    def test_to_archive_copies_store_contents_not_just_empty_dir(self) -> None:
        """apply_plan must copy the non-canonical store's memory/ files into the archive dir."""
        store1 = _make_store(
            self.tmp,
            "to-archive-main",
            {"shared.md": _feedback("shared", "shared")},
        )
        store2 = _make_store(
            self.tmp,
            "to-archive-worktree",
            {"shared.md": _feedback("shared", "shared")},
            is_worktree_slug=True,
        )
        plan = plan_consolidation((store1, store2))
        self.assertEqual(len(plan.to_archive), 1)
        non_canonical = store1 if plan.canonical is store2 else store2
        self.assertIn(non_canonical.root, plan.to_archive)

        archive_dest = self.tmp / "archive_contents"
        result = apply_plan(plan, archive_dest=archive_dest, dry_run=False)
        self.assertTrue(result.applied)

        timestamp = plan.scanned_at.strftime("%Y%m%dT%H%M%SZ")
        slug = plan.canonical.project_slug
        archive_dir = archive_dest / f"{slug}-{timestamp}"
        non_canonical_archive_dir = archive_dir / Path(non_canonical.root).name

        self.assertTrue(non_canonical_archive_dir.is_dir())
        archived_files = {
            f.name for f in non_canonical_archive_dir.iterdir() if f.is_file()
        }
        self.assertIn("shared.md", archived_files)
        self.assertEqual(
            (non_canonical_archive_dir / "shared.md").read_text(encoding="utf-8"),
            (Path(non_canonical.root) / "memory" / "shared.md").read_text(encoding="utf-8"),
        )

    def test_divergence_strategies(self) -> None:
        for strategy in ("keep-newest", "keep-both"):
            with self.subTest(strategy=strategy):
                store1 = _make_store(
                    self.tmp,
                    f"div-{strategy}-main",
                    {"diverged.md": _feedback("diverged_canonical", "canonical version")},
                )
                store2 = _make_store(
                    self.tmp,
                    f"div-{strategy}-worktree",
                    {"diverged.md": _feedback("diverged_secondary", "secondary version")},
                    is_worktree_slug=True,
                )
                plan = plan_consolidation((store1, store2), on_divergence=strategy)

                archive_dest = self.tmp / f"archive_{strategy}"
                result = apply_plan(plan, archive_dest=archive_dest, dry_run=False)

                if strategy == "keep-newest":
                    self.assertEqual(result.superseded, ())
                elif strategy == "keep-both" and plan.conflicts:
                    self.assertGreaterEqual(len(result.superseded), 1)

    def test_unrecognized_strategy_raises(self) -> None:
        with self.assertRaises(ValueError):
            plan_consolidation((), on_divergence="bad-strategy")

    def test_dry_run_superseded_names_match_real_apply(self) -> None:
        """dry_run=True preview must report the exact filenames a real apply creates."""
        store1 = _make_store(
            self.tmp,
            "kb-main",
            {"diverged.md": _feedback("diverged_canonical", "canonical version")},
        )
        store2 = _make_store(
            self.tmp,
            "kb-worktree",
            {"diverged.md": _feedback("diverged_secondary", "secondary version")},
            is_worktree_slug=True,
        )
        plan = plan_consolidation((store1, store2), on_divergence="keep-both")
        self.assertTrue(plan.conflicts)

        preview = apply_plan(plan, archive_dest=self.tmp / "preview-archive", dry_run=True)
        real = apply_plan(plan, archive_dest=self.tmp / "real-archive", dry_run=False)

        preview_names = {Path(p).name for p in preview.superseded}
        real_names = {Path(p).name for p in real.superseded}
        self.assertEqual(preview_names, real_names)


# ---------------------------------------------------------------------------
# TOCTOU abort
# ---------------------------------------------------------------------------


class TestTOCTOUAbort(MemoryTestCase):
    def test_mtime_change_after_plan_raises_runtime_error(self) -> None:
        """apply_plan must raise RuntimeError when a canonical file mtime changed since scan."""
        store1 = _make_store(
            self.tmp,
            "toctou-main",
            {"guarded.md": _feedback("guarded", "canonical guarded")},
        )
        store2 = _make_store(
            self.tmp,
            "toctou-worktree",
            {"secondary.md": _feedback("secondary", "secondary file")},
            is_worktree_slug=True,
        )
        plan = plan_consolidation((store1, store2))

        canonical_mem_path = Path(plan.canonical.memories[0].path)
        time.sleep(0.05)
        canonical_mem_path.touch()

        archive_dest = self.tmp / "archive_toctou"
        with self.assertRaises(RuntimeError) as ctx:
            apply_plan(plan, archive_dest=archive_dest, dry_run=False)
        err_msg = str(ctx.exception)
        self.assertTrue(
            "concurrent write" in err_msg or "modified since" in err_msg,
            f"unexpected RuntimeError message: {err_msg}",
        )

    def test_dry_run_not_affected_by_toctou_check(self) -> None:
        """dry_run skips the TOCTOU check and always succeeds."""
        store = _make_store(
            self.tmp,
            "dryrun-toctou",
            {"mem.md": _feedback("mem", "memory")},
        )
        plan = plan_consolidation((store,))

        archive_dest = self.tmp / "archive_dryrun_toctou"
        result = apply_plan(plan, archive_dest=archive_dest, dry_run=True)
        self.assertTrue(result.dry_run)

    def test_dry_run_immune_to_concurrent_mtime_change(self) -> None:
        """dry_run must return normally even when a canonical file's mtime changed since scan."""
        store1 = _make_store(
            self.tmp,
            "toctou-dryrun-main",
            {"guarded.md": _feedback("guarded", "canonical guarded")},
        )
        store2 = _make_store(
            self.tmp,
            "toctou-dryrun-worktree",
            {"secondary.md": _feedback("secondary", "secondary file")},
            is_worktree_slug=True,
        )
        plan = plan_consolidation((store1, store2))

        canonical_mem_path = Path(plan.canonical.memories[0].path)
        time.sleep(0.05)
        canonical_mem_path.touch()

        archive_dest = self.tmp / "archive_dryrun_toctou_mtime"
        result = apply_plan(plan, archive_dest=archive_dest, dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertFalse(result.applied)


# ---------------------------------------------------------------------------
# apply_plan — prompt divergence
# ---------------------------------------------------------------------------


def _make_conflicting_stores(tmp_path: Path, suffix: str):
    store1 = _make_store(
        tmp_path,
        f"prompt-{suffix}-main",
        {"diverged.md": _feedback("diverged_canonical", "canonical version")},
    )
    store2 = _make_store(
        tmp_path,
        f"prompt-{suffix}-worktree",
        {"diverged.md": _feedback("diverged_secondary", "secondary version")},
        is_worktree_slug=True,
    )
    return store1, store2


class TestOnDivergencePrompt(MemoryTestCase):
    def test_on_divergence_prompt_keep_canonical(self) -> None:
        store1, store2 = _make_conflicting_stores(self.tmp, "keep-k")
        plan = plan_consolidation((store1, store2), on_divergence="prompt")
        self.assertTrue(plan.conflicts)

        archive_dest = self.tmp / "archive_prompt_k"
        result = apply_plan(
            plan,
            archive_dest=archive_dest,
            dry_run=False,
            _stdin=io.StringIO("k\n"),
        )

        self.assertTrue(result.applied)
        self.assertEqual(result.superseded, ())
        self.assertGreaterEqual(len(result.archived), 1)
        archived_names = {Path(p).name for p in result.archived}
        self.assertIn("diverged.md", archived_names)

    def test_on_divergence_prompt_keep_both(self) -> None:
        store1, store2 = _make_conflicting_stores(self.tmp, "keep-b")
        plan = plan_consolidation((store1, store2), on_divergence="prompt")
        self.assertTrue(plan.conflicts)

        archive_dest = self.tmp / "archive_prompt_b"
        result = apply_plan(
            plan,
            archive_dest=archive_dest,
            dry_run=False,
            _stdin=io.StringIO("b\n"),
        )

        self.assertTrue(result.applied)
        self.assertGreaterEqual(len(result.superseded), 1)

    def test_on_divergence_prompt_quit_raises_system_exit(self) -> None:
        store1, store2 = _make_conflicting_stores(self.tmp, "quit")
        plan = plan_consolidation((store1, store2), on_divergence="prompt")
        self.assertTrue(plan.conflicts)

        archive_dest = self.tmp / "archive_prompt_q"
        with self.assertRaises(SystemExit) as ctx:
            apply_plan(
                plan,
                archive_dest=archive_dest,
                dry_run=False,
                _stdin=io.StringIO("q\n"),
            )
        self.assertEqual(ctx.exception.code, 1)

    def test_on_divergence_prompt_invalid_then_quit(self) -> None:
        store1, store2 = _make_conflicting_stores(self.tmp, "invalid-quit")
        plan = plan_consolidation((store1, store2), on_divergence="prompt")
        self.assertTrue(plan.conflicts)

        archive_dest = self.tmp / "archive_prompt_xq"
        with self.assertRaises(SystemExit) as ctx:
            apply_plan(
                plan,
                archive_dest=archive_dest,
                dry_run=False,
                _stdin=io.StringIO("x\nq\n"),
            )
        self.assertEqual(ctx.exception.code, 1)

    def test_on_divergence_prompt_eof_exits(self) -> None:
        """EOF (empty stdin) must not silently default to keep-canonical."""
        store1, store2 = _make_conflicting_stores(self.tmp, "eof-quit")
        plan = plan_consolidation((store1, store2), on_divergence="prompt")
        self.assertTrue(plan.conflicts)

        archive_dest = self.tmp / "archive_prompt_eof"
        with self.assertRaises(SystemExit) as ctx:
            apply_plan(
                plan,
                archive_dest=archive_dest,
                dry_run=False,
                _stdin=io.StringIO(""),
            )
        self.assertEqual(ctx.exception.code, 1)

    def test_on_divergence_prompt_double_invalid_exits(self) -> None:
        """Second invalid char must also exit rather than falling through to keep-canonical."""
        store1, store2 = _make_conflicting_stores(self.tmp, "double-invalid")
        plan = plan_consolidation((store1, store2), on_divergence="prompt")
        self.assertTrue(plan.conflicts)

        archive_dest = self.tmp / "archive_prompt_xx"
        with self.assertRaises(SystemExit) as ctx:
            apply_plan(
                plan,
                archive_dest=archive_dest,
                dry_run=False,
                _stdin=io.StringIO("x\ny\n"),
            )
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
