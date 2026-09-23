"""Rendered-prompt checks for review-and-fix, from PR #406 review rounds 3-4.

Renders the real YAML through the engine, as an agent would receive it, and
pins the merge-fix-worktrees defects review rounds found in the prose: an
unnormalized ref comparison that silently falls through to an untrusted
fallback, a worktree path pasted into shell source even after being
assigned to a variable, and a `git status` check that only looked at stdout
and ignored a non-zero exit code.
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
_WORKFLOW = _ROOT / "workflows/code/review-and-fix.yaml"


def _prompts(**params: str) -> dict[str, str]:
    defn = parse_workflow(str(_WORKFLOW))
    manifest = compile_workflow(defn, project_root=_ROOT,
                                trigger_params={"pr_number": "406", **params})
    with tempfile.TemporaryDirectory() as ws:
        return {name: build_agent_prompt(stage, defn.name, ws)
                for name, stage in manifest.resolved_stages.items()}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class TestMergeFixWorktreesRefComparison(unittest.TestCase):
    """`git worktree list --porcelain` reports the branch as
    refs/heads/<name>, while the fixer records the short name from
    `git rev-parse --abbrev-ref HEAD`. Comparing the raw field to <branch>
    therefore misses the normal worktree and falls through to the untrusted
    self-reported uncommitted_paths fallback."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["merge-fix-worktrees"])

    def test_comparison_is_against_the_full_ref(self) -> None:
        self.assertIn('"branch" equals "refs/heads/<branch>"', self.prompt)

    def test_bare_branch_comparison_is_called_out_as_wrong(self) -> None:
        self.assertIn("not a bare <branch> comparison", self.prompt)
        self.assertIn("turns every fixer into a failed check", self.prompt)

    def test_fallback_lookup_also_uses_the_full_ref(self) -> None:
        self.assertIn('no worktree entry matches "refs/heads/<branch>"', self.prompt)


class TestMergeFixWorktreesPathQuoting(unittest.TestCase):
    """A prior round replaced `git -C <worktree_path>` with
    `WORKTREE_PATH=<worktree_path>` then `git -C "$WORKTREE_PATH"` — but the
    assignment line itself still pasted the raw, untrusted path into shell
    source, so spaces or shell metacharacters in the path could still split
    or inject into the command. The path must reach the shell only as the
    output of a command (parsing the `git worktree list --porcelain -z`
    dump), never typed into command source as `<worktree_path>` text."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["merge-fix-worktrees"])

    def test_worktree_path_is_captured_from_a_command_substitution(self) -> None:
        self.assertIn('WORKTREE_PATH="$(REF="refs/heads/$BRANCH" jq -Rrs', self.prompt)

    def test_git_dash_c_uses_the_quoted_variable(self) -> None:
        self.assertIn('git -C "$WORKTREE_PATH" status --porcelain', self.prompt)

    def test_unquoted_worktree_path_no_longer_appears(self) -> None:
        self.assertNotIn("git -C <worktree_path>", self.prompt)

    def test_raw_placeholder_assignment_is_not_run_as_a_command(self) -> None:
        """The previously-flagged unsafe form: `Bash tool:
        WORKTREE_PATH=<worktree_path>` pasted the raw placeholder directly
        into an assignment's shell text. It may still be named in the
        cautionary prose explaining what not to do, but must not appear as
        a command to run."""
        self.assertNotIn("Bash tool: WORKTREE_PATH=<worktree_path>", self.prompt)

    def test_porcelain_listing_is_parsed_from_a_file_not_inline_text(self) -> None:
        self.assertIn("git worktree list --porcelain -z >", self.prompt)
        self.assertIn("worktree-list.txt", self.prompt)

    def test_branch_is_read_by_jq_and_passed_through_the_environment(self) -> None:
        """The branch comes from the fixer's own result file, so it is agent
        text too; typed into `awk -v ref="refs/heads/<branch>"` it would be
        pasted into shell source exactly like the path was."""
        self.assertIn("BRANCH=\"$(jq -er '.branch' ", self.prompt)
        self.assertIn('REF="refs/heads/$BRANCH" jq -Rrs', self.prompt)
        self.assertIn('"branch " + env.REF', self.prompt)
        self.assertNotIn('-v ref="refs/heads/<branch>"', self.prompt)
        self.assertNotIn('ENVIRON["REF"]', self.prompt)


class TestMergeFixWorktreesStatusExitCode(unittest.TestCase):
    """The gate only treated non-empty `git status` stdout as a failure. A
    removed or unreadable worktree can make `git status` exit non-zero with
    no stdout, and that silently read as clean."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["merge-fix-worktrees"])

    def test_exit_code_is_captured(self) -> None:
        self.assertIn('echo "EXIT=$?"', self.prompt)

    def test_nonzero_exit_is_called_out_as_failure(self) -> None:
        self.assertIn('Pass only when the block printed no paths and ended "EXIT=0"', self.prompt)
        self.assertIn("A silent non-zero exit must never read as clean", self.prompt)

    def test_nonzero_exit_detail_format_is_specified(self) -> None:
        self.assertIn("git status exited non-zero: <code>", self.prompt)


class TestMergeFixWorktreesFailsClosed(unittest.TestCase):
    """PR #406 rounds 5-6: an empty WORKTREE_PATH must not reach `git -C ""`,
    and an unresolvable worktree must fail rather than fall back to the
    fixer's own uncommitted_paths report."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["merge-fix-worktrees"])

    def test_empty_path_is_checked_before_git_status(self) -> None:
        guard = self.prompt.index('[ -n "$WORKTREE_PATH" ] || { echo "NO-MATCH"; exit 4; }')
        status = self.prompt.index('git -C "$WORKTREE_PATH" status')
        self.assertLess(guard, status)

    def test_no_match_fails_closed_without_the_self_reported_fallback(self) -> None:
        self.assertIn('detail "fixer worktree not found; cannot verify". Fail closed.', self.prompt)
        self.assertIn('Do NOT fall back to the fixer\'s "uncommitted_paths"', self.prompt)
        self.assertNotIn("fall back to the fixer's \"uncommitted_paths\" field only as a last resort",
                         self.prompt)

    def test_the_check_runs_as_one_bash_call(self) -> None:
        self.assertIn("shell variables do not survive between calls", self.prompt)


class TestEmptyBranchStillChecksTheWorktree(unittest.TestCase):
    """PR #406 round 7: an empty branch was accepted as a no-op before the
    worktree check ran, so a fixer that left its edits uncommitted and
    reported `fixed: []` lost them silently."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["merge-fix-worktrees"])

    def test_check_runs_for_every_fixer_including_an_empty_branch(self) -> None:
        self.assertIn("Run that check for EVERY fixer, whatever this step found — an empty branch included.",
                      self.prompt)
        self.assertIn("When the branch is empty AND the check is clean, record a no-op", self.prompt)
        self.assertNotIn("Record it as a no-op, skip the merge, and CONTINUE.", self.prompt)

    def test_no_op_requires_a_clean_worktree(self) -> None:
        self.assertIn('an empty branch with a dirty or unverifiable worktree goes in "uncommitted"', self.prompt)


class TestMergeFixWorktreesBranchNeverTyped(unittest.TestCase):
    """PR #406 round 6: the fixer-written branch was still pasted raw into
    `git merge-base`, `git log` and `git merge`."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["merge-fix-worktrees"])

    def test_no_git_command_takes_the_raw_placeholder(self) -> None:
        for raw in ("--is-ancestor <PRE_FIX_SHA> <branch>", "<PRE_FIX_SHA>..<branch>",
                    "git merge --no-ff <branch>"):
            with self.subTest(raw=raw):
                self.assertNotIn(raw, self.prompt)

    def test_every_consumer_validates_and_quotes_the_full_ref(self) -> None:
        for cmd in ('git merge-base --is-ancestor <PRE_FIX_SHA> "refs/heads/$BRANCH"',
                    'git log --oneline <PRE_FIX_SHA>.."refs/heads/$BRANCH"',
                    'git merge --no-ff "refs/heads/$BRANCH"'):
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, self.prompt)
        self.assertEqual(self.prompt.count('git check-ref-format --branch "$BRANCH"'), 4)


def _worktree_check_block(workspace: str) -> str:
    """The worktree-check Bash block exactly as the agent receives it."""
    defn = parse_workflow(str(_WORKFLOW))
    manifest = compile_workflow(defn, project_root=_ROOT, trigger_params={"pr_number": "406"})
    prompt = build_agent_prompt(manifest.resolved_stages["merge-fix-worktrees"], defn.name, workspace)
    chunk = next(c for c in prompt.split("Bash tool: ") if 'WORKTREE_PATH="$(' in c)
    block = chunk[: chunk.index('echo "EXIT=$?"') + len('echo "EXIT=$?"')]
    return "\n".join(line.strip() for line in block.splitlines()).replace(
        "<fixer result file>", "r.json")


@unittest.skipUnless(all(map(shutil.which, ("git", "jq", "bash"))), "needs git, jq and bash")
class TestWorktreeCheckBlockExecutes(unittest.TestCase):
    """Run the rendered block against a real worktree. String assertions
    passed on an `awk -v RS='\\0'` lookup that macOS awk cannot execute: it
    stops at the first NUL, so no fixer worktree ever matched."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.ws, self.repo = root / "ws", root / "repo"
        (self.ws / "outputs/fix").mkdir(parents=True)
        (self.ws / "validation").mkdir()
        self.wt = root / "wt dir"
        self._git("init", "-q", str(self.repo))
        self._git("-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "i")
        self._git("-C", str(self.repo), "worktree", "add", "-q", "-b", "worktree-agent-abc", str(self.wt))
        listing = self._git("-C", str(self.repo), "worktree", "list", "--porcelain", "-z")
        (self.ws / "validation/worktree-list.txt").write_bytes(listing)
        self.block = _worktree_check_block(str(self.ws))

    @staticmethod
    def _git(*args: str) -> bytes:
        argv = [str(shutil.which("git")), "-c", "user.name=t", "-c", "user.email=t@t", *args]
        return subprocess.run(argv, check=True, capture_output=True).stdout  # nosec B603 - fixed argv, temp repo

    def _run(self, branch: object) -> subprocess.CompletedProcess[str]:
        (self.ws / "outputs/fix/r.json").write_text(json.dumps({"branch": branch}))
        argv = [str(shutil.which("bash")), "-c", self.block]
        return subprocess.run(argv, cwd=self.repo, capture_output=True, text=True)  # nosec B603 - runs the workflow's own rendered block in a temp repo

    def test_matching_worktree_reports_its_uncommitted_file(self) -> None:
        (self.wt / "dirty.txt").write_text("x")
        out = self._run("worktree-agent-abc").stdout
        self.assertIn("?? dirty.txt", out)
        self.assertIn("EXIT=0", out)

    def test_clean_matching_worktree_passes(self) -> None:
        out = self._run("worktree-agent-abc").stdout
        self.assertEqual(out.strip(), "EXIT=0")

    def test_unknown_branch_fails_closed(self) -> None:
        res = self._run("worktree-agent-zzz")
        self.assertIn("NO-MATCH", res.stdout)
        self.assertNotEqual(res.returncode, 0)

    def test_shell_syntax_in_the_branch_is_rejected_not_run(self) -> None:
        res = self._run("a$(touch PWNED)")
        self.assertIn("BAD-BRANCH", res.stdout)
        self.assertFalse((self.repo / "PWNED").exists())

    def test_option_shaped_branch_is_rejected(self) -> None:
        self.assertIn("BAD-BRANCH", self._run("-foo").stdout)


if __name__ == "__main__":
    unittest.main()
