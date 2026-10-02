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


def _make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "one")
    return repo


#: The diff every default workspace swept; GUIDES is what the canonical selector picks for it.
CHANGED = ["src/workflow/sweep_record.py", "workflows/code/open-pr.yaml"]


def _make_workspace(root: Path, guides: list[str], review: str | None = "consolidated.json",
                    commit_id: str | None = None, changed: list[str] | None = None) -> Path:
    """A swarm workspace; ``commit_id`` defaults to the repo's HEAD, the commit it swept."""
    ws = root / "ws"
    (ws / "outputs").mkdir(parents=True)
    (ws / "outputs" / "changed-files.txt").write_text("\n".join(CHANGED if changed is None else changed) + "\n")
    swept = commit_id if commit_id is not None else _git(root / "repo", "rev-parse", "HEAD")
    (ws / "outputs" / "pr-context.json").write_text(json.dumps({"commit_id": swept}))
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
        self.repo = _make_repo(self.root)
        self.head = _git(self.repo, "rev-parse", "HEAD")

    def _record_file(self, head: str) -> Path:
        common = Path(_git(self.repo, "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = self.repo / common
        return common.resolve() / "dancing-bear" / "concern-sweeps" / f"{head}.json"

    # --- happy paths -----------------------------------------------------

    def test_write_then_check(self) -> None:
        ws = _make_workspace(self.root, GUIDES)
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
        ws = _make_workspace(self.root, GUIDES)
        self.assertEqual(_run(self.repo, "write", "--head", self.head, "--workspace", str(ws))[0], 0)
        other = self.root / "wt2"
        _git(self.repo, "worktree", "add", "-q", "-b", "other", str(other))
        code, out, _ = _run(other, "check", "--head", self.head)
        self.assertEqual((code, out.strip()), (0, "swept"))

    # --- refusals --------------------------------------------------------

    def test_write_refuses_a_head_that_is_not_checkout_head(self) -> None:
        ws = _make_workspace(self.root, GUIDES)
        old = self.head
        (self.repo / "a.txt").write_text("b\n")
        _git(self.repo, "commit", "-q", "-am", "two")
        code, _, err = _run(self.repo, "write", "--head", old, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("is not this checkout's HEAD", err)
        self.assertFalse(self._record_file(old).exists())

    def test_write_refuses_a_workspace_that_swept_an_earlier_commit(self) -> None:
        ws = _make_workspace(self.root, GUIDES)  # swept the first commit
        (self.repo / "a.txt").write_text("b\n")
        _git(self.repo, "commit", "-q", "-am", "two")
        new = _git(self.repo, "rev-parse", "HEAD")
        code, _, err = _run(self.repo, "write", "--head", new, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("re-run the swarm on HEAD", err)
        self.assertFalse(self._record_file(new).exists())

    def test_write_refuses_a_workspace_without_pr_context(self) -> None:
        ws = _make_workspace(self.root, GUIDES)
        (ws / "outputs" / "pr-context.json").unlink()
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("pr-context.json", err)

    def test_malformed_sha_exits_2_for_every_subcommand(self) -> None:
        ws = _make_workspace(self.root, GUIDES)
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
        ws = _make_workspace(self.root, [g for g in GUIDES if g != "collateral-damage.md"])
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("collateral-damage.md", err)
        self.assertFalse(self._record_file(self.head).exists())

    def test_docs_only_diff_records_with_the_guides_the_selector_picks(self) -> None:
        docs = ["README.md"]
        picked = select_guides(docs)
        self.assertNotIn("collateral-damage.md", picked)
        ws = _make_workspace(self.root, picked, changed=docs)
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 0, err)

    def test_write_refuses_a_missing_or_empty_changed_files_list(self) -> None:
        ws = _make_workspace(self.root, GUIDES, changed=[])
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
        ws = _make_workspace(self.root, GUIDES)
        for doc in ({}, {"findings": None}, []):
            with self.subTest(doc=doc):
                (ws / "outputs" / "consolidated.json").write_text(json.dumps(doc))
                code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
                self.assertEqual(code, 2)
                self.assertIn("no findings list", err)
        self.assertFalse(self._record_file(self.head).exists())

    def test_write_refuses_a_missing_or_unparseable_index(self) -> None:
        ws = _make_workspace(self.root, GUIDES)
        index = ws / "outputs" / "concern-sweep-index.json"
        index.write_text("{not json")
        self.assertEqual(_run(self.repo, "write", "--head", self.head, "--workspace", str(ws))[0], 2)
        index.unlink()
        code, _, err = _run(self.repo, "write", "--head", self.head, "--workspace", str(ws))
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_write_refuses_when_review_output_is_missing(self) -> None:
        ws = _make_workspace(self.root, GUIDES, review=None)
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
