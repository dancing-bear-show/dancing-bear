"""``bin/bootstrap``'s verify step must describe THIS checkout.

The import-path repair in ``bin/_pathrepair.py`` covers every Python entry
point under ``bin/``. ``bin/bootstrap`` is **bash**, so a sweep looking for
Python ``sys.path`` guards skipped it — and its verify step is the one place
where importing from the wrong tree is actively misleading rather than merely
wrong. It prints "Core modules import successfully" as the final word on an
install; sourced from a foreign checkout, that line vouches for a tree the
script never touched.

The hazard is the usual one: ``.envrc`` exports ``PYTHONPATH="$PWD/src"`` and
direnv follows the shell rather than the directory, so running bootstrap in a
worktree leaves PYTHONPATH naming the main checkout's ``src/`` — which outranks
the editable install's ``.pth`` that bootstrap just created.

Only the single verify invocation is exercised here. Running ``bin/bootstrap``
itself would install Homebrew, build a venv and pip-install the project.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess  # nosec B404 - replays this repo's own bootstrap line
import sys
import tempfile
import unittest
from pathlib import Path

from tests.infra.pathrepair_fixtures import make_fake_checkout

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "bin" / "bootstrap"

#: The modules bootstrap's verify step imports.
VERIFY_MODULES = ("mail", "calendars", "resume", "core")

#: Splits the verify line into the parts the end-to-end replay may and may not
#: touch. ``env`` is everything between ``if`` and the interpreter: the
#: environment prefix that decides the import race, which is the thing under
#: test and is replayed verbatim. It is allowed to match empty, so an unpinned
#: line still parses and still runs — that is what gives the replay its teeth.
#: ``interp`` is the venv interpreter, the only token substituted.
_VERIFY_LINE_RE = re.compile(
    r"^if\s+(?P<env>.*?)(?P<interp>\S*\.venv/bin/python)\s+-c\s+"
    r"\"(?P<body>[^\"]*)\"(?P<tail>.*?);\s*then\s*$"
)

#: Replacement ``-c`` body: reports where each verified module resolved, as
#: JSON, so a failure names the offending tree instead of only an exit status.
_ORIGIN_REPORTER = (
    "import json, importlib;"
    "print(json.dumps({m: getattr(importlib.import_module(m), '__file__', '')"
    f" for m in {list(VERIFY_MODULES)!r}}}))"
)


def _verify_line() -> str:
    """Return bootstrap's verify command, read from the script itself.

    Read rather than duplicated: a copy in the test would keep passing after
    someone edited the script, which is precisely the regression this guards.
    """
    for line in BOOTSTRAP.read_text(encoding="utf-8").splitlines():
        if "import mail" in line and "-c" in line:
            return line.strip()
    raise AssertionError(f"no verify line found in {BOOTSTRAP}")


def _replayable_verify_command(interpreter: str) -> str:
    """Rebuild bootstrap's verify command so a test can execute it.

    Exactly two substitutions are made, and no others:

    * the ``.venv/bin/python`` interpreter, because a worktree that has not run
      ``make venv`` has no venv to invoke;
    * the ``-c`` body, replaced by :data:`_ORIGIN_REPORTER` so the caller can
      read back where each module resolved.

    The environment prefix is spliced through untouched — substituting it, or
    reconstructing it from what the test *expects* bootstrap to contain, is how
    the previous version of this test came to pass against a bootstrap with no
    pin at all. ``2>/dev/null`` is dropped so a failure stays diagnosable.
    """
    line = _verify_line()
    match = _VERIFY_LINE_RE.match(line)
    if match is None:
        raise AssertionError(f"verify line no longer parses: {line!r}")
    return (
        f"{match.group('env')}{shlex.quote(interpreter)} "
        f"-c {shlex.quote(_ORIGIN_REPORTER)}"
    )


class BootstrapVerifyStepTests(unittest.TestCase):
    """The verify step resolves modules from the checkout being bootstrapped."""

    def test_verify_line_pins_pythonpath_to_its_own_src(self) -> None:
        """The command must set PYTHONPATH rather than inherit it."""
        line = _verify_line()
        self.assertRegex(
            line,
            r'PYTHONPATH="\$\(pwd\)/src"',
            "bootstrap's verify step does not pin PYTHONPATH, so an inherited "
            "one naming another checkout of this repo wins the import race "
            f"and it verifies the wrong tree: {line!r}",
        )

    def test_verify_imports_resolve_to_this_checkout(self) -> None:
        """End-to-end: a foreign PYTHONPATH must not capture the verify step.

        Executes the verify command **as bootstrap writes it** — environment
        prefix and all, parsed out of the script — through a shell, with a
        decoy checkout as the sole ``PYTHONPATH`` entry and ``cwd`` at the repo
        root (the pin is ``$(pwd)/src``, so the cwd is load-bearing).

        Nothing here pre-seeds this checkout's ``src`` onto the path. If
        bootstrap's line carries the pin, the pin is what wins; if the pin were
        deleted, the decoy wins and this fails.
        """
        command = _replayable_verify_command(sys.executable)

        with tempfile.TemporaryDirectory() as td:
            decoy_src = make_fake_checkout(Path(td, "other-checkout"), package="mail")

            proc = subprocess.run(  # nosec B603 B607 - replays the repo's own line
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                env={**os.environ, "PYTHONPATH": str(decoy_src)},
                timeout=120,
            )

            self.assertEqual(
                proc.returncode,
                0,
                f"verify command {command!r} failed:\n{proc.stderr}",
            )
            origins = json.loads(proc.stdout)
            self.assertEqual(sorted(origins), sorted(VERIFY_MODULES))
            for module, origin in origins.items():
                self.assertTrue(
                    origin.startswith(str(REPO_ROOT) + os.sep),
                    f"{module} resolved to {origin!r}, outside this checkout "
                    f"({REPO_ROOT}) — the verify step is describing another "
                    f"tree. Command replayed from bin/bootstrap: {command!r}",
                )

    def test_unpinned_verify_would_import_the_decoy(self) -> None:
        """Proves the decoy genuinely shadows, so the test above has teeth.

        Without this, a decoy that could never win would make
        ``test_verify_imports_resolve_to_this_checkout`` pass vacuously.
        """
        with tempfile.TemporaryDirectory() as td:
            decoy_src = make_fake_checkout(Path(td, "other-checkout"), package="mail")
            proc = subprocess.run(  # nosec B603 - fixed argv, repo's own interpreter
                [sys.executable, "-c", "import mail; print(mail.__file__)"],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                env={**os.environ, "PYTHONPATH": str(decoy_src)},
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn(
                str(decoy_src),
                proc.stdout,
                "the decoy did not shadow the real package, so the pinned "
                "assertion above proves nothing",
            )

    def test_pip_lines_are_left_unpinned(self) -> None:
        """`pip install` lines need no pin, and must not acquire one by cargo cult.

        pip resolves from the venv it is invoked out of, not from PYTHONPATH,
        so these carry none of the hazard. Pinning them anyway would suggest
        the risk is broader than it is and invite the same edit elsewhere.
        """
        text = BOOTSTRAP.read_text(encoding="utf-8")
        pip_lines = [
            ln.strip()
            for ln in text.splitlines()
            if re.search(r"\.venv/bin/python -m pip", ln)
        ]
        self.assertTrue(pip_lines, "no pip lines found — did bootstrap change?")
        for line in pip_lines:
            self.assertNotIn(
                "PYTHONPATH=",
                line,
                f"pip line carries an unnecessary PYTHONPATH pin: {line!r}",
            )


if __name__ == "__main__":
    unittest.main()
