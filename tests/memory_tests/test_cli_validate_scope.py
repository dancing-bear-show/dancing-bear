"""Scope safety for `memory validate --fix`: explicit store scope, dry-run, per-store repo defaults."""

from __future__ import annotations

import contextlib
import io
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import memory.cli as memory_cli
from memory.models import MemoryStore
from memory.parser import parse_memory_file
from memory.validation import _check_ref_dead_path, _check_stale_superseded_pr, _CheckContext, run_checks
from tests.memory_tests.fixtures import MemoryTestCase, write_memory_dir

SLUG_A = "-Users-alice-code-aaa"
SLUG_B = "-Users-alice-code-bbb"

# Fixable: no type (schema-missing-type fix rewrites the frontmatter) and the
# file is absent from MEMORY.md (index-orphan fix rewrites the index).
_UNTYPED = "---\nname: feedback_x\ndescription: d\nmetadata:\n  node_type: memory\n---\n\n**Why:** x\n\n**How to apply:** y\n"


def _run_validate(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = memory_cli.main(["validate", *argv])
    return rc, out.getvalue(), err.getvalue()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _store(root: Path, memories: tuple = ()) -> MemoryStore:
    return MemoryStore(
        project_slug="s",
        root=str(root),
        memories=memories,
        non_memory_files=(),
        index_path=None,
        index_entries=(),
        inferred_repo=None,
        is_worktree_slug=False,
    )


class TestValidateFixScope(MemoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        projects = self.home / ".claude" / "projects"
        projects.mkdir(parents=True)
        self.dir_a = write_memory_dir(projects, SLUG_A, [("feedback_x.md", _UNTYPED), ("MEMORY.md", "# Index\n")])
        self.dir_b = write_memory_dir(projects, SLUG_B, [("feedback_x.md", _UNTYPED), ("MEMORY.md", "# Index\n")])

    def _both(self) -> tuple[dict[str, bytes], dict[str, bytes]]:
        return _snapshot(self.dir_a), _snapshot(self.dir_b)

    def test_fix_without_scope_is_rejected_and_writes_nothing(self) -> None:
        before = self._both()
        rc, _, err = _run_validate("--fix")
        self.assertEqual(rc, 1)
        self.assertIn("requires --store SLUG or --all-stores", err)
        self.assertEqual(self._both(), before)

    def test_fix_with_store_touches_only_that_store(self) -> None:
        before_a, before_b = self._both()
        _run_validate("--fix", f"--store={SLUG_A}")
        self.assertNotEqual(_snapshot(self.dir_a), before_a)
        self.assertEqual(_snapshot(self.dir_b), before_b)

    def test_fix_with_all_stores_touches_both(self) -> None:
        before_a, before_b = self._both()
        _run_validate("--fix", "--all-stores")
        self.assertNotEqual(_snapshot(self.dir_a), before_a)
        self.assertNotEqual(_snapshot(self.dir_b), before_b)

    def test_store_and_all_stores_rejected(self) -> None:
        before = self._both()
        rc, _, err = _run_validate("--fix", f"--store={SLUG_A}", "--all-stores")
        self.assertEqual(rc, 1)
        self.assertIn("cannot be combined", err)
        self.assertEqual(self._both(), before)

    def test_fix_dry_run_leaves_files_identical_and_reports_fixable(self) -> None:
        before = self._both()
        rc, out, _ = _run_validate("--fix", "--dry-run", "--all-stores")
        self.assertEqual(self._both(), before)
        self.assertNotEqual(rc, 0)
        self.assertIn("schema-missing-type", out)
        self.assertIn('"fixable": "True"', out)

    def test_dry_run_without_fix_rejected(self) -> None:
        rc, _, err = _run_validate("--dry-run")
        self.assertEqual(rc, 1)
        self.assertIn("requires --fix", err)

    def test_read_only_validate_still_scans_all_stores(self) -> None:
        _, out, _ = _run_validate("--check", "schema-missing-type")
        self.assertEqual(out.count("schema-missing-type"), 2)


class TestMultiStoreCwdDefaults(MemoryTestCase):
    def test_no_cwd_claude_md_when_cwd_default_disabled(self) -> None:
        (self.tmp / "CLAUDE.md").write_text("rules", encoding="utf-8")
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.tmp)
        captured: list[_CheckContext] = []

        def spy(_store: MemoryStore, ctx: _CheckContext) -> tuple:
            captured.append(ctx)
            return ()

        with patch.dict("memory.validation.CHECK_REGISTRY", {"staleness": spy}):
            run_checks(_store(self.tmp), checks=("staleness",), cwd_default=False)
            run_checks(_store(self.tmp), checks=("staleness",))
        self.assertEqual(captured[0].claude_md_paths, ())
        self.assertEqual(len(captured[1].claude_md_paths), 1)


def _project_memory(tmp: Path, body: str):
    f = tmp / "project_a.md"
    f.write_text(f"---\nname: project_a\ndescription: d\ntype: project\n---\n\n{body}\n", encoding="utf-8")
    return parse_memory_file(f, project_slug="s")


class TestRefDeadPathMissingRepo(MemoryTestCase):
    def test_nonexistent_repo_yields_no_findings(self) -> None:
        store = _store(self.tmp, (_project_memory(self.tmp, "See src/core/x.py and `src/mail/y.py`."),))
        ctx = _CheckContext(repo=self.tmp / "no-such-repo--claude-worktrees-x", claude_md_paths=(), fix=False)
        self.assertEqual(_check_ref_dead_path(store, ctx), ())


class TestStaleSupersededPrRobustness(MemoryTestCase):
    def test_non_dict_response_is_skipped(self) -> None:
        store = _store(self.tmp, (_project_memory(self.tmp, "See PR #7."),))
        ctx = _CheckContext(repo=None, claude_md_paths=(), fix=False)
        for payload in ([], "x", None, 5):
            with self.subTest(payload=payload):
                results = _check_stale_superseded_pr(store, ctx, github_caller=lambda _n, p=payload: p)
                self.assertEqual(results, ())

    def test_default_caller_resolved_against_repo_root_with_timeout(self) -> None:
        repo = self.tmp / "repo"
        (repo / "bin").mkdir(parents=True)
        (repo / "bin" / "github").write_text("#!/bin/sh\n", encoding="utf-8")
        ctx = _CheckContext(repo=repo, claude_md_paths=(), fix=False)
        store = _store(self.tmp, (_project_memory(self.tmp, "See PR #7."),))
        calls: list[tuple[list[str], dict]] = []

        class _Done:
            stdout = '{"state": "MERGED"}'

        def fake_run(argv: list[str], **kw: object) -> _Done:
            calls.append((argv, kw))
            return _Done()

        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(elsewhere)
        with patch("memory.validation.subprocess.run", fake_run):
            results = _check_stale_superseded_pr(store, ctx)
        self.assertEqual(len(results), 1)
        argv, kw = calls[0]
        self.assertEqual(argv[0], str(repo / "bin" / "github"))
        self.assertEqual(kw["cwd"], repo)
        self.assertIsNotNone(kw.get("timeout"))


if __name__ == "__main__":
    unittest.main()
