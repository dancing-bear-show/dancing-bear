"""The SessionStart PYTHONPATH warning must fire exactly when it should.

`.claude/scripts/check-pythonpath.sh` is the layer that covers a bare
``python3 -c`` — the one invocation neither ``bin/_router.py`` nor the Makefile
can intercept. Its value is entirely in which of three states it warns about, so
a parsing slip or a change to the hook's output contract would ship silently.

The hook must emit a single JSON object with a ``systemMessage`` key when
PYTHONPATH names a DIFFERENT checkout of this repo, and emit nothing at all
otherwise. It must never exit non-zero: a wrong PYTHONPATH is a correctness
hazard, not a reason to refuse to start a session.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404 - runs this repo's own hook script, no user input
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "scripts" / "check-pythonpath.sh"


def _run_hook(pythonpath: str | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    return subprocess.run(  # nosec B603 B607 - in-repo script, fixed argv
        ["bash", str(HOOK)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=30,
    )


def _make_fake_checkout(root: Path) -> Path:
    """A decoy checkout: src/ plus the sibling pyproject.toml marker."""
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "decoy"\n')
    return root / "src"


class TestCheckPythonpathHook(unittest.TestCase):
    def test_warns_when_pythonpath_names_another_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            foreign = _make_fake_checkout(Path(td, "other-checkout"))

            proc = _run_hook(str(foreign))

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIn("systemMessage", payload)
            msg = payload["systemMessage"]
            self.assertIn(str(foreign), msg)
            # The message must name the remedy, not merely the problem.
            self.assertIn("direnv allow", msg)
            self.assertIn("make test", msg)

    def test_silent_when_pythonpath_is_this_checkout(self) -> None:
        proc = _run_hook(str(REPO_ROOT / "src"))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_silent_when_pythonpath_is_unset(self) -> None:
        proc = _run_hook(None)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_silent_for_an_unrelated_src_directory(self) -> None:
        """A ``src`` with no sibling pyproject.toml belongs to someone else.

        Warning about it would train the reader to ignore the warning.
        """
        with tempfile.TemporaryDirectory() as td:
            unrelated = Path(td, "some-lib", "src")
            unrelated.mkdir(parents=True)  # deliberately NO pyproject.toml

            proc = _run_hook(str(unrelated))

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")

    def test_warns_when_a_foreign_entry_is_mixed_with_a_good_one(self) -> None:
        """A correct entry alongside a foreign one is still a hazard.

        Import order decides the winner, so the presence of our own src/ does
        not make the foreign entry harmless.
        """
        with tempfile.TemporaryDirectory() as td:
            foreign = _make_fake_checkout(Path(td, "other-checkout"))
            mixed = os.pathsep.join([str(REPO_ROOT / "src"), str(foreign)])

            proc = _run_hook(mixed)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIn(str(foreign), payload["systemMessage"])

    def test_output_is_a_single_json_object(self) -> None:
        """The hook contract is one JSON object on stdout — not prose."""
        with tempfile.TemporaryDirectory() as td:
            foreign = _make_fake_checkout(Path(td, "other-checkout"))

            proc = _run_hook(str(foreign))

            # json.loads on the whole stream: extra lines or a bare string fail.
            payload = json.loads(proc.stdout)
            self.assertIsInstance(payload, dict)
            self.assertEqual(list(payload.keys()), ["systemMessage"])


if __name__ == "__main__":
    unittest.main()
