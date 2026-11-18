import os
import subprocess  # nosec B404 - test fixture runs fixed git argv
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from core.gitutil import GIT_ENV_OVERRIDES, git_env, git_toplevel, run_git
from core.paths import repo_root
from core.process import RC_TIMEOUT, CompletedRun


class TestGitEnv(unittest.TestCase):
    def test_overrides_are_scrubbed_and_others_kept(self) -> None:
        polluted = dict.fromkeys(GIT_ENV_OVERRIDES, "/elsewhere")
        polluted["KEEP_ME"] = "1"
        with mock.patch.dict(os.environ, polluted):
            env = git_env()
        for name in GIT_ENV_OVERRIDES:
            self.assertNotIn(name, env)
        self.assertEqual(env["KEEP_ME"], "1")

    def test_run_git_passes_scrubbed_env_and_timeout(self) -> None:
        done = CompletedRun(stdout="", stderr="", returncode=0)
        with (
            mock.patch.dict(os.environ, {"GIT_DIR": "/elsewhere"}),
            mock.patch("core.gitutil.run_binary", return_value=done) as run,
        ):
            run_git(["status"], cwd="/x", timeout=7)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["git", "status"])
        self.assertNotIn("GIT_DIR", kwargs["env"])
        self.assertEqual(kwargs["timeout"], 7)
        self.assertEqual(kwargs["cwd"], "/x")


class TestGitToplevel(unittest.TestCase):
    def test_inside_repo_returns_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)  # nosec B603 B607
            sub = root / "a" / "b"
            sub.mkdir(parents=True)
            top = git_toplevel(sub)
        if top is None:
            self.fail("git_toplevel returned None inside a repository")
        self.assertEqual(top.resolve(), root)

    def test_inherited_git_dir_does_not_redirect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            root = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)  # nosec B603 B607
            subprocess.run(["git", "init", "-q", other], check=True)  # nosec B603 B607
            with mock.patch.dict(os.environ, {"GIT_DIR": str(Path(other) / ".git")}):
                top = git_toplevel(root)
        if top is None:
            self.fail("git_toplevel returned None inside a repository")
        self.assertEqual(top.resolve(), root)

    def test_not_a_repo_returns_none(self) -> None:
        run = CompletedRun(stdout="", stderr="fatal: not a git repository", returncode=128)
        with mock.patch("core.gitutil.run_binary", return_value=run):
            self.assertIsNone(git_toplevel("/nowhere"))

    def test_timeout_returns_none(self) -> None:
        run = CompletedRun(stdout="", stderr="timeout", returncode=RC_TIMEOUT, timed_out=True)
        with mock.patch("core.gitutil.run_binary", return_value=run):
            self.assertIsNone(git_toplevel("/x", timeout=0.1))

    def test_missing_git_returns_none(self) -> None:
        run = CompletedRun(
            stdout="", stderr="git: not found", returncode=127, exec_error=FileNotFoundError()
        )
        with mock.patch("core.gitutil.run_binary", return_value=run):
            self.assertIsNone(git_toplevel())

    def test_empty_output_returns_none(self) -> None:
        run = CompletedRun(stdout="\n", stderr="", returncode=0)
        with mock.patch("core.gitutil.run_binary", return_value=run):
            self.assertIsNone(git_toplevel())


class TestRepoRoot(unittest.TestCase):
    def test_root_holds_this_projects_pyproject(self) -> None:
        root = repo_root()
        self.assertTrue((root / "pyproject.toml").is_file())
        self.assertTrue((root / "src" / "core" / "paths.py").is_file())

    def test_unrelated_pyproject_is_not_a_match(self) -> None:
        from core.paths import _names_this_project

        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "pyproject.toml"
            other.write_text('[project]\nname = "something-else"\n', encoding="utf-8")
            self.assertFalse(_names_this_project(other))
            self.assertFalse(_names_this_project(Path(tmp) / "missing.toml"))


if __name__ == "__main__":
    unittest.main()
