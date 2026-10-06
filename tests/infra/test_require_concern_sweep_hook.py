"""Tests for the require-concern-sweep PreToolUse hook.

The hook runs by path through ``bash`` with a synthetic payload over throwaway git
repos, exactly as the harness would run it. The script under test defaults to the
staged copy; set ``REQUIRE_CONCERN_SWEEP_HOOK`` to the installed
``.claude/hooks/require-concern-sweep.sh`` to run the same suite against it.

Records are written with ``workflow.sweep_record.write_waived`` -- the CLI's own
writer -- so a drift between the record the CLI writes and the one the hook reads
fails here.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess  # nosec B404 - runs the hook and git with fixed argv
import tempfile
import unittest
from pathlib import Path

from tests.infra.test_check_pythonpath_hook import _launches_unisolated_python
from workflow.sweep_record import write_waived

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = Path(
    os.environ.get("REQUIRE_CONCERN_SWEEP_HOOK")
    or REPO_ROOT / ".claude" / "hooks" / "require-concern-sweep.sh"
)
HELPER = HOOK.parent / "_pr_create_targets.py"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
HOOK_COMMAND = 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/require-concern-sweep.sh"'

_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "PYTHONPATH"},
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}

#: Commands that open a PR for HEAD of the payload cwd.
HEAD_CREATES = [
    "gh pr create",
    "gh pr create --base main --title t --body-file b.md",
    "gh pr create --repo o/r --fill",
    "gh pr --repo o/r create",
    "gh pr new",
    "cd sub && gh pr create",
    "FOO=1 gh pr create",
    "env gh pr create",
    "env FOO=1 command gh pr create",
    "builtin command gh pr create",
    "/opt/homebrew/bin/gh pr create",
    "GH pr create",
    "timeout 60 gh pr create",
    "git status; gh pr create",
    "git push -u origin HEAD && gh pr create --fill",
    "ls\ngh pr create",
    "x#; gh pr create",
    "gh \\\npr create",
    "echo `gh pr create`",
    "echo $(gh pr create)",
    "{ gh pr create; }",
    "bash -c 'gh pr create'",
    "bash -O extglob -c 'gh pr create'",
    "bash -O extglob -O errexit -c 'gh pr create'",
    "sh -lc \"git push && gh pr create\"",
    "eval gh pr create",
    "./bin/github pr create --base main --body-file b.md",
    "bin/github pr create --base main --body-file b.md",
    "python3 -m github_assistant pr create --base main --body-file b.md",
    "./bin/assistant github pr create --base main --body-file b.md",
    "./bin/pr-assistant",
    "./bin/pr-assistant --base main --no-create --create",
    "hub pull-request",
    # Quoting that bash removes before running: the words are still `gh pr create`.
    "gh p''r create",
    'gh "p"r create',
    "gh p\\r create",
    "gh $'\\x70'r create",
    "gh $'\\x70\\x72' create",
    'gh $"pr" create',
    "g''h pr create",
    "gh pr cre''ate",
    "hub pu''ll-request",
    # Value-taking global options before the subcommand (PR #454 review).
    "gh --repo o/r pr create",
    "gh -R o/r pr create",
    "gh -R=o/r pr create",
    "./bin/github --agentic-domain x pr create",
    "hub -c a=b pull-request",
    # Same-shell groups keep the cwd of a cd inside them.
    "{ cd sub; } && gh pr create",
    "if cd sub; then gh pr create; fi",
]

#: Commands that are not PR creation and must pass with no record anywhere.
NOT_CREATES = [
    "gh pr view",
    "gh pr view 12 --json title",
    "gh pr list --state open",
    'echo "gh pr create"',
    "echo 'gh pr create --head x'",
    'git commit -m "gh pr create"',
    "ls -la",
    "make test",
    "./bin/github pr view --fields title",
    "./bin/pr-assistant --no-create",
    "./bin/pr-assistant --dry-run",
    "gh api repos/o/r/pulls",
    "gh api repos/o/r/pulls/12/comments",
    "printf '%s' pr",
    # Expansion in words that do not decide PR creation stays allowed.
    "N=5; gh pr view $N",
    "echo $HOME 'x'",
    "ls *.py",
    "gh api repos/o/r/issues/$N/comments",
    "echo $'\\x70r'",
]

#: Cannot be checked before the shell runs; blocked even with a HEAD record.
UNVERIFIABLE = [
    "echo 'gh pr create",
    'gh pr create --title "unterminated',
    "$GH pr create",
    'gh pr create --head "$BRANCH"',
    'cd "$DIR" && gh pr create',
    "gh api graphql -f query='mutation { createPullRequest(input: {}) { pullRequest { url } } }'",
    "gh api -X POST repos/o/r/pulls -f title=t",
    # A word that decides PR creation, built at run time: bash may expand it to pr.
    "gh p${EMPTY}r create",
    "gh p$EMPTY'r' create",
    "gh p$(true)r create",
    "gh p`true`r create",
    "gh {pr,} create",
    "gh p{r,} create",
    "gh p? create",
    "S=pr; gh $S create",
    "gh pr $SUB",
    "hub pull-$R",
    "gh api -X POST repos/o/r/$E -f head=x",
    # The directory gh runs in is not knowable, or not this one (PR #454 review).
    "hub -C /elsewhere pull-request",
    "hub --git-dir=/elsewhere/.git pull-request",
    "cd sub || gh pr create",
    "pushd sub && popd && gh pr create",
]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(  # nosec B603 B607 - fixed argv
        ["git", *args], cwd=str(cwd), env=_ENV, check=True, capture_output=True, text=True,
    ).stdout.strip()


def run_hook(command: str, cwd: Path, hook: Path = HOOK) -> subprocess.CompletedProcess[str]:
    payload = {
        "session_id": "s",
        "transcript_path": "/Users/someone/.claude/projects/p/s.jsonl",
        "cwd": str(cwd),
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": "d"},
    }
    return subprocess.run(  # nosec B603 B607 - fixed argv; the hook is a repo file
        ["bash", str(hook)], input=json.dumps(payload), cwd=str(cwd), env=_ENV,
        capture_output=True, text=True, timeout=60, check=False,
    )


class RequireConcernSweepHookTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("a\n")
        _git(self.repo, "add", "a.txt")
        _git(self.repo, "commit", "-q", "-m", "one")
        _git(self.repo, "checkout", "-q", "-b", "other")
        (self.repo / "a.txt").write_text("b\n")
        _git(self.repo, "commit", "-q", "-am", "two")
        self.other = _git(self.repo, "rev-parse", "HEAD")
        _git(self.repo, "checkout", "-q", "main")
        self.head = _git(self.repo, "rev-parse", "HEAD")
        (self.repo / "sub").mkdir()

    def _record(self, sha: str) -> None:
        write_waived(self.repo, sha, "test")

    def assertBlocked(self, proc: subprocess.CompletedProcess[str], needle: str = "Blocked") -> None:
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn(needle, proc.stderr)

    # --- blocked without a record, allowed with one -------------------------

    def test_pr_creates_are_blocked_without_a_record(self) -> None:
        for command in HEAD_CREATES:
            with self.subTest(command=command):
                proc = run_hook(command, self.repo)
                self.assertBlocked(proc, self.head)
                self.assertIn("/open-pr", proc.stderr)
                self.assertIn("sweep-record waive", proc.stderr)

    def test_pr_creates_are_allowed_with_a_record_for_head(self) -> None:
        self._record(self.head)
        for command in HEAD_CREATES:
            with self.subTest(command=command):
                proc = run_hook(command, self.repo)
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_head_names_another_branch(self) -> None:
        self._record(self.head)
        for command in (
            "gh pr create --head other",
            "gh pr create --head=other",
            "gh pr create -H other",
            "gh pr create -Hother",
            "gh pr create --head me:other",
            "./bin/github pr create --base main --body-file b --head other",
            "./bin/github pr create --base main --body-file b --hea other",
            "gh api -X POST repos/o/r/pulls -f head=other -f base=main",
            "gh api -X POST repos/o/r/pu''lls -f head=other -f base=main",
            "gh api repos/{owner}/{repo}/pulls -F head=other",
        ):
            with self.subTest(command=command):
                self.assertBlocked(run_hook(command, self.repo), self.other)
        self._record(self.other)
        self.assertEqual(run_hook("gh pr create --head other", self.repo).returncode, 0)

    def test_head_that_does_not_resolve_fails_closed(self) -> None:
        self._record(self.head)
        for command in ("gh pr create --head no-such-branch", "gh pr create --head -x", "gh pr create --head"):
            with self.subTest(command=command):
                self.assertBlocked(run_hook(command, self.repo), "cannot")

    def test_record_from_another_worktree_counts(self) -> None:
        wt = self.root / "wt"
        _git(self.repo, "worktree", "add", "-q", str(wt), "other")
        self._record(self.other)
        self.assertEqual(run_hook("gh pr create", wt).returncode, 0)
        self.assertBlocked(run_hook("gh pr create", self.repo), self.head)

    def test_cd_that_does_not_reach_gh_is_not_followed(self) -> None:
        """PR #454 review: a cd in a pipeline, background job or subshell leaves gh in the
        original directory. Checking the cd target's record would let gh open from a
        checkout that has none."""
        wt = self.root / "wt"
        _git(self.repo, "worktree", "add", "-q", str(wt), "other")
        self._record(self.other)  # only the worktree's HEAD has a record
        self.assertEqual(run_hook(f"cd {wt} && gh pr create", self.repo).returncode, 0)
        self.assertEqual(run_hook(f"cd {wt}; gh pr create", self.repo).returncode, 0)
        self.assertEqual(run_hook(f"(cd {wt} && gh pr create)", self.repo).returncode, 0)
        for command in (f"cd {wt} & gh pr create", f"cd {wt} | gh pr create",
                        f"(cd {wt}); gh pr create", f"( cd {wt} ) ; gh pr create"):
            with self.subTest(command=command):
                self.assertBlocked(run_hook(command, self.repo), self.head)

    def test_cd_inside_conditional_branch_makes_cwd_unknown(self) -> None:
        """A cd inside then/else/elif/do may not execute; the hook must fail closed
        rather than treating the conditional branch's target directory as the cwd for
        subsequent commands.

        PR #454 review: ``if false; then cd /worktree-with-record; fi; gh pr create``
        should be blocked because the real cwd (self.repo) has no record.  Before the
        fix the walker applied the cd unconditionally and authorised from the worktree.
        """
        wt = self.root / "wt"
        _git(self.repo, "worktree", "add", "-q", str(wt), "other")
        self._record(self.other)  # only the worktree's HEAD has a record, not self.repo
        # All of these conditionally cd into wt; the real shell stays in self.repo.
        for template in (
            "if false; then cd {wt}; fi; gh pr create",
            "if true; then cd {wt}; fi; gh pr create",
            "while false; do cd {wt}; done; gh pr create",
            "for x in 1; do cd {wt}; done; gh pr create",
        ):
            command = template.format(wt=wt)
            with self.subTest(command=command):
                self.assertBlocked(run_hook(command, self.repo), "cannot")

    def test_a_record_naming_another_sha_does_not_count(self) -> None:
        self._record(self.other)
        path = Path(_git(self.repo, "rev-parse", "--absolute-git-dir"))
        records = path / "dancing-bear" / "concern-sweeps"
        shutil.copy(records / f"{self.other}.json", records / f"{self.head}.json")
        self.assertBlocked(run_hook("gh pr create", self.repo), self.head)

    def test_outside_a_git_repo_fails_closed(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        self.assertBlocked(run_hook("gh pr create", outside), "cannot determine")

    # --- not PR creation -----------------------------------------------------

    def test_other_commands_are_allowed(self) -> None:
        for command in NOT_CREATES:
            with self.subTest(command=command):
                proc = run_hook(command, self.repo)
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_non_pr_commands_short_circuit_before_python(self) -> None:
        """Without the helper, a PR-free command still passes and gh pr create fails closed."""
        lone = self.root / "lone"
        lone.mkdir()
        hook = lone / HOOK.name
        shutil.copy(HOOK, hook)
        self.assertEqual(run_hook("ls -la && git status", self.repo, hook).returncode, 0)
        self.assertBlocked(run_hook("gh pr create", self.repo, hook), "missing")
        self.assertBlocked(run_hook("gh \\u0070r create", self.repo, hook), "missing")
        # The pre-filter is load-bearing: a command it passes is never analysed, so
        # every way of spelling pr without the substring must still reach Python.
        for command in ("gh p''r create", 'gh "p"r create', "gh p\\r create", "gh $'\\x70'r create",
                        "gh p${X}r create", "gh p`true`r create", "gh p{r,} create", "gh p? create",
                        "gh p[r] create", "hub pu''ll-request"):
            with self.subTest(command=command):
                self.assertBlocked(run_hook(command, self.repo, hook), "missing")

    # --- fail closed ---------------------------------------------------------

    def test_unverifiable_commands_fail_closed(self) -> None:
        self._record(self.head)
        for command in UNVERIFIABLE:
            with self.subTest(command=command):
                self.assertBlocked(run_hook(command, self.repo), "cannot")

    def test_malformed_payload_fails_closed(self) -> None:
        proc = subprocess.run(  # nosec B603 B607 - fixed argv
            ["bash", str(HOOK)], input='{"tool_input": {"command": "gh pr create"', env=_ENV,
            capture_output=True, text=True, timeout=60, check=False,
        )
        self.assertBlocked(proc)

    # --- isolation -------------------------------------------------------------

    def test_hook_and_settings_entry_never_start_an_unisolated_interpreter(self) -> None:
        # Read the real settings file: a hook with passing tests and no
        # PreToolUse entry never runs.
        pre = json.loads(SETTINGS.read_text())["hooks"]["PreToolUse"]
        entries = [e for e in pre if any(h.get("command") == HOOK_COMMAND for h in e["hooks"])]
        self.assertEqual(len(entries), 1, "require-concern-sweep.sh is not wired exactly once")
        entry = entries[0]
        self.assertEqual(entry["matcher"], "Bash")
        commands = [h["command"] for h in entry["hooks"]]
        self.assertEqual(commands, [HOOK_COMMAND])
        for text in (*commands, HOOK.read_text()):
            self.assertFalse(_launches_unisolated_python(text))
        launches = [
            line for line in HOOK.read_text().splitlines()
            if not line.lstrip().startswith("#") and "python3 " in line and not line.lstrip().startswith("echo")
        ]
        self.assertTrue(launches)
        for line in launches:
            self.assertIn("python3 -I -S ", line)
        self.assertNotIn("bin/workflow", "\n".join(
            line for line in HOOK.read_text().splitlines() if not line.lstrip().startswith("#")
        ))

    def test_helper_imports_only_the_standard_library(self) -> None:
        allowed = {"__future__", "json", "os", "re", "shlex", "stat", "subprocess", "sys",
                   "dataclasses", "pathlib"}
        tree = ast.parse(HELPER.read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "relative import in the helper")
                imported.add((node.module or "").split(".")[0])
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
        self.assertLessEqual(imported, allowed)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
