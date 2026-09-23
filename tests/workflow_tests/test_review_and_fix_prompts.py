"""Rendered-prompt checks for review-and-fix, from PR #406 review rounds 3-4.

Renders the real YAML through the engine, as an agent would receive it, and
pins the merge-fix-worktrees defects review rounds found in the prose: an
unnormalized ref comparison that silently falls through to an untrusted
fallback, a worktree path pasted into shell source even after being
assigned to a variable, and a `git status` check that only looked at stdout
and ignored a non-zero exit code.
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
        self.assertIn("silently falls through to the untrusted fallback", self.prompt)

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
        self.assertIn('WORKTREE_PATH="$(REF="refs/heads/$BRANCH" awk', self.prompt)

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
        self.assertIn("BRANCH=\"$(jq -r '.branch' ", self.prompt)
        self.assertIn('REF="refs/heads/$BRANCH" awk', self.prompt)
        self.assertIn('ENVIRON["REF"]', self.prompt)
        self.assertNotIn('-v ref="refs/heads/<branch>"', self.prompt)


class TestMergeFixWorktreesStatusExitCode(unittest.TestCase):
    """The gate only treated non-empty `git status` stdout as a failure. A
    removed or unreadable worktree can make `git status` exit non-zero with
    no stdout, and that silently read as clean."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["merge-fix-worktrees"])

    def test_exit_code_is_captured(self) -> None:
        self.assertIn('echo "EXIT=$?"', self.prompt)

    def test_nonzero_exit_is_called_out_as_failure(self) -> None:
        self.assertIn(
            "a non-zero exit code, means fail", self.prompt
        )

    def test_nonzero_exit_detail_format_is_specified(self) -> None:
        self.assertIn("git status exited non-zero: <code>", self.prompt)


if __name__ == "__main__":
    unittest.main()
