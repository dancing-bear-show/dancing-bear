"""The WorktreeCreate hook must name and create a worktree without corrupting
the caller's repo, and its failure mode must match what the harness expects.

`.claude/scripts/name-worktree.sh` is invoked by the harness with a JSON
payload (``{"name": "..."}``) on stdin whenever a session or subagent asks for
an isolated worktree. Unlike ``check-pythonpath.sh`` (a SessionStart hook that
emits ``{"systemMessage": ...}`` and never blocks), this hook's contract is:

  - stdout's LAST LINE is the absolute path of the newly created worktree,
    as PLAIN TEXT — not JSON. The harness chdir()s into whatever that line
    says, so a wrong or missing path breaks session start outright.
  - exit 1 when the input has no usable ``.name`` — this hook is allowed to
    block, deliberately, because a missing name is a caller-contract error,
    not an environmental hazard.
  - the branch/directory name actually used comes from ``/usr/share/dict/words``
    (three random 4-7 letter lowercase words), NOT from the caller-supplied
    name in the normal path. The input name is a fallback only.

Every test here runs against a THROWAWAY git repository in a temp directory
and passes it as ``cwd`` to the hook, so no test ever creates, renames, or
touches a worktree of the real dancing-bear repo.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404 - runs this repo's own hook script, no user input
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "scripts" / "name-worktree.sh"

# Three lowercase words, 4-7 letters each, joined by hyphens - the shape the
# hook's dict-based generator produces on a normal run.
_GENERATED_NAME_RE = re.compile(r"^[a-z]{4,7}-[a-z]{4,7}-[a-z]{4,7}$")


def _make_sandbox_repo(root: Path) -> Path:
    """A real, throwaway git repo the hook is safe to run `git worktree add` in."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # nosec B603 B607 - fixed argv, temp dir
        ["git", "init", "-q", "."],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    subprocess.run(  # nosec B603 B607 - fixed argv, temp dir
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return root


def _run_hook(
    repo: Path, payload: str | None, timeout: int = 30
) -> subprocess.CompletedProcess[str]:
    """Run the hook with *payload* as raw stdin, cwd inside *repo*."""
    return subprocess.run(  # nosec B603 B607 - in-repo script, sandboxed cwd
        ["bash", str(HOOK)],
        input=payload if payload is not None else "",
        capture_output=True,
        text=True,
        cwd=str(repo),
        timeout=timeout,
    )


class TestNameWorktreeHookHappyPath(unittest.TestCase):
    """A well-formed request must produce a real worktree and print its path."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = _make_sandbox_repo(Path(self._td.name, "repo"))

    def test_creates_a_worktree_and_prints_its_absolute_path_as_last_line(
        self,
    ) -> None:
        proc = _run_hook(self.repo, json.dumps({"name": "whatever"}))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines, "hook printed nothing on stdout")
        printed_path = Path(lines[-1])

        self.assertTrue(
            printed_path.is_absolute(),
            f"last stdout line is not an absolute path: {printed_path}",
        )
        self.assertTrue(
            printed_path.is_dir(),
            f"printed path does not exist as a directory: {printed_path}",
        )
        # .resolve() on both sides: the hook prints a canonicalized path
        # (derived via `cd ... && pwd`-style resolution inside git), while
        # self.repo may still contain a symlink component (e.g. macOS's
        # /tmp -> /private/tmp), so a literal comparison would fail for a
        # reason that has nothing to do with the hook's behaviour.
        self.assertEqual(
            printed_path.parent,
            (self.repo / ".claude" / "worktrees").resolve(),
        )

    def test_output_is_plain_text_not_json(self) -> None:
        """Unlike check-pythonpath.sh, this hook's contract is a bare path.

        A caller that tried to json.loads() this hook's stdout would break —
        confirm that is genuinely not the contract, so a future change to
        JSON-wrap the output is a deliberate, visible decision.
        """
        proc = _run_hook(self.repo, json.dumps({"name": "whatever"}))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(proc.stdout)

    def test_generated_branch_name_ignores_the_caller_supplied_name(
        self,
    ) -> None:
        """The dict-word generator wins over the input name WHEN THE DICT EXISTS.

        `/usr/share/dict/words` ships on macOS but not on a stock Linux runner,
        so the generator legitimately cannot run everywhere. Asserting the
        generated shape unconditionally passed locally and failed CI — the
        assertion was platform-dependent, not the hook. Skip where the dict is
        absent and assert the documented fallback instead, so both platforms
        check something real.
        """
        proc = _run_hook(self.repo, json.dumps({"name": "caller-supplied-name"}))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        printed_path = Path(proc.stdout.splitlines()[-1])
        generated_name = printed_path.name

        # Key off what the hook actually did, not off whether the dict file
        # exists: the generator can also fail with the file present (an
        # unreadable file, a python3 that cannot open it), and a proxy check
        # would then assert the wrong branch. The fallback is exactly the
        # sanitised caller name, so its presence identifies which path ran.
        if generated_name == "caller-supplied-name":
            self.assertTrue(printed_path.is_dir(), "fallback produced no worktree")
            self.skipTest("name generator unavailable here; asserted the fallback instead")

        self.assertNotEqual(generated_name, "caller-supplied-name")
        self.assertRegex(
            generated_name,
            _GENERATED_NAME_RE,
            f"generated name does not match the documented '3 random nouns' "
            f"shape: {generated_name!r}",
        )

    def test_creates_a_real_git_worktree_registered_with_the_repo(self) -> None:
        """The printed path must be an actual `git worktree`, not just a dir.

        A directory that merely exists on disk (e.g. a stray `mkdir`) would
        satisfy `is_dir()` but leave the repo's worktree list unaware of it -
        checked separately so a regression that creates the folder without
        running `git worktree add` is still caught.
        """
        proc = _run_hook(self.repo, json.dumps({"name": "whatever"}))
        printed_path = Path(proc.stdout.splitlines()[-1])

        listing = subprocess.run(  # nosec B603 B607 - fixed argv, sandbox repo
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        self.assertIn(str(printed_path), listing.stdout)

    def test_running_twice_produces_two_distinct_worktrees_not_a_collision(
        self,
    ) -> None:
        """Idempotency for this hook means "safe to call again", not "no-op".

        Each invocation mints a fresh random branch name, so two calls with
        the same input must not collide, clobber, or error on the second run -
        the hallmark of a hook whose repeated effect does not compound into
        breakage.
        """
        first = _run_hook(self.repo, json.dumps({"name": "whatever"}))
        second = _run_hook(self.repo, json.dumps({"name": "whatever"}))

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)

        first_path = Path(first.stdout.splitlines()[-1])
        second_path = Path(second.stdout.splitlines()[-1])

        self.assertNotEqual(first_path, second_path)
        self.assertTrue(first_path.is_dir())
        self.assertTrue(second_path.is_dir())

        listing = subprocess.run(  # nosec B603 B607 - fixed argv, sandbox repo
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        self.assertIn(str(first_path), listing.stdout)
        self.assertIn(str(second_path), listing.stdout)


class TestNameWorktreeHookMissingOrMalformedInput(unittest.TestCase):
    """Missing/empty `.name` must BLOCK - this hook's design differs from
    check-pythonpath.sh's "always exit 0" contract, and that difference is
    the behaviour under test here."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = _make_sandbox_repo(Path(self._td.name, "repo"))

    def test_no_stdin_at_all_exits_nonzero_and_creates_nothing(self) -> None:
        proc = _run_hook(self.repo, None)

        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse((self.repo / ".claude" / "worktrees").exists())

    def test_empty_json_object_exits_nonzero_and_creates_nothing(self) -> None:
        proc = _run_hook(self.repo, "{}")

        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse((self.repo / ".claude" / "worktrees").exists())

    def test_empty_string_name_exits_nonzero_and_creates_nothing(self) -> None:
        proc = _run_hook(self.repo, json.dumps({"name": ""}))

        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse((self.repo / ".claude" / "worktrees").exists())

    def test_malformed_json_exits_nonzero_and_creates_nothing(self) -> None:
        """`jq -r '.name // empty'` on invalid JSON prints nothing (with jq's
        error routed to stderr via the `2>/dev/null` in the script), so this
        must fail the same empty-name check as a missing key."""
        proc = _run_hook(self.repo, "{not valid json")

        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse((self.repo / ".claude" / "worktrees").exists())

    def test_name_key_present_but_null_exits_nonzero(self) -> None:
        proc = _run_hook(self.repo, json.dumps({"name": None}))

        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse((self.repo / ".claude" / "worktrees").exists())


class TestNameWorktreeHookNameVariety(unittest.TestCase):
    """A variety of caller-supplied names must not change the hook's own
    output shape, since the generator - not the input - decides the name in
    the normal path. These pin that the caller's name is inert cargo."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = _make_sandbox_repo(Path(self._td.name, "repo"))

    def _assert_normal_success(self, name: str) -> None:
        """A hostile caller name must not break the hook.

        Deliberately does NOT assert the dict-generated shape: that only holds
        where /usr/share/dict/words exists (macOS, not a stock Linux runner).
        Pinning the shape here passed locally and failed CI while the hook was
        behaving correctly on both. What must hold everywhere is that the hook
        succeeds and produces a usable, safe directory name.
        """
        proc = _run_hook(self.repo, json.dumps({"name": name}))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        printed_path = Path(proc.stdout.splitlines()[-1])
        self.assertTrue(printed_path.is_dir(), f"no worktree at {printed_path}")

        produced = printed_path.name
        self.assertTrue(produced, "produced an empty worktree name")
        self.assertFalse(produced.startswith("-"), f"leading dash: {produced!r}")
        self.assertNotIn(" ", produced, f"space survived: {produced!r}")
        self.assertNotIn("/", produced, f"slash survived: {produced!r}")
        self.assertLessEqual(len(produced), 64, f"unbounded name: {len(produced)} chars")

    def test_name_with_spaces_does_not_break_generation(self) -> None:
        self._assert_normal_success("has spaces in it")

    def test_name_with_slashes_does_not_break_generation(self) -> None:
        self._assert_normal_success("has/slash/in/it")

    def test_name_with_unicode_does_not_break_generation(self) -> None:
        self._assert_normal_success("héllo-wörld-🐻")

    def test_name_with_leading_dash_does_not_break_generation(self) -> None:
        self._assert_normal_success("-leading-dash")

    def test_very_long_name_does_not_break_generation(self) -> None:
        self._assert_normal_success("x" * 5000)


class TestNameWorktreeHookNotAGitRepo(unittest.TestCase):
    """Running outside any git repo must fail cleanly, not half-create state."""

    def test_exits_nonzero_and_creates_nothing_when_cwd_is_not_a_repo(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            not_a_repo = Path(td, "plain-dir")
            not_a_repo.mkdir()

            proc = _run_hook(not_a_repo, json.dumps({"name": "whatever"}))

            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse((not_a_repo / ".claude").exists())


class TestNameWorktreeHookFallbackIsUnreachable(unittest.TestCase):
    """Documents a real bug: the `NAME_IN` fallback can never run.

    The header/inline comments promise that when dict-based name generation
    fails, the script falls back to the caller-supplied name:

        NAME=$(python3 -I -S -c "..." 2>/dev/null)
        [ -z "$NAME" ] && NAME="$NAME_IN"

    But the script also runs under `set -euo pipefail`. `2>/dev/null` only
    silences python3's stderr - it does not change its exit status, and a
    command substitution's exit status IS the assignment's exit status. When
    `python3` exits nonzero (e.g. `/usr/share/dict/words` is missing, or any
    other failure inside the snippet), `set -e` kills the whole script at the
    `NAME=$(...)` line itself, before the `[ -z "$NAME" ]` fallback check is
    ever reached. The fallback line is dead code - confirmed with `bash -x`:
    the trace stops at `NAME=` with nothing after it.

    So on a machine where `/usr/share/dict/words` is absent (this script's
    only source of names), the hook does not gracefully fall back to the
    caller's name - it exits nonzero and blocks worktree creation entirely.
    This class pins the ACTUAL behaviour (hard failure), not the commented
    intent (graceful fallback), and is a bug report, not a fix.

    Forcing generation to fail without editing the hook: point $PATH at a
    directory whose `python3` unconditionally exits nonzero, so the script's
    own `NAME=$(python3 ...)` line is what's under test.
    """

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = _make_sandbox_repo(Path(self._td.name, "repo"))

        fake_bin = Path(self._td.name, "fake_bin")
        fake_bin.mkdir()
        fake_python3 = fake_bin / "python3"
        fake_python3.write_text("#!/bin/sh\nexit 1\n")
        fake_python3.chmod(0o755)
        # Real `git`/`bash`/`jq`/etc. must still resolve, so prepend rather
        # than replace PATH.
        real_path = os.environ.get("PATH", "")
        self.fallback_env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{real_path}"}

    def _run_with_broken_python3(
        self, payload: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 B607 - in-repo script, sandbox repo
            ["bash", str(HOOK)],
            input=payload,
            capture_output=True,
            text=True,
            cwd=str(self.repo),
            env=self.fallback_env,
            timeout=30,
        )

    def test_a_failing_generator_falls_back_to_the_caller_name(self) -> None:
        """A failing name generator must fall back, not block worktree creation.

        This test previously pinned the opposite — the fallback was dead code,
        because `set -euo pipefail` aborts the script at a command substitution
        that exits non-zero, so the `[ -z "$NAME" ]` line after it never ran.
        Its failure message said to update it if the fallback became reachable,
        which is exactly what happened: `/usr/share/dict/words` does not exist on
        a stock Linux runner, so the generator fails there for real and this
        defect was turning CI red.
        """
        proc = self._run_with_broken_python3(
            json.dumps({"name": "fallback-safe-name"})
        )

        self.assertEqual(
            proc.returncode,
            0,
            f"a failing generator must not block worktree creation: {proc.stderr}",
        )
        printed = Path(proc.stdout.splitlines()[-1])
        self.assertEqual(
            printed.name,
            "fallback-safe-name",
            "expected the sanitised caller name as the fallback",
        )
        self.assertTrue(printed.is_dir(), f"no worktree created at {printed}")

    def test_the_fallback_sanitises_a_hostile_caller_name(self) -> None:
        """The fallback feeds a git branch name, so it must be safe to use.

        Spaces, slashes and a leading dash all break or confuse `git worktree
        add`; a name of pure punctuation would leave it empty.
        """
        for raw, forbidden in (
            ("name with spaces", " "),
            ("feature/nested/name", "/"),
            ("--leading-dashes", None),
            ("!!!", None),
        ):
            with self.subTest(name=raw):
                proc = self._run_with_broken_python3(json.dumps({"name": raw}))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                produced = Path(proc.stdout.splitlines()[-1]).name
                self.assertTrue(produced, "fell back to an empty name")
                self.assertFalse(produced.startswith("-"), f"leading dash: {produced!r}")
                if forbidden:
                    self.assertNotIn(forbidden, produced)


class TestNameWorktreeHookScriptItself(unittest.TestCase):
    """Static properties of the script that the dynamic tests above can't
    directly observe (redirection, hook wiring)."""

    def test_registered_in_settings_json_as_the_worktreecreate_hook(self) -> None:
        settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text())
        commands = [
            hook.get("command", "")
            for group in settings.get("hooks", {}).get("WorktreeCreate", [])
            for hook in group.get("hooks", [])
        ]
        self.assertTrue(
            any("name-worktree.sh" in cmd for cmd in commands),
            f"name-worktree.sh is not wired as a WorktreeCreate hook: {commands}",
        )

    def test_script_uses_strict_mode(self) -> None:
        """`set -euo pipefail` is what makes a failed `git worktree add`
        propagate as a nonzero exit rather than printing an empty/wrong path
        and exiting 0 - the property the happy-path tests above rely on."""
        text = HOOK.read_text()
        self.assertIn("set -euo pipefail", text)


if __name__ == "__main__":
    unittest.main()
