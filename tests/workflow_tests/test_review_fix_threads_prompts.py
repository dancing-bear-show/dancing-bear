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
        self.assertIn('Take the tests to read ONLY from fix-results-merged.json\'s top-level "tests_by_result"', self.prompt)
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


class TestUnlinkedFindingTriageAndDispatchRules(unittest.TestCase):
    """PR #443 review threads PRRT_kwDOQr1kjM6nUv2O / PRRT_kwDOQr1kjM6nUv2h:
    no rendered-prompt regression checks pinned the unlinked-finding rules —
    stale exclusion, independent repeat_of judgement (including the
    previously_missed-without-repeat_of case a drifted-line merge produces),
    and dispatch/report reading confirmed ids only."""

    def setUp(self) -> None:
        self.triage_prompt = _flat(_prompts()["triage-threads"])
        self.dispatch_prompt = _flat(_prompts()["fix-dispatch"])
        self.report_prompt = _flat(_prompts()["report"])

    def test_stale_current_false_findings_are_not_dispatched(self) -> None:
        # (a) current: false -> stale_unlinked reporting, never dispatch.
        self.assertIn('"current": false', self.triage_prompt)
        self.assertIn("stale_unlinked", self.triage_prompt)
        self.assertIn("Do NOT dispatch it", self.triage_prompt)

    def test_repeat_of_is_judged_per_prior_id_by_title_and_body(self) -> None:
        # (b) prior_same_path alone grants nothing; each id is compared by
        # its own title/body before it can enter repeat_of.
        self.assertIn(
            "compare ITS \"title\" and \"body\" against the current finding's "
            "own title and body. Judge each prior id independently",
            self.triage_prompt,
        )
        self.assertIn(
            "only shows that an earlier finding cited the SAME FILE",
            self.triage_prompt,
        )
        # Positive rule: a same-concern prior IS recorded.
        self.assertIn(
            "record its id in this triage entry's \"repeat_of\" list",
            self.triage_prompt,
        )
        self.assertIn("do NOT add it to \"repeat_of\"", self.triage_prompt)

    def test_own_previously_missed_keeps_weight_with_empty_repeat_of(self) -> None:
        # (c) the Uv2O fix: _merge_drifted folds an earlier same-title raise
        # into the current entry (previously_missed stays true) without
        # populating repeat_of. That must still carry full weight.
        self.assertIn(
            "\"previously_missed\" can be true here with \"repeat_of\" left "
            "empty",
            self.triage_prompt,
        )
        self.assertIn(
            "grant this finding the same \"previously missed\" weight "
            "regardless of what \"repeat_of\" ends up containing",
            self.triage_prompt,
        )

    def test_earlier_raise_embedding_reads_repeat_of_not_prior_same_path(self) -> None:
        # (d) fix-dispatch must source the "Earlier raise" context from the
        # triage-judged repeat_of list, not the raw prior_same_path list.
        self.assertIn(
            'When triage.json\'s "repeat_of" for this entry is non-empty, add '
            'one more synthetic comment per listed id',
            self.dispatch_prompt,
        )
        self.assertIn(
            'Read "repeat_of", never "prior_same_path", here', self.dispatch_prompt
        )
        self.assertIn('prefixed "Earlier raise (<path>:<line>):"', self.dispatch_prompt)
        # Negative: the dispatch prose must never instruct sourcing the
        # embedded comment directly from prior_same_path.
        self.assertNotIn(
            "add one more synthetic comment per listed id in "
            '"prior_same_path"',
            self.dispatch_prompt,
        )

    def test_superseded_by_requires_repeat_of_not_shared_path_alone(self) -> None:
        # (e) report: "superseded by" only fires from a triage-confirmed
        # repeat_of match, and a rejected path is shown labelled, not
        # "null:<line>".
        self.assertIn(
            'Say "superseded by <id>" ONLY when', self.report_prompt
        )
        self.assertIn(
            'triage.json records that current finding\'s "repeat_of" as '
            'containing this stale id', self.report_prompt
        )
        self.assertIn("not merely a current finding sharing the same path", self.report_prompt)
        self.assertIn("never \"null:<line>\"", self.report_prompt)

    def test_both_path_and_path_rejected_null_falls_back_to_id(self) -> None:
        # (f) a bare "unlinked:<digest>" finding (no path line was present to
        # parse or reject) has neither "path" nor "path_rejected" to show.
        # triage-threads must classify it "context" instead of dispatching a
        # null path, and report must label its bare id rather than
        # assembling "null:<line>".
        self.assertIn(
            'A finding can also have BOTH "path" and "path_rejected" null',
            self.triage_prompt,
        )
        self.assertIn(
            "this finding has nowhere to be dispatched", self.triage_prompt
        )
        self.assertIn(
            'When BOTH "path" and "path_rejected" are null', self.report_prompt
        )
        self.assertIn('labelled "(path unavailable)"', self.report_prompt)

    def test_partial_parse_stale_guidance_in_triage_and_report(self) -> None:
        # (g) when review-overview.json status is "partial", current: false
        # only means the finding was not parsed — it may still be live.
        # Triage must check the raw body before calling it stale; report must
        # label each such entry "staleness indeterminate (partial parse)".
        self.assertIn(
            "partial",
            self.triage_prompt,
        )
        self.assertIn(
            "staleness indeterminate: partial parse",
            self.triage_prompt,
        )
        self.assertIn(
            "staleness indeterminate (partial parse)",
            self.report_prompt,
        )

    def test_partial_parse_raw_body_selected_by_review_id_not_timestamp(
        self,
    ) -> None:
        # PR #453 PRRT_kwDOQr1kjM6njurS: "review_bodies" holds every non-empty
        # review, bot or human, so selecting by latest "submitted_at" can pick
        # a later human review's text over the newest Copilot overview. Pin
        # the actual selection mechanism — by "review_id" matching
        # review-overview.json "newest"."review_id" — not just the output
        # label.
        self.assertIn(
            'Select the "review_bodies" entry whose "review_id" equals '
            'review-overview.json "newest"."review_id"',
            self.triage_prompt,
        )
        self.assertIn(
            "never by timestamp", self.triage_prompt
        )
        self.assertIn(
            "treat the finding as indeterminate", self.triage_prompt
        )
        # Negative: the prose must no longer instruct selecting by latest
        # submitted_at for this fallback.
        self.assertNotIn(
            'look in threads.json "review_bodies" for the entry with the '
            'latest "submitted_at" timestamp',
            self.triage_prompt,
        )

    def test_partial_parse_title_match_triages_like_current_and_records_id(
        self,
    ) -> None:
        # The title-match branch must triage the finding like a current one
        # AND give it a triage entry keyed by its original id, since the
        # report's re-confirmed/indeterminate split depends on that entry
        # existing.
        self.assertIn(
            'If the title is present there, triage it like a current '
            "finding", self.triage_prompt,
        )
        self.assertIn(
            'give it the usual triage fields including this finding\'s '
            'original "id" from review-overview.json so the report can join '
            "on it", self.triage_prompt,
        )

    def test_report_splits_reconfirmed_from_indeterminate_stale_findings(
        self,
    ) -> None:
        # The report must not apply a blanket "indeterminate" label to every
        # stale id under a partial parse — a stale id triage re-confirmed
        # (its own triage.json entry) must report its real fix-results.json
        # outcome; only a stale id with no triage entry is indeterminate.
        self.assertIn(
            'This id has its OWN entry in triage.json', self.report_prompt
        )
        self.assertIn(
            "Report its actual outcome from fix-results-merged.json", self.report_prompt
        )
        self.assertIn(
            "never \"indeterminate\"", self.report_prompt
        )
        self.assertIn(
            "This id has NO entry in triage.json", self.report_prompt
        )
        self.assertIn(
            "No live match was established, so label it", self.report_prompt
        )


class TestSweepFixRegressions(unittest.TestCase):
    """Regression sweep stage is present, correctly ordered, and wired properly.

    The nine regression patterns from the 2026-10-06 session (PRs #437/#448/
    #452/#454/#455/#456) are all covered by concerns/fix-regressions.md, which
    the stage selects via --task-type review-fix.
    """

    def setUp(self) -> None:
        self.prompts = _prompts()
        self.stages = list(self.prompts.keys())

    # --- Stage existence and ordering ---

    def test_all_three_sweep_stages_exist(self) -> None:
        for name in ("sweep-fix-regressions", "refix-regressions", "resweep-regressions"):
            with self.subTest(stage=name):
                self.assertIn(name, self.stages)

    def test_sweep_pipeline_ordering(self) -> None:
        """fix-aggregate → sweep → refix → resweep → commit-and-push."""
        agg = self.stages.index("fix-aggregate")
        sweep = self.stages.index("sweep-fix-regressions")
        refix = self.stages.index("refix-regressions")
        resweep = self.stages.index("resweep-regressions")
        commit = self.stages.index("commit-and-push")
        self.assertLess(agg, sweep)
        self.assertLess(sweep, refix)
        self.assertLess(refix, resweep)
        self.assertLess(resweep, commit)

    # --- sweep-fix-regressions: reporter, exits 0 ---

    def test_sweep_prompt_calls_select_concerns_with_review_fix_task_type(self) -> None:
        prompt = _flat(self.prompts["sweep-fix-regressions"])
        self.assertIn("--task-type review-fix", prompt)

    def test_sweep_prompt_uses_paths_file_not_inline_paths(self) -> None:
        """Paths passed in shell text split on spaces (CLAUDE.md).
        The stage must use --paths-file."""
        prompt = _flat(self.prompts["sweep-fix-regressions"])
        self.assertIn("--paths-file", prompt)

    def test_sweep_is_reporter_exits_zero(self) -> None:
        """sweep-fix-regressions is a reporter — it exits 0 even with blocking
        findings. The gate is resweep-regressions."""
        prompt = _flat(self.prompts["sweep-fix-regressions"])
        self.assertIn("Exit 0", prompt)
        self.assertIn("reporter", prompt)

    def test_sweep_prompt_names_unbacked_verification_check(self) -> None:
        """Regression 6: verify test_output_tail contains 'Ran N tests'."""
        prompt = _flat(self.prompts["sweep-fix-regressions"])
        self.assertIn("test_output_tail", prompt)
        self.assertIn("Ran N tests", prompt)

    def test_sweep_prompt_names_gate_suppressions_check(self) -> None:
        """Regression 7: type: ignore is forbidden by CLAUDE.md."""
        prompt = _flat(self.prompts["sweep-fix-regressions"])
        self.assertIn("# type: ignore", prompt)

    def test_sweep_prompt_names_rename_schema_drift_check(self) -> None:
        """Regression 8: renamed field must be updated everywhere."""
        prompt = _flat(self.prompts["sweep-fix-regressions"])
        self.assertIn("rename-schema-drift", prompt)

    def test_sweep_prompt_is_read_only_no_edit(self) -> None:
        """The sweep stage must not edit source files."""
        prompt = _flat(self.prompts["sweep-fix-regressions"])
        self.assertIn("MUST NOT edit", prompt)

    def test_sweep_prompt_writes_findings_json(self) -> None:
        prompt = _flat(self.prompts["sweep-fix-regressions"])
        self.assertIn("sweep-findings.json", prompt)

    # --- refix-regressions: thread-fixer, edits source ---

    def test_refix_is_noop_when_blocking_zero(self) -> None:
        """refix writes empty results and exits 0 when no blocking findings."""
        prompt = _flat(self.prompts["refix-regressions"])
        self.assertIn("blocking", prompt)
        self.assertIn("0", prompt)
        # Must write refix-results.json even when nothing to do.
        self.assertIn("refix-results.json", prompt)

    def test_refix_passes_blocking_findings_to_fixer(self) -> None:
        prompt = _flat(self.prompts["refix-regressions"])
        self.assertIn("blocking_findings", prompt)

    # --- resweep-regressions: reviewer, the gate ---

    def test_resweep_exits_nonzero_when_findings_persist(self) -> None:
        """resweep is the gate — it must exit non-zero if any finding persists."""
        prompt = _flat(self.prompts["resweep-regressions"])
        self.assertIn("exit non-zero", prompt)
        self.assertIn("still_blocking", prompt)

    def test_resweep_is_read_only_no_edit(self) -> None:
        """resweep must not edit source files."""
        prompt = _flat(self.prompts["resweep-regressions"])
        self.assertIn("MUST NOT edit", prompt)

    def test_resweep_reruns_probe_from_sweep_findings(self) -> None:
        """resweep re-runs the probe commands sweep recorded, not a new scan."""
        prompt = _flat(self.prompts["resweep-regressions"])
        self.assertIn("probe", prompt)
        self.assertIn("sweep-findings.json", prompt)

    def test_resweep_checks_gate_suppressions_in_refix_diff(self) -> None:
        """gate-suppressions in refix output must also be caught by resweep."""
        prompt = _flat(self.prompts["resweep-regressions"])
        self.assertIn("gate-suppression", prompt)

    # --- commit-and-push sees refix files ---

    def test_commit_reads_refix_results(self) -> None:
        """commit-and-push must read refix-results.json and include its
        files_changed in the files to stage."""
        prompt = _flat(self.prompts["commit-and-push"])
        self.assertIn("refix-results.json", prompt)

    # --- selection.yaml wiring ---

    def test_selection_yaml_maps_review_fix_task_type_to_fix_regressions_guide(
        self,
    ) -> None:
        """Run the real select-concerns binary; do not string-match the YAML."""
        import subprocess
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("src/foo.py\n")
            paths_file = f.name

        result = subprocess.run(  # nosec B603 - fixed argv invoking the repo's own CLI
            [
                "./bin/workflow",
                "select-concerns",
                "--paths-file",
                paths_file,
                "--task-type",
                "review-fix",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            cwd=str(_ROOT),
        )
        self.assertEqual(
            result.returncode,
            0,
            f"select-concerns failed: {result.stderr}",
        )
        data = json.loads(result.stdout)
        # Output is {"guides": [...]} — the guides key holds the list.
        if isinstance(data, dict):
            raw = data.get("guides") or data.get("selected") or []
            guide_names: list[object] = raw if isinstance(raw, list) else []
        else:
            guide_names = list(data) if data else []
        self.assertIn(
            "fix-regressions.md",
            guide_names,
            f"fix-regressions.md not in selected guides for review-fix: {guide_names}",
        )

    # --- merge-fix-results CLI: execution and schema ---

    def test_merge_fix_results_command_executes(self) -> None:
        """merge-fix-results runs without error and produces a merged JSON file."""
        with tempfile.TemporaryDirectory() as td:
            fr_path = Path(td) / "fix-results.json"
            rr_path = Path(td) / "refix-results.json"
            out_path = Path(td) / "fix-results-merged.json"
            fr_path.write_text(json.dumps({
                "files_changed": ["src/core/foo.py"],
                "results": [{"id": "r1", "action": "fixed"}],
                "missing_results": [],
                "failed_tests": [],
                "key_mismatches": [],
                "out_of_scope_requests": [],
                "out_of_scope_paths": [],
                "rejected_tests_added": [],
                "tests_by_result": {"r1": ["tests/core_tests/test_foo.py"]},
                "by_action": {"fixed": 1, "rejected": 0},
                "total_expected": 1,
                "total_results": 1,
            }), encoding="utf-8")
            rr_path.write_text(json.dumps({
                "files_changed": ["src/core/bar.py"],
                "results": [{"id": "r2", "action": "fixed"}],
                "missing_results": [],
                "failed_tests": [],
                "key_mismatches": [],
                "out_of_scope_requests": [],
                "out_of_scope_paths": [],
                "rejected_tests_added": [],
                "tests_by_result": {"r2": ["tests/core_tests/test_bar.py"]},
                "by_action": {"fixed": 1, "rejected": 0},
                "total_expected": 1,
                "total_results": 1,
            }), encoding="utf-8")

            result = subprocess.run(  # nosec B603 - fixed argv invoking the repo's own CLI
                [
                    "./bin/workflow",
                    "merge-fix-results",
                    str(fr_path),
                    str(rr_path),
                    str(out_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(_ROOT),
            )
            self.assertEqual(
                result.returncode,
                0,
                f"merge-fix-results failed: {result.stderr}",
            )
            self.assertTrue(out_path.is_file(), "merged file was not written")
            merged = json.loads(out_path.read_text(encoding="utf-8"))
            # files_changed must be the union of both inputs
            self.assertIn("src/core/foo.py", merged["files_changed"])
            self.assertIn("src/core/bar.py", merged["files_changed"])
            # tests_by_result must carry both result IDs
            self.assertIn("r1", merged["tests_by_result"])
            self.assertIn("r2", merged["tests_by_result"])
            # by_action must be summed: fixed=2
            self.assertEqual(merged["by_action"]["fixed"], 2)

    def test_merge_fix_results_carries_all_fields(self) -> None:
        """Merged file must carry the fields downstream readers need."""
        prompt_commit = _flat(self.prompts["commit-and-push"])
        # The merge command must appear in commit-and-push
        self.assertIn("merge-fix-results", prompt_commit)
        # The merge must not use python3 -c (which can cause IndentationError)
        self.assertNotIn('python3 -I -S -c "', prompt_commit)
        self.assertNotIn("python3 -c \"", prompt_commit)

    def test_downstream_readers_reference_merged_file(self) -> None:
        """verify-fixes, check-prose, plan-resolution, and report must read
        fix-results-merged.json, not fix-results.json, for fields that
        refix-regressions may have contributed to."""
        for stage_name in ("verify-fixes", "check-prose", "plan-resolution", "report"):
            with self.subTest(stage=stage_name):
                prompt = _flat(self.prompts[stage_name])
                self.assertIn(
                    "fix-results-merged.json",
                    prompt,
                    f"{stage_name} does not reference fix-results-merged.json",
                )


if __name__ == "__main__":
    unittest.main()
