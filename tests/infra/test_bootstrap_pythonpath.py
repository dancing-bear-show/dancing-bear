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

# The ONLY environment prefix this test will hand to `bash -c`.
#
# The env group above is deliberately permissive so an unpinned line still
# parses; this constant is the separate gate deciding what may execute. Exact
# equality rather than a pattern: bin/bootstrap is branch-controlled, and an
# allowlist regex is a standing invitation to widen it by one metacharacter
# until something chains a command. There is exactly one correct value, so
# compare against it.
_EXPECTED_ENV_PREFIX = 'PYTHONPATH="$(pwd)/src"'

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

    The environment prefix is read from the script rather than reconstructed
    from what the test *expects* to find — rebuilding it is how an earlier
    version of this test came to pass against a bootstrap with no pin at all.
    ``2>/dev/null`` is dropped so a failure stays diagnosable.

    But read is not the same as trusted. ``bin/bootstrap`` is branch-controlled,
    and this prefix is interpolated into ``bash -c``: a PR that changed the line
    to ``touch /tmp/x; PYTHONPATH=...`` would have its command run with CI
    privileges. Demonstrated before this guard existed — the injected ``touch``
    fired and the test still reported OK, which is the worst pairing available.

    So the prefix must equal :data:`_EXPECTED_ENV_PREFIX` exactly before it is
    executed; anything else fails the test instead of running. An empty prefix
    is the one exception — that is an unpinned bootstrap, the regression this
    suite exists to catch, so it is replayed and left to fail on the import
    result where the message can name the tree that won.
    """
    line = _verify_line()
    match = _VERIFY_LINE_RE.match(line)
    if match is None:
        raise AssertionError(f"verify line no longer parses: {line!r}")
    env_prefix = match.group("env").strip()
    if not env_prefix:
        # An unpinned bootstrap. Not hostile — it is the regression this suite
        # exists to catch, so let it through and let the import result report
        # it. Erroring here instead would turn "bootstrap lost its pin" into an
        # opaque prefix complaint that never names the tree that won.
        return f"{shlex.quote(interpreter)} -c {shlex.quote(_ORIGIN_REPORTER)}"
    if env_prefix != _EXPECTED_ENV_PREFIX:
        raise AssertionError(
            "bootstrap's verify line carries an environment prefix this test "
            f"will not execute: {env_prefix!r}. Expected exactly "
            f"{_EXPECTED_ENV_PREFIX!r}. If the line legitimately changed, "
            "update _EXPECTED_ENV_PREFIX deliberately — never relax it to make "
            "a test pass, since this text is interpolated into `bash -c`."
        )
    return (
        f"{env_prefix} {shlex.quote(interpreter)} "
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


class EnvPrefixIsNotAnExecutionSinkTests(unittest.TestCase):
    """A tampered bootstrap line must fail the test, not run in CI.

    This suite reads ``bin/bootstrap`` — a tracked, branch-controlled file —
    and interpolates part of it into ``bash -c``. Without a gate on that text,
    a PR could append a command to the environment prefix and have the test
    suite execute it with CI privileges. That was demonstrated: an injected
    ``touch`` fired *and the test still reported OK*.
    """

    def _replay_with_verify_line(self, line: str) -> str:
        """Run the real builder against a substituted verify line."""
        original = BOOTSTRAP.read_text(encoding="utf-8")
        patched = original.replace(_verify_line(), line)
        self.assertNotEqual(patched, original, "substitution did not apply")
        BOOTSTRAP.write_text(patched, encoding="utf-8")
        try:
            return _replayable_verify_command(sys.executable)
        finally:
            BOOTSTRAP.write_text(original, encoding="utf-8")

    def test_the_shipped_prefix_is_accepted(self) -> None:
        """The guard must not reject what bootstrap actually ships."""
        command = _replayable_verify_command(sys.executable)
        self.assertIn(_EXPECTED_ENV_PREFIX, command)

    def test_injected_commands_are_rejected(self) -> None:
        """Each of these would otherwise run in CI with the suite's privileges."""
        for hostile in [
            'if touch /tmp/pwned; PYTHONPATH="$(pwd)/src" '
            '.venv/bin/python -c "import mail" 2>/dev/null; then',
            'if PYTHONPATH="$(pwd)/src" && touch /tmp/pwned '
            '.venv/bin/python -c "import mail" 2>/dev/null; then',
            'if PYTHONPATH="$(cat /etc/passwd)" '
            '.venv/bin/python -c "import mail" 2>/dev/null; then',
            'if PYTHONPATH="`id`" '
            '.venv/bin/python -c "import mail" 2>/dev/null; then',
        ]:
            with self.subTest(line=hostile):
                with self.assertRaises(AssertionError) as caught:
                    self._replay_with_verify_line(hostile)
                self.assertIn("will not execute", str(caught.exception))

    def test_an_unpinned_line_still_reaches_the_import_assertion(self) -> None:
        """An empty prefix is not hostile — it is the bug under test.

        Erroring on it would turn "bootstrap lost its pin" into an opaque
        prefix complaint that never names the tree that won the import race.
        """
        command = self._replay_with_verify_line(
            'if .venv/bin/python -c "import mail" 2>/dev/null; then'
        )
        self.assertNotIn("PYTHONPATH", command)
        self.assertIn("-c", command)


if __name__ == "__main__":
    unittest.main()
