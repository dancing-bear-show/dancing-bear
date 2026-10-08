"""Tests for workflow sweep-record: per-commit evidence that the concern swarm ran."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess  # nosec B404 - builds throwaway git repos with fixed argv
import tempfile
import unittest
from pathlib import Path

from workflow import sweep_record
from workflow.cli import main
from workflow.concern_select import select_guides

_GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(  # nosec B603 B607 - fixed argv
        ["git", *args], cwd=str(cwd), env=_GIT_ENV, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _make_repo(root: Path) -> tuple[Path, str]:
    """Create a two-commit repo whose HEAD diff matches CHANGED.

    Returns (repo, merge_base_sha).  HEAD adds the CHANGED files; merge_base is
    the parent commit so ``git diff <merge_base>..HEAD --name-only`` returns CHANGED.
    """
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "base")
    merge_base = _git(repo, "rev-parse", "HEAD")
    for p in CHANGED:
        full = repo / p
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(f"{p}\n")
        _git(repo, "add", p)
    _git(repo, "commit", "-q", "-m", "feat")
    return repo, merge_base


#: The diff every default workspace swept; GUIDES is what the canonical selector picks for it.
CHANGED = ["src/workflow/sweep_record.py", "workflows/code/open-pr.yaml"]


def _make_workspace(root: Path, guides: list[str], review: str | None = "consolidated.json",
                    commit_id: str | None = None, changed: list[str] | None = None,
                    merge_base: str | None = None) -> Path:
    """A swarm workspace; ``commit_id`` defaults to the repo's HEAD, the commit it swept.

    When *merge_base* is given it is stored in pr-context.json so the diff
    check can validate without falling back to git.
    """
    ws = root / "ws"
    (ws / "outputs").mkdir(parents=True)
    (ws / "outputs" / "changed-files.txt").write_text("\n".join(CHANGED if changed is None else changed) + "\n")
    swept = commit_id if commit_id is not None else _git(root / "repo", "rev-parse", "HEAD")
    ctx: dict[str, object] = {"commit_id": swept, "head_sha": swept}
    if merge_base is not None:
        ctx["merge_base"] = merge_base
    (ws / "outputs" / "pr-context.json").write_text(json.dumps(ctx))
    index = {
        "total": len(guides),
        "items": [{"index": str(i), "data": {"guide": g}} for i, g in enumerate(guides)],
    }
    (ws / "outputs" / "concern-sweep-index.json").write_text(json.dumps(index))
    if review:
        (ws / "outputs" / review).write_text(json.dumps({"findings": []}))
    return ws


def _run(cwd: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.chdir(cwd), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["sweep-record", *argv])
    return code, out.getvalue(), err.getvalue()


GUIDES = select_guides(CHANGED)


class SweepRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo, self.merge_base = _make_repo(self.root)
        self.head = _git(self.repo, "rev-parse", "HEAD")

    def _record_file(self, head: str) -> Path:
        common = Path(_git(self.repo, "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = self.repo / common
        return common.resolve() / "dancing-bear" / "concern-sweeps" / f"{head}.json"

    # --- happy paths -----------------------------------------------------

    def test_write_then_check(self) -> None:
        ws = _make_workspace(self.root, GUIDES, merge_base=self.merge_base)
        code, out, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 0, err)
        path = self._record_file(self.head)
        self.assertEqual(out.strip(), str(path))
        data = json.loads(path.read_text())
        self.assertEqual(data["head_sha"], self.head)
        self.assertEqual(data["mode"], "swept")
        self.assertEqual(data["guides"], GUIDES)
        self.assertEqual(data["workspace"], str(ws))
        self.assertIsNone(data["reason"])
        self.assertRegex(data["recorded_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(path.parent.glob(".tmp-*")), [])
        code, out, _ = _run(self.repo, "check", "--head", self.head)
        self.assertEqual((code, out.strip()), (0, "swept"))

    def test_waive_then_check(self) -> None:
        code, _, err = _run(self.repo, "waive", "--head", self.head, "--reason", "docs only")
        self.assertEqual(code, 0, err)
        data = json.loads(self._record_file(self.head).read_text())
        self.assertEqual(
            (data["mode"], data["guides"], data["workspace"], data["reason"]),
            ("waived", [], None, "docs only"),
        )
        code, out, _ = _run(self.repo, "check", "--head", self.head)
        self.assertEqual((code, out.strip()), (0, "waived"))

    def test_check_works_from_a_subdirectory(self) -> None:
        _run(self.repo, "waive", "--head", self.head, "--reason", "r")
        sub = self.repo / "sub"
        sub.mkdir()
        self.assertEqual(_run(sub, "check", "--head", self.head)[0], 0)

    def test_record_is_visible_from_a_second_worktree(self) -> None:
        ws = _make_workspace(self.root, GUIDES, merge_base=self.merge_base)
        self.assertEqual(_run(self.repo, "write", "--head", self.head, "--workspace", str(ws))[0], 0)
        other = self.root / "wt2"
        _git(self.repo, "worktree", "add", "-q", "-b", "other", str(other))
        code, out, _ = _run(other, "check", "--head", self.head)
        self.assertEqual((code, out.strip()), (0, "swept"))

    # --- refusals --------------------------------------------------------

    def test_write_refuses_a_head_that_is_not_checkout_head(self) -> None:
        ws = _make_workspace(self.root, GUIDES, merge_base=self.merge_base)
        old = self.head
        (self.repo / "a.txt").write_text("b\n")
        _git(self.repo, "commit", "-q", "-am", "two")
        code, _, err = _run(self.repo, "write", "--head", old, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("is not this checkout's HEAD", err)
        self.assertFalse(self._record_file(old).exists())

    def test_write_refuses_a_workspace_that_swept_an_earlier_commit(self) -> None:
        ws = _make_workspace(self.root, GUIDES, merge_base=self.merge_base)  # swept the first commit
        (self.repo / "a.txt").write_text("b\n")
        _git(self.repo, "commit", "-q", "-am", "two")
        new = _git(self.repo, "rev-parse", "HEAD")
        code, _, err = _run(self.repo, "write", "--head", new, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("re-run the swarm on HEAD", err)
        self.assertFalse(self._record_file(new).exists())

    def test_write_refuses_a_workspace_without_pr_context(self) -> None:
        ws = _make_workspace(self.root, GUIDES, merge_base=self.merge_base)
        (ws / "outputs" / "pr-context.json").unlink()
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("pr-context.json", err)

    def test_malformed_sha_exits_2_for_every_subcommand(self) -> None:
        ws = _make_workspace(self.root, GUIDES, merge_base=self.merge_base)
        bad = [self.head[:12], self.head.upper(), self.head + "0", "../" + self.head[3:], ""]
        for sha in bad:
            for argv in (
                ("write", "--head", sha, "--workspace", str(ws)),
                ("waive", "--head", sha, "--reason", "r"),
                ("check", "--head", sha),
            ):
                with self.subTest(sha=sha, cmd=argv[0]):
                    code, _, err = _run(self.repo, *argv)
                    self.assertEqual(code, 2)
                    self.assertIn("40-character", err)
        records = self._record_file(self.head).parent
        self.assertFalse(records.exists() and any(records.iterdir()))

    def test_write_refuses_an_index_missing_a_guide_the_selector_picks(self) -> None:
        self.assertIn("collateral-damage.md", GUIDES)  # src/ and workflows/ changes select it
        ws = _make_workspace(self.root, [g for g in GUIDES if g != "collateral-damage.md"],
                             merge_base=self.merge_base)
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("collateral-damage.md", err)
        self.assertFalse(self._record_file(self.head).exists())

    def test_docs_only_diff_records_with_the_guides_the_selector_picks(self) -> None:
        docs = ["README.md"]
        picked = select_guides(docs)
        self.assertNotIn("collateral-damage.md", picked)
        # Need a repo whose actual diff matches docs; can't reuse self.repo (diff is CHANGED).
        docs_root = self.root / "docs_sub"
        docs_root.mkdir()
        docs_repo, docs_mb, docs_head = _make_repo_with_diff(docs_root, docs)
        docs_head = _git(docs_repo, "rev-parse", "HEAD")
        ws = _make_workspace_with_context(docs_root, picked, docs_mb, docs_head, docs)
        code, _, err = _run(docs_repo, "write", "--head", docs_head, "--workspace", str(ws))
        self.assertEqual(code, 0, err)

    def test_write_refuses_unreadable_or_non_utf8_changed_files(self) -> None:
        """An unreadable or non-UTF-8 changed-files.txt must exit 2, not raise an uncaught exception."""
        ws = _make_workspace(self.root, GUIDES, merge_base=self.merge_base)
        changed = ws / "outputs" / "changed-files.txt"
        # Non-UTF-8 content: write raw bytes that are not valid UTF-8.
        changed.write_bytes(b"\xff\xfe invalid utf-8 bytes\n")
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 2, err)
        self.assertIn("changed-files.txt", err)
        # Replace with a directory so read_text raises OSError.
        changed.unlink()
        changed.mkdir()
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 2, err)
        self.assertIn("changed-files.txt", err)

    def test_write_refuses_a_missing_or_empty_changed_files_list(self) -> None:
        ws = _make_workspace(self.root, GUIDES, changed=[], merge_base=self.merge_base)
        (ws / "outputs" / "changed-files.txt").write_text("\n")
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("empty", err)
        (ws / "outputs" / "changed-files.txt").unlink()
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("changed-files.txt not found", err)

    def test_write_refuses_the_empty_sentinel_a_skipped_stage_leaves(self) -> None:
        """PR #454 review: a skipped large-path consolidate wrote {} over the real report."""
        ws = _make_workspace(self.root, GUIDES, merge_base=self.merge_base)
        sentinels: tuple[object, ...] = ({}, {"findings": None}, [])
        for doc in sentinels:
            with self.subTest(doc=doc):
                (ws / "outputs" / "consolidated.json").write_text(json.dumps(doc))
                code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
                self.assertEqual(code, 2)
                self.assertIn("no findings list", err)
        self.assertFalse(self._record_file(self.head).exists())

    def test_write_refuses_a_missing_or_unparseable_index(self) -> None:
        ws = _make_workspace(self.root, GUIDES, merge_base=self.merge_base)
        index = ws / "outputs" / "concern-sweep-index.json"
        index.write_text("{not json")
        self.assertEqual(_run(self.repo, "write", "--head", self.head, "--workspace", str(ws))[0], 2)
        index.unlink()
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_write_refuses_when_review_output_is_missing(self) -> None:
        ws = _make_workspace(self.root, GUIDES, review=None, merge_base=self.merge_base)
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("consolidated.json", err)
        self.assertFalse(self._record_file(self.head).exists())

    def test_waive_refuses_an_empty_reason(self) -> None:
        for reason in ("", "   "):
            with self.subTest(reason=reason):
                code, _, err = _run(self.repo, "waive", "--head", self.head, "--reason", reason)
                self.assertEqual(code, 2)
                self.assertIn("--reason", err)
        self.assertFalse(self._record_file(self.head).exists())

    def test_check_on_unknown_sha_exits_1(self) -> None:
        code, out, _ = _run(self.repo, "check", "--head", "0" * 40)
        self.assertEqual((code, out), (1, ""))

    def test_check_ignores_a_record_naming_another_sha(self) -> None:
        path = self._record_file(self.head)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"head_sha": "1" * 40, "mode": "swept"}))
        self.assertEqual(_run(self.repo, "check", "--head", self.head)[0], 1)

    def test_review_outputs_cover_both_swarm_paths(self) -> None:
        self.assertEqual(set(sweep_record.REVIEW_OUTPUTS), {"review-consolidated", "consolidate"})


def _make_repo_with_diff(root: Path, paths: list[str]) -> tuple[Path, str, str]:
    """Create a repo where MERGE_BASE..HEAD changes exactly *paths*.

    Returns (repo, merge_base, head_sha).
    """
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-q", "-m", "base")
    merge_base = _git(repo, "rev-parse", "HEAD")
    for p in paths:
        full = repo / p
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(f"{p}\n")
        _git(repo, "add", p)
    _git(repo, "commit", "-q", "-m", "feat")
    head_sha = _git(repo, "rev-parse", "HEAD")
    return repo, merge_base, head_sha


def _make_workspace_with_context(root: Path, guides: list[str], merge_base: str, head_sha: str,
                                  changed: list[str]) -> Path:
    """A swarm workspace with full pr-context.json (merge_base + head_sha)."""
    ws = root / "ws"
    (ws / "outputs").mkdir(parents=True)
    (ws / "outputs" / "changed-files.txt").write_text("\n".join(changed) + "\n")
    ctx = {"commit_id": head_sha, "head_sha": head_sha, "merge_base": merge_base}
    (ws / "outputs" / "pr-context.json").write_text(json.dumps(ctx))
    index = {
        "total": len(guides),
        "items": [{"index": str(i), "data": {"guide": g}} for i, g in enumerate(guides)],
    }
    (ws / "outputs" / "concern-sweep-index.json").write_text(json.dumps(index))
    (ws / "outputs" / "consolidated.json").write_text(json.dumps({"findings": []}))
    return ws


class DiffValidationTests(unittest.TestCase):
    """_require_diff_matches_workspace — changed-files.txt must match git diff."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def _run_repo(self, repo: Path, ws: Path, head: str) -> tuple[int, str, str]:
        return _run(repo, "write", "--head", head, "--workspace", str(ws))

    def test_matching_list_records_successfully(self) -> None:
        paths = ["src/core/util.py", "workflows/code/open-pr.yaml"]
        repo, merge_base, head_sha = _make_repo_with_diff(self.root, paths)
        guides = select_guides(paths)
        ws = _make_workspace_with_context(self.root, guides, merge_base, head_sha, paths)
        code, _, err = self._run_repo(repo, ws, head_sha)
        self.assertEqual(code, 0, err)

    def test_extra_path_in_workspace_is_refused(self) -> None:
        paths = ["src/core/util.py"]
        repo, merge_base, head_sha = _make_repo_with_diff(self.root, paths)
        guides = select_guides(paths)
        extra = paths + ["src/core/extra.py"]
        ws = _make_workspace_with_context(self.root, guides, merge_base, head_sha, extra)
        code, _, err = self._run_repo(repo, ws, head_sha)
        self.assertEqual(code, 2)
        self.assertIn("extra paths in workspace", err)
        self.assertIn("src/core/extra.py", err)

    def test_missing_path_in_workspace_is_refused(self) -> None:
        paths = ["src/core/util.py", "src/core/other.py"]
        repo, merge_base, head_sha = _make_repo_with_diff(self.root, paths)
        guides = select_guides(paths)
        subset = paths[:1]
        ws = _make_workspace_with_context(self.root, guides, merge_base, head_sha, subset)
        code, _, err = self._run_repo(repo, ws, head_sha)
        self.assertEqual(code, 2)
        self.assertIn("missing paths from git diff", err)
        self.assertIn("src/core/other.py", err)

    def test_non_ascii_path_round_trips(self) -> None:
        path = "src/café/main.py"
        repo, merge_base, head_sha = _make_repo_with_diff(self.root, [path])
        guides = select_guides([path])
        ws = _make_workspace_with_context(self.root, guides, merge_base, head_sha, [path])
        code, _, err = self._run_repo(repo, ws, head_sha)
        self.assertEqual(code, 0, err)

    def test_absent_merge_base_recomputed_and_passes_when_list_matches(self) -> None:
        """When merge_base is absent, git recomputes it; if list matches, record is written."""
        paths = ["src/core/util.py"]
        repo, merge_base, head_sha = _make_repo_with_diff(self.root, paths)
        guides = select_guides(paths)
        # Workspace without merge_base — git must recompute from the base branch.
        # Set baseRefName to the actual merge_base sha so git can resolve it.
        ws = _make_workspace_with_context(self.root, guides, merge_base, head_sha, paths)
        # Remove merge_base from pr-context.json but leave baseRefName pointing at
        # the merge_base commit so _resolve_merge_base can find it.
        ctx = {"commit_id": head_sha, "head_sha": head_sha, "baseRefName": merge_base}
        (ws / "outputs" / "pr-context.json").write_text(json.dumps(ctx))
        code, _, err = self._run_repo(repo, ws, head_sha)
        self.assertEqual(code, 0, err)

    def test_absent_merge_base_recomputed_and_refuses_when_list_differs(self) -> None:
        """When merge_base is absent and recomputed, a mismatched list is still refused."""
        paths = ["src/core/util.py"]
        repo, merge_base, head_sha = _make_repo_with_diff(self.root, paths)
        guides = select_guides(paths)
        wrong = paths + ["src/core/extra.py"]
        ws = _make_workspace_with_context(self.root, guides, merge_base, head_sha, wrong)
        ctx = {"commit_id": head_sha, "head_sha": head_sha, "baseRefName": merge_base}
        (ws / "outputs" / "pr-context.json").write_text(json.dumps(ctx))
        code, _, err = self._run_repo(repo, ws, head_sha)
        self.assertEqual(code, 2)
        self.assertIn("extra paths in workspace", err)

    def test_unresolvable_base_ref_is_refused(self) -> None:
        """When neither merge_base nor a resolvable base ref is available, refuse."""
        paths = ["src/core/util.py"]
        repo, merge_base, head_sha = _make_repo_with_diff(self.root, paths)
        guides = select_guides(paths)
        ws = _make_workspace_with_context(self.root, guides, merge_base, head_sha, paths)
        # No merge_base, no baseRefName, no origin/main — must refuse.
        ctx = {"commit_id": head_sha, "head_sha": head_sha}
        (ws / "outputs" / "pr-context.json").write_text(json.dumps(ctx))
        code, _, err = self._run_repo(repo, ws, head_sha)
        self.assertEqual(code, 2)
        self.assertIn("cannot determine merge-base", err)

    def test_malformed_merge_base_sha_is_refused(self) -> None:
        """A merge_base that is not a valid 40-hex SHA must be refused."""
        paths = ["src/core/util.py"]
        repo, _, head_sha = _make_repo_with_diff(self.root, paths)
        guides = select_guides(paths)
        ws = _make_workspace_with_context(self.root, guides, "not-a-sha", head_sha, paths)
        code, _, err = self._run_repo(repo, ws, head_sha)
        self.assertEqual(code, 2)
        self.assertIn("merge_base", err)

    def test_waive_does_not_run_diff_check(self) -> None:
        """waive is the explicit escape hatch; it must not be reachable from write."""
        paths = ["src/core/util.py"]
        repo, _, head_sha = _make_repo_with_diff(self.root, paths)
        # waive with no workspace at all — if diff check were wired to waive, it would error.
        code, _, err = _run(repo, "waive", "--head", head_sha, "--reason", "exempt")
        self.assertEqual(code, 0, err)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
