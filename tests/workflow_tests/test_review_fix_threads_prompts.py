"""Rendered-prompt checks for review-fix-threads, from its first live dry run.

Four read-through reviews of this workflow missed what one live run found.
These render the real YAML through the engine, as an agent would receive it,
and pin the defects that run exposed in the prose no unit test otherwise
reaches.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # nosec B404 - runs git/bash against a temp repo
import tempfile
import unittest
from pathlib import Path

from workflow.compiler import compile_workflow
from workflow.dispatch import build_agent_prompt
from workflow.parser import parse_workflow

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / "workflows/code/review-fix-threads.yaml"


def _prompts(**params: str) -> dict[str, str]:
    defn = parse_workflow(str(_WORKFLOW))
    manifest = compile_workflow(defn, project_root=_ROOT,
                                trigger_params={"pr_number": "405", **params})
    with tempfile.TemporaryDirectory() as ws:
        return {name: build_agent_prompt(stage, defn.name, ws)
                for name, stage in manifest.resolved_stages.items()}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class TestPushVerification(unittest.TestCase):
    """gh pr view returned the old sha right after a push ls-remote showed had
    landed; a single comparison fails a push that worked."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["commit-and-push"])

    def test_remote_ref_is_checked_directly(self) -> None:
        self.assertIn('git ls-remote origin "refs/heads/$HEAD_BRANCH"', self.prompt)

    def test_head_branch_is_not_substituted_into_command_text(self) -> None:
        # head_branch must be loaded into a shell variable via a controlled
        # `jq` command substitution, never typed into shell source directly —
        # a git ref can contain "$(...)" or backticks. See PRRT_kwDOQr1kjM6lOUjx.
        self.assertIn(
            "HEAD_BRANCH=$(jq -er '.head_branch' ", self.prompt
        )
        self.assertNotIn("git push origin <head_branch", self.prompt)
        self.assertNotIn("git ls-remote origin refs/heads/<head_branch", self.prompt)

    def test_head_ref_oid_comparison_is_retried_and_bounded(self) -> None:
        self.assertIn("retry at most 4 more times", self.prompt)
        self.assertIn("2, 4, 8 and then 16 seconds", self.prompt)
        self.assertIn("Never loop until it matches", self.prompt)

    def test_failure_names_every_sha(self) -> None:
        self.assertIn("local HEAD, the ls-remote sha, and the last headRefOid", self.prompt)


def _five_a_commands(workspace: str) -> str:
    """Step 5a's shell lines exactly as the commit-and-push agent receives them."""
    defn = parse_workflow(str(_WORKFLOW))
    manifest = compile_workflow(defn, project_root=_ROOT, trigger_params={"pr_number": "405"})
    prompt = build_agent_prompt(manifest.resolved_stages["commit-and-push"], defn.name, workspace)
    section = prompt[prompt.index("5a, the remote ref"): prompt.index("The first field of the ls-remote line")]
    cmds = [ln.strip() for ln in section.splitlines()
            if ln.strip().startswith(("git ", "HEAD_BRANCH="))]
    return "\n".join(cmds)


@unittest.skipUnless(all(map(shutil.which, ("git", "jq", "bash"))), "needs git, jq and bash")
class TestPushVerificationRunsAsItsOwnCall(unittest.TestCase):
    """PR #406 round 7: Step 5a used $HEAD_BRANCH from Step 4, a separate
    Bash call where it no longer exists, so ls-remote queried "refs/heads/"
    and every push verification failed. Run 5a alone, as the agent would."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.ws, repo, origin = root / "ws", root / "repo", root / "origin.git"
        (self.ws / "outputs").mkdir(parents=True)
        self._git("init", "-q", "--bare", str(origin))
        self._git("init", "-q", "-b", "feat/x", str(repo))
        self._git("-C", str(repo), "commit", "-q", "--allow-empty", "-m", "i")
        self._git("-C", str(repo), "remote", "add", "origin", str(origin))
        self._git("-C", str(repo), "push", "-q", "origin", "feat/x")
        self.repo = repo
        self.head = self._git("-C", str(repo), "rev-parse", "HEAD").decode().strip()

    @staticmethod
    def _git(*args: str) -> bytes:
        argv = [str(shutil.which("git")), "-c", "user.name=t", "-c", "user.email=t@t", *args]
        return subprocess.run(argv, check=True, capture_output=True).stdout  # nosec B603 - fixed argv, temp repo

    def _run_5a(self, context: dict[str, object]) -> subprocess.CompletedProcess[str]:
        (self.ws / "outputs/pr-context.json").write_text(json.dumps(context))
        argv = [str(shutil.which("bash")), "-c", _five_a_commands(str(self.ws))]
        return subprocess.run(argv, cwd=self.repo, capture_output=True, text=True)  # nosec B603 - runs the workflow's own rendered lines in a temp repo

    def test_5a_finds_the_pushed_ref_without_step_4s_shell(self) -> None:
        out = self._run_5a({"head_branch": "feat/x"}).stdout
        self.assertIn(f"{self.head}\trefs/heads/feat/x", out)

    def test_5a_fails_loudly_when_head_branch_is_missing(self) -> None:
        res = self._run_5a({})
        self.assertIn("NO-HEAD-BRANCH", res.stdout)
        self.assertNotEqual(res.returncode, 0)


class TestShellStateDoesNotCrossCalls(unittest.TestCase):
    """Each multi-line shell block that sets a variable says it is one call."""

    def test_init_digest_is_guarded_and_single_call(self) -> None:
        prompt = _flat(_prompts()["init"])
        self.assertIn('[ -n "$DIGEST" ] || { echo "NO-DIGEST"; exit 3; }', prompt)
        self.assertIn("a DIGEST set in one call is empty in the next", prompt)

    def test_step_4_push_is_single_call(self) -> None:
        prompt = _flat(_prompts()["commit-and-push"])
        self.assertIn("a HEAD_BRANCH set in one call is empty in the next", prompt)


class TestUnlistedEditGate(unittest.TestCase):
    """Test files were never committed: the gate and its baseline must be wired."""

    def test_init_snapshots_before_any_fixer(self) -> None:
        self.assertIn("./bin/workflow snapshot-dirty", _prompts()["init"])

    def test_init_records_the_baseline_hash(self) -> None:
        """PR #406 review: the baseline sits in fixer-writable outputs/, so
        init must record its sha256 before any fixer runs."""
        prompt = _flat(_prompts()["init"])
        self.assertIn('"dirty_baseline_sha256" in pr-context.json', prompt)
        self.assertIn('shasum -a 256 "', prompt)

    def test_init_actually_writes_the_hash_into_pr_context(self) -> None:
        """PR #406 round 2: the old prose only computed and printed the
        digest via shasum -- it never wrote dirty_baseline_sha256 into
        pr-context.json, so _verify_baseline_provenance always failed
        closed on the missing field. init must load the digest and merge
        it into the file with jq, atomically (temp file + rename, not a
        direct `>` redirect racing jq's own read of that path)."""
        prompt = _flat(_prompts()["init"])
        self.assertIn("dirty_baseline_sha256: $d", prompt)
        self.assertIn("pr-context.json.tmp", prompt)
        self.assertIn("mv ", prompt)
        self.assertIn("atomic", prompt)

    def test_commit_rejects_a_baseline_that_no_longer_matches(self) -> None:
        prompt = _flat(_prompts()["commit-and-push"])
        self.assertIn("dirty_baseline_sha256", prompt)
        self.assertIn("fail closed", prompt)

    def test_commit_runs_check_unlisted_before_staging(self) -> None:
        # check-unlisted now runs twice: once unconditionally in Step 1
        # (before the no-files early return; see the test below), and again
        # in Step 3b immediately before staging. check-paths (Step 3a) must
        # still precede that second, pre-staging run.
        prompt = _prompts()["commit-and-push"]
        staging_gate = prompt.rindex("./bin/workflow check-unlisted")
        self.assertLess(staging_gate, prompt.index("git add <file1>"))
        self.assertLess(prompt.index("./bin/workflow check-paths"), staging_gate)

    def test_commit_runs_check_unlisted_before_the_no_files_early_return(self) -> None:
        """PR #406 round 2: Step 1 used to return {"committed": false} on an
        empty files_changed before Step 3b's check-unlisted gate ever ran,
        so a fixer that edited a file but under-reported an empty
        files_changed list left the edit behind undetected. The gate must
        now run before that early-return decision, not only later in Step
        3b."""
        prompt = _flat(_prompts()["commit-and-push"])
        early_return = prompt.index('"reason": "no files changed"')
        first_gate_mention = prompt.index("./bin/workflow check-unlisted")
        self.assertLess(first_gate_mention, early_return)
        self.assertIn("unconditionally", prompt)


class TestParamProse(unittest.TestCase):
    """A param embedded as if it were a variable name rendered as
    'excluded unless false is "true"'."""

    def test_include_resolved_reads_correctly_for_both_values(self) -> None:
        for value in ("true", "false"):
            with self.subTest(include_resolved=value):
                prompt = _flat(_prompts(include_resolved=value)["triage-threads"])
                self.assertIn(f'include_resolved = "{value}"', prompt)
                self.assertNotIn(f'unless {value} is "true"', prompt)

    def test_pr_number_is_not_used_as_a_sentence_subject(self) -> None:
        prompt = _flat(_prompts()["init"])
        self.assertNotIn("405 is REQUIRED", prompt)
        self.assertNotIn("every later 405 site", prompt)


class TestQltyInstruction(unittest.TestCase):
    """verify-fixes told agents qlty scans zero files in a worktree -- untrue
    since 2026-08-27 -- steering them off the only linter running bandit and
    radarlint, which CI enforces."""

    def test_verify_fixes_runs_qlty_twice_on_named_files(self) -> None:
        prompt = _flat(_prompts()["verify-fixes"])
        self.assertIn(
            "Run the complete pass over every path TWICE and take the union",
            prompt,
        )

    def test_no_workflow_or_agent_repeats_the_stale_claim(self) -> None:
        roots = [*(_ROOT / "workflows").rglob("*.yaml"), *(_ROOT / ".claude/agents").glob("*.md")]
        self.assertTrue(roots)
        for path in roots:
            with self.subTest(path=str(path.relative_to(_ROOT))):
                self.assertNotIn("scans zero files", _flat(path.read_text(encoding="utf-8")))


class TestQltyPathsAreValidated(unittest.TestCase):
    """commit-result.json's files_committed is an agent-authored echo, not a
    code-validated list -- PR #406 review thread PRRT_kwDOQr1kjM6lP6Wt.
    Expanding it straight into a shell command let a malformed or
    prompt-injected path run shell syntax or point qlty elsewhere, even
    though fix-results.json's files_changed already passed check-paths in
    commit-and-push. verify-fixes must source qlty's paths from that
    validated list instead, loaded argv-safely."""

    def test_qlty_no_longer_expands_files_committed_directly(self) -> None:
        prompt = _flat(_prompts()["verify-fixes"])
        self.assertNotIn(
            "~/.qlty/bin/qlty check <every path in commit-result.json's files_committed>",
            prompt,
        )

    def test_qlty_sources_the_pushed_commit_not_a_workspace_file(self) -> None:
        """PR #406 round 7 ("Previously missed"): fix-results.json stays in
        the writable workspace, so a list read from it could be rewritten
        after staging. The targets come from the pushed commit instead."""
        prompt = _flat(_prompts()["verify-fixes"])
        self.assertIn("git diff-tree --no-commit-id --name-only -r -z --no-renames --diff-filter=d", prompt)
        self.assertIn('[ "$HEAD_SHA" = "$REMOTE_SHA" ] || { echo "HEAD-NOT-PUSHED', prompt)
        self.assertNotIn("jq -e -r '.files_changed[]'", prompt)

    def test_qlty_loop_never_interpolates_a_path_into_shell_text(self) -> None:
        prompt = _flat(_prompts()["verify-fixes"])
        self.assertIn("while IFS= read -r -d '' p; do", prompt)
        self.assertIn('~/.qlty/bin/qlty check "$p" || qlty_status=1', prompt)
        self.assertIn('done < ', prompt)
        self.assertIn('validation/qlty-paths.z', prompt)


class TestQltyLoopAccumulatesStatus(unittest.TestCase):
    """Copilot review thread (unlinked, review-fix-threads.yaml:1254): without
    `set -e`, a `while ...; done` loop's exit status is only its LAST
    iteration's -- a finding in any file but the last was followed by a clean
    check and the loop read as passing. The prose also asked for two full
    passes but the snippet only ran one."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["verify-fixes"])

    def test_status_is_captured_per_path_not_left_to_the_last_iteration(self) -> None:
        # Fixed form: a running qlty_status variable is OR'd across every
        # path, so an early failure survives a later clean file.
        self.assertIn("qlty_status=0", self.prompt)
        self.assertIn('qlty check "$p" || qlty_status=1', self.prompt)
        self.assertIn(
            "the exit status of a `while ...; done` loop is only the status "
            "of its LAST iteration",
            self.prompt,
        )
        # Broken form: a bare loop with no per-iteration status capture,
        # where the loop's own exit code is all that gets checked.
        self.assertNotIn(
            'while IFS= read -r p; do ~/.qlty/bin/qlty check "$p"; done',
            self.prompt,
        )

    def test_the_complete_pass_runs_twice_over_every_path(self) -> None:
        # The whole loop (all paths) runs twice inside one status scope.
        self.assertIn(
            "Run the complete pass over every path TWICE and take the union",
            self.prompt,
        )
        self.assertIn("for pass in 1 2; do", self.prompt)

    def test_status_is_not_reset_between_passes(self) -> None:
        """PR #406 round 5: resetting qlty_status before pass two erased a
        pass-one failure whenever pass two came back clean."""
        self.assertEqual(self.prompt.count("qlty_status=0"), 1)
        self.assertLess(self.prompt.index("qlty_status=0"), self.prompt.index("for pass in 1 2; do"))
        self.assertNotIn("a fresh `qlty_status=0` reset first", self.prompt)
        self.assertIn('echo "QLTY_STATUS=$qlty_status"', self.prompt)

    def test_lint_fail_is_set_from_either_pass_or_a_nonzero_status(self) -> None:
        self.assertIn(
            'finding in either qlty pass, a non-zero QLTY_STATUS, a failed path '
            'list or a commit that changed nothing, or a non-zero `make lint`, sets "lint": "fail"',
            self.prompt,
        )


class TestQltyPathListMustBeNonEmpty(unittest.TestCase):
    """PR #406 round 5: a failed source left an empty path list, the loop
    checked nothing, and exited 0 -- a green verification of zero files."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["verify-fixes"])

    def test_path_count_is_checked(self) -> None:
        self.assertIn("echo \"PATHS=$(tr -cd '\\0' <", self.prompt)

    def test_empty_or_failed_list_is_a_lint_failure_not_a_pass(self) -> None:
        self.assertIn("or DIFFTREE-FAILED, or CHANGED=0: set \"lint\": \"fail\"", self.prompt)
        self.assertIn("do not run qlty", self.prompt)

    def test_deletion_only_commit_skips_qlty_without_failing(self) -> None:
        """PR #406 round 12: --diff-filter=d leaves a deletion-only commit
        with PATHS=0, which used to fail lint and abort the run."""
        self.assertIn("PATHS=0 with CHANGED above 0: the commit only deleted files", self.prompt)
        self.assertIn("Skip the qlty loop", self.prompt)


class TestCoverageAuditReadsOnlyValidatedTests(unittest.TestCase):
    """PR #406 round 13: verify-fixes read every tests_added id from each
    verbatim result, so a fixer-written ../../.envrc::x became a file read."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["verify-fixes"])

    def test_tests_come_from_the_validated_map(self) -> None:
        self.assertIn('Take the tests to read ONLY from fix-results.json\'s top-level "tests_by_result"', self.prompt)
        self.assertIn('"rejected_tests_added"; never open those', self.prompt)
        self.assertNotIn('For every result with action "fixed" that lists tests_added', self.prompt)


def _qlty_paths_block(workspace: str) -> str:
    """verify-fixes' path-derivation lines exactly as the agent receives them."""
    defn = parse_workflow(str(_WORKFLOW))
    manifest = compile_workflow(defn, project_root=_ROOT, trigger_params={"pr_number": "405"})
    prompt = build_agent_prompt(manifest.resolved_stages["verify-fixes"], defn.name, workspace)
    section = prompt[prompt.index("HEAD_SHA=$(git rev-parse HEAD)"): prompt.index("`--diff-filter=d` leaves out")]
    # Only command lines; the block ends at echo "CHANGED=...".
    return "\n".join(ln.strip() for ln in section.splitlines() if ln.strip())


@unittest.skipUnless(all(map(shutil.which, ("git", "jq", "bash"))), "needs git, jq and bash")
class TestQltyPathsComeFromThePushedCommit(unittest.TestCase):
    """Run the rendered block: it must list the pushed commit's files, and
    refuse when HEAD is not what origin has."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        # The workspace name carries a space: every {workspace} path in the
        # block must be quoted (PR #406 round 12).
        self.ws, self.repo, origin = root / "work space", root / "repo", root / "origin.git"
        (self.ws / "outputs").mkdir(parents=True)
        (self.ws / "validation").mkdir()
        (self.ws / "outputs/pr-context.json").write_text(json.dumps({"head_branch": "feat/x"}))
        # A decoy list: nothing the block does may read it.
        (self.ws / "outputs/fix-results.json").write_text(json.dumps({"files_changed": ["decoy.py"]}))
        git = TestPushVerificationRunsAsItsOwnCall._git
        git("init", "-q", "--bare", str(origin))
        git("init", "-q", "-b", "feat/x", str(self.repo))
        (self.repo / "gone.py").write_text("x = 1\n")
        git("-C", str(self.repo), "add", "gone.py")
        git("-C", str(self.repo), "commit", "-q", "-m", "base")
        (self.repo / "fixed file.py").write_text("y = 1\n")
        git("-C", str(self.repo), "rm", "-q", "gone.py")
        git("-C", str(self.repo), "add", "fixed file.py")
        git("-C", str(self.repo), "commit", "-q", "-m", "fix")
        git("-C", str(self.repo), "remote", "add", "origin", str(origin))
        git("-C", str(self.repo), "push", "-q", "origin", "feat/x")
        self.git = git

    def _run(self) -> subprocess.CompletedProcess[str]:
        argv = [str(shutil.which("bash")), "-c", _qlty_paths_block(str(self.ws))]
        return subprocess.run(argv, cwd=self.repo, capture_output=True, text=True)  # nosec B603 - runs the workflow's own rendered block in a temp repo

    def test_lists_the_pushed_commits_files_nul_delimited(self) -> None:
        res = self._run()
        self.assertIn("PATHS=1", res.stdout)
        self.assertIn("CHANGED=2", res.stdout)
        listed = (self.ws / "validation/qlty-paths.z").read_bytes().split(b"\0")
        self.assertEqual([p for p in listed if p], [b"fixed file.py"])

    def test_deletion_only_commit_reports_paths_zero_but_changed(self) -> None:
        self.git("-C", str(self.repo), "rm", "-q", "fixed file.py")
        self.git("-C", str(self.repo), "commit", "-q", "-m", "delete only")
        self.git("-C", str(self.repo), "push", "-q", "origin", "feat/x")
        res = self._run()
        self.assertIn("PATHS=0", res.stdout)
        self.assertIn("CHANGED=1", res.stdout)

    def test_unpushed_head_is_refused(self) -> None:
        self.git("-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "local only")
        res = self._run()
        self.assertIn("HEAD-NOT-PUSHED", res.stdout)
        self.assertNotEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
