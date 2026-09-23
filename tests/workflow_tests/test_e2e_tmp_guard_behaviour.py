"""Run consolidate-schema's PII scratch-dir guard, as rendered, against real worktrees.

test_isolated_workspace_refs pins the snippet's TEXT. Text checks passed while
the snippet was broken three ways, each found only by executing it:

* `for ROOT in $ROOTS` never word-splits under zsh, so the check never ran;
* bash's `pwd -P` keeps the case you typed, so on a case-insensitive
  filesystem `.../LINKED/tmp` escaped a path-prefix match into a worktree;
* zsh skips an EXIT trap on SIGTERM, leaking the PII scratch directory.

So this extracts the snippet from the engine-rendered test-e2e-data prompt --
what an agent actually receives -- and runs it in a throwaway repo that has a
main checkout and linked worktrees. bash is required; zsh runs when installed
(it is not a CI dependency, and is what the Bash tool uses on macOS).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess  # nosec B404 - runs a trusted snippet from an in-repo workflow
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from workflow.compiler import compile_workflow
from workflow.dispatch import build_agent_prompt
from workflow.parser import parse_workflow

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / "workflows/resume/consolidate-schema.yaml"
_PROCEED = "SNIPPET-PROCEEDED"


def _rendered_snippet() -> str:
    """The guard block exactly as the test-e2e-data agent receives it."""
    defn = parse_workflow(str(_WORKFLOW))
    manifest = compile_workflow(defn, project_root=_ROOT, trigger_params={})
    with tempfile.TemporaryDirectory() as ws:
        lines = build_agent_prompt(
            manifest.resolved_stages["test-e2e-data"], defn.name, ws
        ).splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("E2E_TMP=$(mktemp"))
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == 'done < "$ROOTS_FILE"')
    return textwrap.dedent("\n".join(lines[start : end + 1])) + "\n"


def _git(*args: str, cwd: Path) -> None:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True,  # nosec B603 B607 - fixed git argv
                   capture_output=True)


def _case_insensitive(directory: Path) -> bool:
    probe = directory / "CaseProbe"
    probe.mkdir()
    try:
        return (directory / "caseprobe").exists()
    finally:
        probe.rmdir()


class _SnippetHarness(unittest.TestCase):
    shells: tuple[str, ...] = ()
    # Built once per class in setUpClass.
    snippet: str
    tmp: Path
    main: Path
    linked: Path
    other: Path
    outside: Path

    @classmethod
    def setUpClass(cls) -> None:
        # The base only holds the cases; each per-shell subclass runs them. An
        # empty `shells` would loop over nothing and pass, so refuse it outright.
        if cls is _SnippetHarness:
            raise unittest.SkipTest("abstract base: cases run in the per-shell subclasses")
        if not cls.shells:
            raise AssertionError(f"{cls.__name__} names no shell -- it would assert nothing")
        cls.snippet = _rendered_snippet()
        cls.tmp = Path(tempfile.mkdtemp()).resolve()
        cls.main = cls.tmp / "main"
        cls.main.mkdir()
        _git("init", "-q", cwd=cls.main)
        _git("commit", "-q", "--allow-empty", "-m", "init", cwd=cls.main)
        cls.linked = cls.tmp / "linked"
        cls.other = cls.tmp / "other wt"  # a space in the path, on purpose
        _git("worktree", "add", "-q", str(cls.linked), "-b", "linked", cwd=cls.main)
        _git("worktree", "add", "-q", str(cls.other), "-b", "other", cwd=cls.main)
        cls.outside = cls.tmp / "outside"
        for d in (cls.outside, cls.linked / "tmp", cls.other / "tmp", cls.main / "tmp"):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _body(self, tail: str) -> Path:
        body = self.tmp / f"body-{abs(hash(tail))}.sh"
        body.write_text(self.snippet + tail + "\n", encoding="utf-8")
        return body

    def _run(self, shell: str, tmpdir: Path, cwd: Path) -> tuple[int, str]:
        body = self._body(f"echo {_PROCEED}")
        proc = subprocess.run(  # nosec B603 - shell from a fixed allowlist, trusted body
            [shell, str(body)], cwd=cwd, env={**os.environ, "TMPDIR": str(tmpdir)},
            capture_output=True, text=True, timeout=60,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def _leaks(self, where: Path) -> list[str]:
        return sorted(p.name for p in where.glob("e2e-schema.*"))

    def _assert_aborts(self, tmpdir: Path, cwd: Path, leak_dir: Path | None = None) -> None:
        for shell in self.shells:
            with self.subTest(sh=shell, tmpdir=str(tmpdir)):
                rc, out = self._run(shell, tmpdir, cwd)
                self.assertNotIn(_PROCEED, out, msg=f"guard let the run proceed:\n{out}")
                self.assertNotEqual(rc, 0)
                self.assertEqual(self._leaks(leak_dir or tmpdir), [])

    def _assert_proceeds(self, tmpdir: Path, cwd: Path) -> None:
        for shell in self.shells:
            with self.subTest(sh=shell, tmpdir=str(tmpdir)):
                rc, out = self._run(shell, tmpdir, cwd)
                self.assertIn(_PROCEED, out, msg=out)
                self.assertEqual(rc, 0)
                self.assertEqual(self._leaks(tmpdir), [], msg="EXIT trap did not clean up")

    # -- the reviewer's case and its neighbours ------------------------------
    def test_outside_every_checkout_proceeds(self) -> None:
        self._assert_proceeds(self.outside, self.linked)

    def test_inside_another_linked_worktree_aborts(self) -> None:
        self._assert_aborts(self.other / "tmp", self.linked)

    def test_inside_the_main_checkout_aborts(self) -> None:
        self._assert_aborts(self.main / "tmp", self.linked)

    def test_inside_own_worktree_aborts(self) -> None:
        self._assert_aborts(self.linked / "tmp", self.linked)

    def test_symlink_into_a_worktree_aborts(self) -> None:
        link = self.tmp / "sneaky-link"
        if not link.exists():
            link.symlink_to(self.other / "tmp")
        self._assert_aborts(link, self.linked, leak_dir=self.other / "tmp")

    def test_case_variant_spelling_aborts(self) -> None:
        if not _case_insensitive(self.tmp):
            self.skipTest("filesystem is case-sensitive; a case variant is a different path")
        variant = self.tmp / "LINKED" / "tmp"
        self._assert_aborts(variant, self.linked, leak_dir=self.linked / "tmp")

    def test_not_a_git_repo_fails_closed(self) -> None:
        self._assert_aborts(self.outside, self.outside)

    # -- cleanup under interruption ------------------------------------------
    def test_sigterm_mid_run_removes_the_scratch_dir(self) -> None:
        # `sleep & wait`, not a foreground `sleep`: a shell defers a trapped
        # signal until its foreground command ends, so a signal racing the fork
        # would stall the test for the full sleep. `wait` returns at once.
        body = self._body("sleep 30 & echo READY; wait $!")
        for shell in self.shells:
            with self.subTest(sh=shell):
                proc = subprocess.Popen(  # nosec B603 - allowlisted shell, trusted body
                    [shell, str(body)], cwd=self.linked, stdout=subprocess.PIPE, text=True,
                    env={**os.environ, "TMPDIR": str(self.outside)}, start_new_session=True,
                )
                stdout = proc.stdout
                if stdout is None:
                    self.fail("Popen gave no stdout pipe")
                try:
                    self.assertEqual(stdout.readline().strip(), "READY")
                    self.assertEqual(len(self._leaks(self.outside)), 1)  # it exists mid-run
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=10)
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL)
                    stdout.close()
                deadline = time.monotonic() + 5
                while self._leaks(self.outside) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(self._leaks(self.outside), [],
                                 msg=f"{shell}: SIGTERM left the PII scratch dir behind")


class TestGuardUnderBash(_SnippetHarness):
    shells = ("bash",)

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("bash") is None:
            raise AssertionError("bash is required to exercise the PII guard")
        super().setUpClass()


@unittest.skipIf(shutil.which("zsh") is None, "zsh not installed; it is not a CI dependency")
class TestGuardUnderZsh(_SnippetHarness):
    shells = ("zsh",)

