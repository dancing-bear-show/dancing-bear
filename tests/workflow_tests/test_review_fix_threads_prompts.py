"""Rendered-prompt checks for review-fix-threads, from its first live dry run.

Four read-through reviews of this workflow missed what one live run found.
These render the real YAML through the engine, as an agent would receive it,
and pin the defects that run exposed in the prose no unit test otherwise
reaches.
"""

from __future__ import annotations

import re
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
            "HEAD_BRANCH=$(jq -r '.head_branch' ", self.prompt
        )
        self.assertNotIn("git push origin <head_branch", self.prompt)
        self.assertNotIn("git ls-remote origin refs/heads/<head_branch", self.prompt)

    def test_head_ref_oid_comparison_is_retried_and_bounded(self) -> None:
        self.assertIn("retry at most 4 more times", self.prompt)
        self.assertIn("2, 4, 8 and then 16 seconds", self.prompt)
        self.assertIn("Never loop until it matches", self.prompt)

    def test_failure_names_every_sha(self) -> None:
        self.assertIn("local HEAD, the ls-remote sha, and the last headRefOid", self.prompt)


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

    def test_qlty_sources_the_check_paths_validated_list(self) -> None:
        prompt = _flat(_prompts()["verify-fixes"])
        self.assertIn("fix-results.json's files_changed", prompt)
        self.assertIn("check-paths", prompt)
        self.assertIn("jq -r '.files_changed[]'", prompt)
        self.assertIn("outputs/fix-results.json", prompt)

    def test_qlty_loop_never_interpolates_a_path_into_shell_text(self) -> None:
        prompt = _flat(_prompts()["verify-fixes"])
        self.assertIn('while IFS= read -r p; do', prompt)
        self.assertIn('~/.qlty/bin/qlty check "$p" || qlty_status=1', prompt)
        self.assertIn('done < ', prompt)
        self.assertIn('validation/qlty-paths.txt', prompt)


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
        # Fixed form: the whole loop (all paths) repeats a second time with a
        # fresh status reset, and findings/statuses from both runs are
        # unioned -- not one run over one path, or one run over all paths.
        self.assertIn(
            "Run the complete pass over every path TWICE and take the union",
            self.prompt,
        )
        self.assertIn("Run that same loop a second time", self.prompt)
        self.assertIn("a fresh `qlty_status=0` reset first", self.prompt)

    def test_lint_fail_is_set_from_either_pass_or_a_nonzero_status(self) -> None:
        self.assertIn(
            'finding in either qlty pass, either `qlty_status` non-zero, or a '
            'non-zero `make lint`, sets "lint": "fail"',
            self.prompt,
        )


if __name__ == "__main__":
    unittest.main()
