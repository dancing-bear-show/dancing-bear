"""Execution check for implement-gap's qlty criterion (PR #406 round 13).

The criterion used to ask the agent to paste ``<changed files>`` into a qlty
command, so a path with spaces, ``$()``, backticks or ``;`` would be split
or executed. This runs the command the criterion now prescribes against a
real repo with hostile file names, with qlty replaced by a recording stub.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - runs git/bash against a temp repo
import tempfile
import unittest
from pathlib import Path

from workflow.parser import parse_workflow

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / "workflows/domains/implement-gap.yaml"


def _qlty_command() -> str:
    """The one-call shell command inside the qlty criterion, verbatim."""
    for stage in parse_workflow(str(_WORKFLOW)).stages:
        for criterion in stage.validation.criteria if stage.validation else ():
            if "qlty-paths.z" in criterion:
                start = criterion.index("as ONE Bash call: `") + len("as ONE Bash call: `")
                return criterion[start: criterion.index("`. PATHS=0")]
    raise AssertionError("qlty criterion not found")


@unittest.skipUnless(all(map(shutil.which, ("git", "bash"))), "needs git and bash")
class TestQltyCriterionIsArgvSafe(unittest.TestCase):

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.repo, self.ws = root / "repo", root / "work space"
        (self.ws / "validation").mkdir(parents=True)
        self._git("init", "-q", str(self.repo))
        (self.repo / "a b.py").write_text("a = 1\n")
        (self.repo / "gone.py").write_text("g = 1\n")
        self._git("-C", str(self.repo), "add", "a b.py", "gone.py")
        self._git("-C", str(self.repo), "commit", "-q", "-m", "base")
        (self.repo / "a b.py").write_text("a = 2\n")
        (self.repo / "gone.py").unlink()
        (self.repo / "$(touch PWNED).py").write_text("x = 1\n")
        (self.repo / "bad.py").write_text("b = 1\n")
        # A stand-in for qlty: records each path, fails on bad.py.
        self.log = root / "checked.log"
        self.stub = root / "qlty-stub"
        self.stub.write_text(f'#!/bin/bash\nprintf "%s\\n" "$2" >> "{self.log}"\n[ "$2" != bad.py ]\n')
        self.stub.chmod(0o755)

    @staticmethod
    def _git(*args: str) -> None:
        argv = [str(shutil.which("git")), "-c", "user.name=t", "-c", "user.email=t@t", *args]
        subprocess.run(argv, check=True, capture_output=True)  # nosec B603 - fixed argv, temp repo

    def _run(self) -> subprocess.CompletedProcess[str]:
        command = (_qlty_command().replace("{workspace}", str(self.ws))
                   .replace("~/.qlty/bin/qlty", str(self.stub)))
        argv = [str(shutil.which("bash")), "-c", command]
        return subprocess.run(argv, cwd=self.repo, capture_output=True, text=True)  # nosec B603 - runs the workflow's own command in a temp repo

    def test_every_changed_path_is_checked_twice_as_data(self) -> None:
        res = self._run()
        checked = self.log.read_text().splitlines()
        expected = sorted(["a b.py", "$(touch PWNED).py", "bad.py"] * 2)
        self.assertEqual(sorted(checked), expected)
        self.assertFalse((self.repo / "PWNED").exists())
        self.assertIn("PATHS=3", res.stdout)

    def test_a_finding_in_any_file_fails_the_run(self) -> None:
        self.assertIn("QLTY_STATUS=1", self._run().stdout)


if __name__ == "__main__":
    unittest.main()
