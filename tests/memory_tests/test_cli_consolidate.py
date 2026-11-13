"""Coverage for memory.commands.consolidate: _plan_to_rows branches,
run() empty-stores early return, dry-run vs live apply, archive_dest override,
RuntimeError exit-code 3, and warnings on stderr.

Patches discover_stores and apply_plan where they are USED (memory.commands.consolidate),
not where they are defined, per project convention.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from memory.commands.consolidate import _plan_to_rows
from memory.consolidate import ConsolidationPlan, ConsolidationResult
from memory.discovery import load_store
from memory.models import MemoryStore
from tests.memory_tests.fixtures import MemoryTestCase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_store(tmp_path: Path, slug: str = "empty-slug") -> MemoryStore:
    store_root = tmp_path / slug
    (store_root / "memory").mkdir(parents=True)
    return load_store(slug, projects_root=tmp_path)


def _make_plan(
    *,
    identical: tuple[str, ...] = (),
    to_copy: tuple[str, ...] = (),
    conflicts: tuple[tuple[str, str], ...] = (),
    to_archive: tuple[str, ...] = (),
    on_divergence: str = "keep-newest",
    canonical: MemoryStore | None = None,
) -> ConsolidationPlan:
    if canonical is None:
        canonical = MemoryStore(
            project_slug="canonical-slug",
            root="/nonexistent/canonical",
            memories=(),
            non_memory_files=(),
            index_path=None,
            index_entries=(),
            inferred_repo=None,
            is_worktree_slug=False,
        )
    return ConsolidationPlan(
        canonical=canonical,
        identical=identical,
        to_copy=to_copy,
        conflicts=conflicts,
        to_archive=to_archive,
        on_divergence=on_divergence,
        scanned_at=datetime.now(UTC),
    )


def _make_result(
    *,
    dry_run: bool = True,
    applied: bool = False,
    copied: tuple[str, ...] = (),
    archived: tuple[str, ...] = (),
    superseded: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> ConsolidationResult:
    return ConsolidationResult(
        applied=applied,
        archived=archived,
        copied=copied,
        superseded=superseded,
        warnings=warnings,
        dry_run=dry_run,
    )


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Run memory.cli.main with the consolidate subcommand; return (rc, stdout, stderr)."""
    from memory.cli import main

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = main(["consolidate"] + argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# _plan_to_rows — unit coverage for every branch
# ---------------------------------------------------------------------------


class TestPlanToRows(unittest.TestCase):
    def test_empty_plan_produces_empty_rows(self) -> None:
        plan = _make_plan()
        self.assertEqual(_plan_to_rows(plan), [])

    def test_identical_files_produce_decision_identical(self) -> None:
        plan = _make_plan(identical=("mem_a.md", "mem_b.md"))
        rows = _plan_to_rows(plan)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {"path": "mem_a.md", "decision": "identical"})
        self.assertEqual(rows[1], {"path": "mem_b.md", "decision": "identical"})

    def test_to_copy_files_produce_decision_to_copy(self) -> None:
        plan = _make_plan(to_copy=("new_mem.md",))
        rows = _plan_to_rows(plan)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {"path": "new_mem.md", "decision": "to-copy"})

    def test_conflicts_produce_decision_conflict_with_arrow(self) -> None:
        plan = _make_plan(conflicts=(("loser.md", "winner.md"),))
        rows = _plan_to_rows(plan)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision"], "conflict")
        self.assertIn("loser.md", rows[0]["path"])
        self.assertIn("winner.md", rows[0]["path"])
        self.assertIn("<->", rows[0]["path"])

    def test_to_archive_produce_decision_to_archive_store(self) -> None:
        plan = _make_plan(to_archive=("/old/store/root",))
        rows = _plan_to_rows(plan)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {"path": "/old/store/root", "decision": "to-archive-store"})

    def test_all_categories_combined(self) -> None:
        plan = _make_plan(
            identical=("same.md",),
            to_copy=("new.md",),
            conflicts=(("a.md", "b.md"),),
            to_archive=("/archive",),
        )
        rows = _plan_to_rows(plan)
        decisions = [r["decision"] for r in rows]
        self.assertIn("identical", decisions)
        self.assertIn("to-copy", decisions)
        self.assertIn("conflict", decisions)
        self.assertIn("to-archive-store", decisions)
        self.assertEqual(len(rows), 4)


# ---------------------------------------------------------------------------
# run() — no stores discovered (early return)
# ---------------------------------------------------------------------------


class TestMainNoStores(MemoryTestCase):
    def test_empty_stores_returns_zero(self) -> None:
        with patch("memory.commands.consolidate.discover_stores", return_value=()):
            rc, _, _ = _run_cli([])
        self.assertEqual(rc, 0)

    def test_empty_stores_emits_empty_msg_to_stderr(self) -> None:
        with patch("memory.commands.consolidate.discover_stores", return_value=()):
            _, _, err = _run_cli([])
        self.assertIn("No stores discovered", err)

    def test_empty_stores_json_format_emits_valid_output(self) -> None:
        with patch("memory.commands.consolidate.discover_stores", return_value=()):
            _, out, _ = _run_cli(["--format", "json"])
        out_stripped = out.strip()
        if out_stripped:
            json.loads(out_stripped)  # must parse without error


# ---------------------------------------------------------------------------
# run() — dry run path
# ---------------------------------------------------------------------------


class TestMainDryRun(MemoryTestCase):
    def test_dry_run_returns_zero(self) -> None:
        store = _empty_store(self.tmp)
        plan = _make_plan()
        with (
            patch("memory.commands.consolidate.discover_stores", return_value=(store,)),
            patch("memory.commands.consolidate.plan_consolidation", return_value=plan),
        ):
            rc, _, _ = _run_cli(["--dry-run"])
        self.assertEqual(rc, 0)

    def test_dry_run_does_not_call_apply_plan(self) -> None:
        store = _empty_store(self.tmp)
        plan = _make_plan()
        with (
            patch("memory.commands.consolidate.discover_stores", return_value=(store,)),
            patch("memory.commands.consolidate.plan_consolidation", return_value=plan),
            patch("memory.commands.consolidate.apply_plan") as mock_apply,
        ):
            _run_cli(["--dry-run"])
        mock_apply.assert_not_called()

    def test_rows_emitted_before_dry_run_return(self) -> None:
        store = _empty_store(self.tmp)
        plan = _make_plan(identical=("mem.md",))
        with (
            patch("memory.commands.consolidate.discover_stores", return_value=(store,)),
            patch("memory.commands.consolidate.plan_consolidation", return_value=plan),
        ):
            _, out, _ = _run_cli(["--dry-run", "--format", "json"])
        rows = json.loads(out.strip())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision"], "identical")


# ---------------------------------------------------------------------------
# run() — live apply path (no error)
# ---------------------------------------------------------------------------


class TestMainApply(MemoryTestCase):
    def test_successful_apply_returns_zero(self) -> None:
        store = _empty_store(self.tmp)
        plan = _make_plan()
        result = _make_result(dry_run=False, applied=True)
        with (
            patch("memory.commands.consolidate.discover_stores", return_value=(store,)),
            patch("memory.commands.consolidate.plan_consolidation", return_value=plan),
            patch("memory.commands.consolidate.apply_plan", return_value=result),
        ):
            rc, _, _ = _run_cli([])
        self.assertEqual(rc, 0)

    def test_warnings_printed_to_stderr(self) -> None:
        store = _empty_store(self.tmp)
        plan = _make_plan()
        result = _make_result(dry_run=False, applied=True, warnings=("watch out for alpha",))
        with (
            patch("memory.commands.consolidate.discover_stores", return_value=(store,)),
            patch("memory.commands.consolidate.plan_consolidation", return_value=plan),
            patch("memory.commands.consolidate.apply_plan", return_value=result),
        ):
            _, _, err = _run_cli([])
        self.assertIn("watch out for alpha", err)
        self.assertIn("Warning:", err)

    def test_multiple_warnings_all_printed(self) -> None:
        store = _empty_store(self.tmp)
        plan = _make_plan()
        result = _make_result(
            dry_run=False,
            applied=True,
            warnings=("warning-one", "warning-two"),
        )
        with (
            patch("memory.commands.consolidate.discover_stores", return_value=(store,)),
            patch("memory.commands.consolidate.plan_consolidation", return_value=plan),
            patch("memory.commands.consolidate.apply_plan", return_value=result),
        ):
            _, _, err = _run_cli([])
        self.assertIn("warning-one", err)
        self.assertIn("warning-two", err)

    def test_archive_dest_passed_to_apply_plan(self) -> None:
        store = _empty_store(self.tmp)
        plan = _make_plan()
        result = _make_result(dry_run=False, applied=True)
        with (
            patch("memory.commands.consolidate.discover_stores", return_value=(store,)),
            patch("memory.commands.consolidate.plan_consolidation", return_value=plan),
            patch("memory.commands.consolidate.apply_plan", return_value=result) as mock_apply,
        ):
            _run_cli(["--archive-dest", "/nonexistent/custom-archive"])
        call_kwargs = mock_apply.call_args
        self.assertIsNotNone(call_kwargs)
        archive_dest_arg = call_kwargs[1].get("archive_dest") or call_kwargs[0][1]
        self.assertEqual(str(archive_dest_arg), "/nonexistent/custom-archive")


# ---------------------------------------------------------------------------
# run() — RuntimeError from apply_plan → exit code 3
# ---------------------------------------------------------------------------


class TestMainRuntimeError(MemoryTestCase):
    def test_runtime_error_returns_exit_code_3(self) -> None:
        store = _empty_store(self.tmp)
        plan = _make_plan()
        with (
            patch("memory.commands.consolidate.discover_stores", return_value=(store,)),
            patch("memory.commands.consolidate.plan_consolidation", return_value=plan),
            patch(
                "memory.commands.consolidate.apply_plan",
                side_effect=RuntimeError("concurrent write detected"),
            ),
        ):
            rc, _, _ = _run_cli([])
        self.assertEqual(rc, 3)

    def test_runtime_error_message_printed_to_stderr(self) -> None:
        store = _empty_store(self.tmp)
        plan = _make_plan()
        with (
            patch("memory.commands.consolidate.discover_stores", return_value=(store,)),
            patch("memory.commands.consolidate.plan_consolidation", return_value=plan),
            patch(
                "memory.commands.consolidate.apply_plan",
                side_effect=RuntimeError("TOCTOU abort: modified since scan"),
            ),
        ):
            _, _, err = _run_cli([])
        self.assertIn("TOCTOU abort", err)
        self.assertIn("Error:", err)


# ---------------------------------------------------------------------------
# run() — on_divergence argument is forwarded
# ---------------------------------------------------------------------------


class TestMainOnDivergence(MemoryTestCase):
    def test_on_divergence_passed_to_plan_consolidation(self) -> None:
        for strategy in ("keep-newest", "keep-both"):
            with self.subTest(strategy=strategy):
                store = _empty_store(self.tmp, slug=f"empty-{strategy}")
                plan = _make_plan()
                with (
                    patch("memory.commands.consolidate.discover_stores", return_value=(store,)),
                    patch(
                        "memory.commands.consolidate.plan_consolidation", return_value=plan
                    ) as mock_plan,
                ):
                    _run_cli(["--dry-run", "--on-divergence", strategy])
                mock_plan.assert_called_once()
                _, kwargs = mock_plan.call_args
                self.assertEqual(kwargs.get("on_divergence"), strategy)


if __name__ == "__main__":
    unittest.main()
