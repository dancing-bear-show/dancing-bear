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
    """A decoy checkout of THIS project: src/ plus a matching pyproject.toml."""
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "personal-assistants"\nversion = "0.1.0"\n'
    )
    return root / "src"


def _make_third_party_checkout(root: Path) -> Path:
    """A DIFFERENT project that happens to have src/ and a pyproject.toml.

    This is the case a bare "has a pyproject.toml" heuristic gets wrong: most
    third-party checkouts have one, so matching on its presence alone would warn
    about paths we have no business touching.
    """
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "some-other-lib"\n')
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

    def test_silent_for_a_third_party_checkout_with_its_own_pyproject(self) -> None:
        """A pyproject.toml is not enough — it must name THIS project.

        Most third-party checkouts ship a pyproject.toml, so a presence-only
        marker would warn about unrelated paths and train the reader to ignore
        the warning.
        """
        with tempfile.TemporaryDirectory() as td:
            other = _make_third_party_checkout(Path(td, "some-other-lib"))

            proc = _run_hook(str(other))

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")

    def test_no_interpreter_runs_with_the_foreign_path_still_set(self) -> None:
        """The hook must not start Python while the foreign PYTHONPATH is live.

        Python imports sitecustomize/usercustomize from PYTHONPATH entries during
        startup, so an interpreter launched here would execute code from the very
        checkout being warned about. Planting a sitecustomize.py proves whether
        the hook is exposed.
        """
        with tempfile.TemporaryDirectory() as td:
            foreign = _make_fake_checkout(Path(td, "other-checkout"))
            (foreign / "sitecustomize.py").write_text(
                'import sys; sys.stderr.write("PWNED\\n")\n'
            )

            proc = _run_hook(str(foreign))

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("PWNED", proc.stderr)
            self.assertNotIn("PWNED", proc.stdout)
            # The warning itself must still be emitted.
            self.assertIn("systemMessage", json.loads(proc.stdout))

    def test_every_sessionstart_python_hook_is_interpreter_isolated(self) -> None:
        """No SessionStart hook may start a bare `python3`.

        SessionStart hooks run with the session's environment, which is exactly
        when PYTHONPATH may name a foreign checkout. Python imports
        sitecustomize/usercustomize from PYTHONPATH entries during startup, so a
        bare `python3 -c ...` hook executes code from that checkout before any
        warning is emitted — including before this file's own hook runs.

        Hardening this one shell script was not enough: the pre-existing
        worktree-marker hook is ordered FIRST and launched a bare interpreter,
        so the exposure survived a fix that claimed to close it. `-I` ignores
        PYTHONPATH and the user site directory; `-S` skips site.py, which is what
        imports sitecustomize.
        """
        settings = json.loads(
            (REPO_ROOT / ".claude" / "settings.json").read_text()
        )
        offenders = []
        for group in settings.get("hooks", {}).get("SessionStart", []):
            for hook in group.get("hooks", []):
                cmd = hook.get("command", "")
                if not cmd.startswith("python3"):
                    continue  # shell hooks start no interpreter
                if "-I" not in cmd.split('"')[0] or "-S" not in cmd.split('"')[0]:
                    offenders.append(cmd[:80])

        self.assertEqual(
            offenders,
            [],
            "SessionStart hook(s) start python3 without -I -S, so a "
            "sitecustomize.py on a foreign PYTHONPATH would execute first: "
            f"{offenders}",
        )

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
