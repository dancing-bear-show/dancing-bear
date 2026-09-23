"""Rendered-prompt checks for review-and-fix, from PR #406 review round 3.

Renders the real YAML through the engine, as an agent would receive it, and
pins the merge-fix-worktrees defects a review round found in the prose: an
unnormalized ref comparison that silently falls through to an untrusted
fallback, and an unquoted worktree path in a shell command.
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
    """<worktree_path> was inserted into shell source unquoted: a checkout
    path containing spaces splits the `git -C` argument, and shell
    metacharacters in the path can be interpreted."""

    def setUp(self) -> None:
        self.prompt = _flat(_prompts()["merge-fix-worktrees"])

    def test_worktree_path_is_captured_in_a_shell_variable(self) -> None:
        self.assertIn("WORKTREE_PATH=<worktree_path>", self.prompt)

    def test_git_dash_c_uses_the_quoted_variable(self) -> None:
        self.assertIn('git -C "$WORKTREE_PATH" status --porcelain', self.prompt)

    def test_unquoted_worktree_path_no_longer_appears(self) -> None:
        self.assertNotIn("git -C <worktree_path>", self.prompt)


if __name__ == "__main__":
    unittest.main()
