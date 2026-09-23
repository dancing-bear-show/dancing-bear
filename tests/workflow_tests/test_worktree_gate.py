"""Tests for workflow.worktree_gate and the snapshot-dirty / check-unlisted CLI.

The gate exists because commit-and-push stages exactly fix-results.json's
files_changed: on the first live run of review-fix-threads a fixer's test file
was missing from that list, and nothing noticed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import subprocess  # nosec B404 - drives a throwaway git repo in a temp dir
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.process import run_binary
from workflow.cli_dispatch_review import _cmd_check_unlisted, _cmd_snapshot_dirty
from workflow.worktree_gate import (
    _GIT_STATUS_TIMEOUT,
    committed_since,
    head_commit,
    parse_porcelain_z,
    snapshot_dirty,
    unlisted_changes,
)


class TestParsePorcelainZ(unittest.TestCase):
    def test_modified_and_untracked(self) -> None:
        self.assertEqual(parse_porcelain_z(" M src/a.py\0?? tests/test_a.py\0"),
                         {"src/a.py", "tests/test_a.py"})

    def test_rename_yields_both_paths(self) -> None:
        """The origin is a separate NUL field; skipping it would misread it as
        an entry and drop its first three characters."""
        self.assertEqual(parse_porcelain_z("R  new.py\0old.py\0 M x.py\0"),
                         {"new.py", "old.py", "x.py"})

    def test_paths_with_spaces_are_kept_whole(self) -> None:
        self.assertEqual(parse_porcelain_z("?? a dir/b c.py\0"), {"a dir/b c.py"})

    def test_empty_output(self) -> None:
        self.assertEqual(parse_porcelain_z(""), set())


class TestUnlistedChanges(unittest.TestCase):
    def test_new_unlisted_file_is_reported(self) -> None:
        self.assertEqual(unlisted_changes({}, {"src/a.py": "1", "tests/t.py": "2"}, ["src/a.py"]),
                         ["tests/t.py"])

    def test_preexisting_dirt_from_another_session_is_ignored(self) -> None:
        self.assertEqual(unlisted_changes({"notes.md": "1"}, {"notes.md": "1"}, []), [])

    def test_preexisting_dirt_edited_again_is_reported(self) -> None:
        """Already dirty is not a licence: a changed hash means this run touched it."""
        self.assertEqual(unlisted_changes({"notes.md": "1"}, {"notes.md": "2"}, []), ["notes.md"])

    def test_reverted_file_is_reported(self) -> None:
        self.assertEqual(unlisted_changes({"notes.md": "1"}, {}, []), ["notes.md"])

    def test_dot_slash_listing_matches(self) -> None:
        self.assertEqual(unlisted_changes({}, {"src/a.py": "1"}, ["./src/a.py"]), [])

    def test_committed_path_absent_from_current_is_still_reported(self) -> None:
        """A staged-and-committed file is clean in `current` -- git status can't
        see it -- so `committed` is the only signal that catches it."""
        self.assertEqual(
            unlisted_changes({}, {}, [], committed=["src/sneaky.py"]),
            ["src/sneaky.py"],
        )

    def test_committed_path_already_listed_is_not_reported(self) -> None:
        self.assertEqual(
            unlisted_changes({}, {}, ["src/a.py"], committed=["src/a.py"]),
            [],
        )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # nosec B603 B607 - fixed argv, temp repo


class _Repo(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        self.repo.mkdir()
        self.ws = Path(tmp.name) / "ws"
        self.ws.mkdir()
        _git(self.repo, "init", "-q")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "init")
        (self.repo / "src").mkdir()
        (self.repo / "src/a.py").write_text("a = 1\n")
        _git(self.repo, "add", "src/a.py")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "a")
        self.enterContext(contextlib.chdir(self.repo))

    def _run_cmd(self, func, **kwargs: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = func(argparse.Namespace(**kwargs))
        return rc, out.getvalue(), err.getvalue()

    def _snapshot(self) -> Path:
        path = self.ws / "baseline.json"
        rc, _, err = self._run_cmd(_cmd_snapshot_dirty, out=str(path))
        self.assertEqual(rc, 0, err)
        self._write_pr_context(path)
        return path

    def _write_pr_context(self, baseline_path: Path, sha256: str | None = None) -> Path:
        """Write pr-context.json beside baseline_path with its true hash.

        Mirrors init Step 5: hash the baseline right after writing it and
        record that as dirty_baseline_sha256. Pass sha256 to plant a wrong
        value for the tamper sad-path tests.
        """
        digest = sha256 if sha256 is not None else hashlib.sha256(baseline_path.read_bytes()).hexdigest()
        context_path = baseline_path.parent / "pr-context.json"
        context_path.write_text(json.dumps({"dirty_baseline_sha256": digest}))
        return context_path

    def _results(self, files: object) -> Path:
        path = self.ws / "fix-results.json"
        path.write_text(json.dumps({"files_changed": files}))
        return path


class TestCheckUnlistedCLI(_Repo):
    def test_fix_without_its_test_file_fails(self) -> None:
        """The dry-run shape: src listed, test file edited but not listed."""
        baseline = self._snapshot()
        (self.repo / "src/a.py").write_text("a = 2\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_a.py").write_text("pass\n")
        rc, out, _ = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                   fix_results=str(self._results(["src/a.py"])))
        self.assertEqual((rc, out), (1, "UNLISTED: tests/test_a.py\n"))

    def test_every_edit_listed_passes(self) -> None:
        baseline = self._snapshot()
        (self.repo / "src/a.py").write_text("a = 2\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_a.py").write_text("pass\n")
        rc, out, _ = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                   fix_results=str(self._results(["src/a.py", "tests/test_a.py"])))
        self.assertEqual((rc, out), (0, ""))

    def test_other_sessions_untouched_dirt_passes(self) -> None:
        (self.repo / "scratch.txt").write_text("someone else's\n")
        baseline = self._snapshot()
        (self.repo / "src/a.py").write_text("a = 2\n")
        rc, _, _ = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                 fix_results=str(self._results(["src/a.py"])))
        self.assertEqual(rc, 0)

    def test_unlisted_protected_edit_is_reported(self) -> None:
        """An edit that skipped the list would also have skipped check-paths."""
        baseline = self._snapshot()
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude/settings.json").write_text("{}\n")
        rc, out, _ = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                   fix_results=str(self._results([])))
        self.assertEqual((rc, out), (1, "UNLISTED: .claude/settings.json\n"))

    def test_bad_inputs_fail_closed(self) -> None:
        baseline = self._snapshot()
        cases = {
            "missing baseline": dict(baseline=str(self.ws / "nope.json"),
                                     fix_results=str(self._results([]))),
            "files_changed not a list": dict(baseline=str(baseline),
                                             fix_results=str(self._results("src/a.py"))),
            "files_changed holds a non-string": dict(baseline=str(baseline),
                                                     fix_results=str(self._results([1]))),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                rc, _, err = self._run_cmd(_cmd_check_unlisted, **kwargs)
                self.assertEqual(rc, 1)
                self.assertIn("check-unlisted:", err)

    def test_baseline_without_dirty_object_fails(self) -> None:
        bad = self.ws / "bad.json"
        bad.write_text(json.dumps({"paths": []}))
        self._write_pr_context(bad)
        rc, _, err = self._run_cmd(_cmd_check_unlisted, baseline=str(bad),
                                   fix_results=str(self._results([])))
        self.assertEqual(rc, 1)
        self.assertIn("no 'dirty' object", err)

    def test_baseline_without_head_fails_closed(self) -> None:
        """Without the recorded HEAD a committed unlisted file is invisible,
        so a head-less baseline must fail rather than skip that check."""
        bad = self.ws / "nohead.json"
        bad.write_text(json.dumps({"dirty": {}}))
        self._write_pr_context(bad)
        rc, _, err = self._run_cmd(_cmd_check_unlisted, baseline=str(bad),
                                   fix_results=str(self._results([])))
        self.assertEqual(rc, 1)
        self.assertIn("no 'head' commit", err)


class TestCheckUnlistedBaselineProvenance(_Repo):
    """A fixer has Write/Bash access to the same {workspace}/outputs/
    directory dirty-baseline.json lives in, so check-unlisted must not trust
    it without verifying it against pr-context.json's recorded hash."""

    def test_tampered_baseline_is_rejected(self) -> None:
        """A fixer rewrites dirty-baseline.json (e.g. with post-edit hashes,
        or dropping its own unlisted entry) after init recorded its hash."""
        baseline = self._snapshot()
        baseline.write_text(json.dumps({"dirty": {}, "head": "0" * 40}))
        rc, out, err = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                     fix_results=str(self._results([])))
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("does not match dirty_baseline_sha256", err)

    def test_missing_pr_context_is_rejected(self) -> None:
        """No sibling pr-context.json at all -- e.g. a stale workspace from
        before this provenance check existed -- must fail closed, not pass
        by skipping verification."""
        path = self.ws / "baseline.json"
        rc, _, err = self._run_cmd(_cmd_snapshot_dirty, out=str(path))
        self.assertEqual(rc, 0, err)
        rc, out, err = self._run_cmd(_cmd_check_unlisted, baseline=str(path),
                                     fix_results=str(self._results([])))
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("pr-context.json not found", err)

    def test_pr_context_missing_hash_field_is_rejected(self) -> None:
        baseline = self._snapshot()
        (self.ws / "pr-context.json").write_text(json.dumps({"number": 406}))
        rc, out, err = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                     fix_results=str(self._results([])))
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("no 'dirty_baseline_sha256' string", err)

    def test_pr_context_non_string_hash_field_is_rejected(self) -> None:
        baseline = self._snapshot()
        (self.ws / "pr-context.json").write_text(json.dumps({"dirty_baseline_sha256": 12345}))
        rc, _, err = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                   fix_results=str(self._results([])))
        self.assertEqual(rc, 1)
        self.assertIn("no 'dirty_baseline_sha256' string", err)

    def test_verified_baseline_still_passes(self) -> None:
        """Happy path: init's real hash matches, so a legitimate baseline
        with no unlisted edits still passes."""
        baseline = self._snapshot()
        (self.repo / "src/a.py").write_text("a = 2\n")
        rc, out, _ = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                   fix_results=str(self._results(["src/a.py"])))
        self.assertEqual((rc, out), (0, ""))

    def test_baseline_is_not_reread_after_hash_verification(self) -> None:
        """A fixer process races the check: it rewrites dirty-baseline.json
        (with a false 'clean' dirty map so its own edit looks pre-existing)
        immediately after the hash check reads it for hashing. A second,
        separate read of the same path would pick up that rewritten content
        even though the hash matched the original bytes -- the TOCTOU this
        gate must close. _verify_baseline_provenance must parse the exact
        bytes it hashed and the caller must reuse that object, so the
        malicious rewrite is never consulted."""
        baseline = self._snapshot()
        original_bytes = baseline.read_bytes()
        tampered = json.dumps({"dirty": {}, "head": "0" * 40}).encode("utf-8")
        self.assertNotEqual(original_bytes, tampered)

        real_read_bytes = Path.read_bytes
        call_count = {"n": 0}

        def racing_read_bytes(self_path: Path, *args: object, **kwargs: object) -> bytes:
            data = real_read_bytes(self_path, *args, **kwargs)
            if self_path == baseline:
                call_count["n"] += 1
                # Simulate the race: a fixer overwrites the file right after
                # this read returns the bytes that get hashed.
                baseline.write_bytes(tampered)
            return data

        (self.repo / "src/a.py").write_text("a = 2\n")
        with patch.object(Path, "read_bytes", racing_read_bytes):
            rc, out, err = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                         fix_results=str(self._results(["src/a.py"])))
        # Exactly one read of the baseline's bytes: the hash-and-parse read.
        # If check-unlisted still re-read the file afterwards (the old bug),
        # that second read would see the tampered content instead.
        self.assertEqual(call_count["n"], 1)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "")
        # The file on disk is now the tampered version, proving the race
        # window existed -- yet the run still used the verified snapshot.
        self.assertEqual(baseline.read_bytes(), tampered)

    def test_verified_but_non_object_baseline_is_rejected(self) -> None:
        """A hash match only proves provenance, not shape: a baseline whose
        verified bytes decode to a JSON array (not an object) must still be
        rejected, matching the pre-fix behaviour where this check lived in
        _load_json_object."""
        path = self.ws / "baseline.json"
        path.write_text(json.dumps(["not", "an", "object"]))
        self._write_pr_context(path)
        rc, out, err = self._run_cmd(_cmd_check_unlisted, baseline=str(path),
                                     fix_results=str(self._results([])))
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("baseline is not a JSON object", err)


class TestHeadCommitAndCommittedSince(_Repo):
    def test_head_commit_returns_current_sha(self) -> None:
        sha = head_commit(self.repo)
        rc = subprocess.run(  # nosec B603 B607 - fixed argv, temp repo
            ["git", "rev-parse", "HEAD"], cwd=self.repo, check=True, capture_output=True, text=True
        )
        self.assertEqual(sha, rc.stdout.strip())
        self.assertEqual(len(sha), 40)

    def test_committed_since_reports_files_from_new_commits(self) -> None:
        baseline_head = head_commit(self.repo)
        (self.repo / "src/sneaky.py").write_text("x = 1\n")
        _git(self.repo, "add", "src/sneaky.py")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "-m", "sneaky commit")
        self.assertEqual(committed_since(self.repo, baseline_head), {"src/sneaky.py"})

    def test_committed_since_empty_when_no_new_commits(self) -> None:
        baseline_head = head_commit(self.repo)
        self.assertEqual(committed_since(self.repo, baseline_head), set())

    def test_committed_since_unresolvable_baseline_fails_closed(self) -> None:
        """A baseline sha that no longer resolves (e.g. rewritten history) must
        raise, not silently report no commits."""
        with self.assertRaises(RuntimeError):
            committed_since(self.repo, "0" * 40)

    def test_committed_since_catches_commit_then_revert(self) -> None:
        """A two-tree diff of baseline..HEAD nets a commit-then-revert of an
        unlisted file to no diff, since the file is identical at both ends --
        so this must walk each commit's own diff, not just the endpoints."""
        baseline_head = head_commit(self.repo)
        (self.repo / "src/sneaky.py").write_text("x = 1\n")
        _git(self.repo, "add", "src/sneaky.py")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "-m", "add sneaky")
        _git(self.repo, "rm", "-q", "src/sneaky.py")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "-m", "revert sneaky")
        # Sanity: the naive two-tree diff really does net to nothing.
        two_tree = run_binary(
            ("git", "diff", "--name-only", "-z", f"{baseline_head}..HEAD"),
            cwd=self.repo, timeout=_GIT_STATUS_TIMEOUT,
        )
        self.assertEqual(two_tree.stdout, "")
        self.assertEqual(committed_since(self.repo, baseline_head), {"src/sneaky.py"})

    def test_committed_since_reports_both_sides_of_a_rename(self) -> None:
        """Default rename detection would report only the destination, so a
        commit renaming a protected/unlisted source path could hide the
        source from check-paths. Both names must be reported."""
        (self.repo / "src/protected.py").write_text("p = 1\n")
        _git(self.repo, "add", "src/protected.py")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "-m", "add protected")
        baseline_head = head_commit(self.repo)
        _git(self.repo, "mv", "src/protected.py", "src/renamed.py")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "-m", "rename protected")
        # Sanity: default rename detection really does drop the source name.
        with_renames = run_binary(
            ("git", "diff", "--name-only", "-z", f"{baseline_head}..HEAD"),
            cwd=self.repo, timeout=_GIT_STATUS_TIMEOUT,
        )
        self.assertEqual(with_renames.stdout.split("\0"), ["src/renamed.py", ""])
        self.assertEqual(
            committed_since(self.repo, baseline_head),
            {"src/protected.py", "src/renamed.py"},
        )

    def test_committed_since_catches_a_file_added_only_by_a_merge_commit(self) -> None:
        """A path introduced by the merge commit itself -- present on neither
        parent, e.g. a conflict resolution amended to also add an unrelated
        file -- must still be reported. Without ``-m``, ``git log
        --name-only`` emits no diff at all for a merge commit, so this path
        would otherwise be invisible even though ``git status`` reports it
        clean once committed."""
        baseline_head = head_commit(self.repo)
        main_branch = subprocess.run(  # nosec B603 B607 - fixed argv, temp repo
            ["git", "branch", "--show-current"], cwd=self.repo, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        _git(self.repo, "checkout", "-q", "-b", "feature")
        (self.repo / "f.txt").write_text("f\n")
        _git(self.repo, "add", "f.txt")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "-m", "feature adds f.txt")
        _git(self.repo, "checkout", "-q", main_branch)
        (self.repo / "m.txt").write_text("m\n")
        _git(self.repo, "add", "m.txt")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "-m", "master adds m.txt")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "merge", "-q",
             "--no-edit", "feature")
        (self.repo / "src/sneaky.py").write_text("x = 1\n")
        _git(self.repo, "add", "src/sneaky.py")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "--amend", "--no-edit")
        # Sanity: prove the gap the fix closes -- the default (no -m) walk
        # really does miss the merge-only file, so this test would fail to
        # demonstrate anything if the repo fixture behaved differently.
        without_m = run_binary(
            ("git", "log", "--name-only", "--no-renames", "-z", "--pretty=format:",
             f"{baseline_head}..HEAD"),
            cwd=self.repo, timeout=_GIT_STATUS_TIMEOUT,
        )
        self.assertNotIn("src/sneaky.py", without_m.stdout.split("\0"))
        self.assertEqual(committed_since(self.repo, baseline_head), {
            "f.txt", "m.txt", "src/sneaky.py",
        })

    def test_check_unlisted_catches_a_staged_and_committed_file(self) -> None:
        """End-to-end: a fixer stages and commits an unlisted file before
        check-unlisted runs. git status alone reports it clean; folding
        committed_since's output into check-unlisted must still catch it."""
        baseline_head = head_commit(self.repo)
        (self.repo / "src/sneaky.py").write_text("x = 1\n")
        _git(self.repo, "add", "src/sneaky.py")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "-m", "sneaky commit")
        current = snapshot_dirty(self.repo)
        self.assertNotIn("src/sneaky.py", current)  # git status can't see it
        committed = committed_since(self.repo, baseline_head)
        unlisted = unlisted_changes({}, current, [], committed=committed)
        self.assertEqual(unlisted, ["src/sneaky.py"])


class TestCheckUnlistedCLICommittedSince(_Repo):
    """_cmd_check_unlisted itself must fold committed_since in -- not just
    the worktree_gate functions in isolation."""

    def test_staged_and_committed_unlisted_file_is_caught_via_cli(self) -> None:
        baseline = self._snapshot()
        (self.repo / "src/sneaky.py").write_text("x = 1\n")
        _git(self.repo, "add", "src/sneaky.py")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "-m", "sneaky commit")
        rc, out, _ = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                   fix_results=str(self._results([])))
        self.assertEqual((rc, out), (1, "UNLISTED: src/sneaky.py\n"))

    def test_staged_and_committed_listed_file_passes_via_cli(self) -> None:
        """Happy path: the same commit, but the file is in files_changed."""
        baseline = self._snapshot()
        (self.repo / "src/sneaky.py").write_text("x = 1\n")
        _git(self.repo, "add", "src/sneaky.py")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
             "-m", "sneaky commit")
        rc, out, _ = self._run_cmd(_cmd_check_unlisted, baseline=str(baseline),
                                   fix_results=str(self._results(["src/sneaky.py"])))
        self.assertEqual((rc, out), (0, ""))


class TestSnapshotDirtyTimeout(_Repo):
    def test_git_status_called_with_bounded_timeout(self) -> None:
        """snapshot_dirty must pass a real, non-None timeout -- not rely on
        the default-unbounded run_binary call the reviewer flagged."""
        from workflow.worktree_gate import run_binary as real_run_binary

        with patch(
            "workflow.worktree_gate.run_binary", side_effect=real_run_binary
        ) as mock_run:
            snapshot_dirty(self.repo)
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("timeout"), _GIT_STATUS_TIMEOUT)
        self.assertIsNotNone(kwargs.get("timeout"))

    def test_hung_git_status_fails_closed(self) -> None:
        """A git process that exceeds the timeout must raise, not hang or
        report the tree clean."""
        with patch("workflow.worktree_gate._GIT_STATUS_TIMEOUT", 0.05), \
             patch("workflow.worktree_gate._STATUS_CMD", ("sleep", "5")):
            with self.assertRaises(RuntimeError) as ctx:
                snapshot_dirty(self.repo)
        self.assertIn("git status failed", str(ctx.exception))


class TestSnapshotOutsideRepo(unittest.TestCase):
    def test_git_failure_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                snapshot_dirty(tmp)
            with contextlib.chdir(tmp):
                err = io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    rc = _cmd_snapshot_dirty(argparse.Namespace(out=str(Path(tmp) / "b.json")))
            self.assertEqual(rc, 1)
            self.assertFalse((Path(tmp) / "b.json").exists())


if __name__ == "__main__":
    unittest.main()
