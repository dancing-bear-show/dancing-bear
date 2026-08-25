"""Run the .claude/hooks shell suites under unittest discovery.

WHY THIS WRAPPER EXISTS
-----------------------
The guard-hook suites are shell scripts. They were documented as manual commands
only, so `make test` and CI -- both of which run Python unittest discovery and
nothing else -- never invoked them. A regression in a hook that blocks credential
reads would therefore ship green, which is the one class of regression these
hooks exist to prevent.

Shelling out from a discovered test is the smallest change that fixes that: no new
Makefile target to remember, no second CI step to keep in sync with the first, and
the suites stay runnable by hand exactly as the README documents. `make test`,
`make cov`, and `.github/workflows/ci.yml` all pick this up automatically because
all three go through discovery.

The suites are self-contained bash and require only `jq`. When `jq` or `bash` is
missing the test FAILS.

WHY FAIL RATHER THAN SKIP
-------------------------
This used to call ``skipTest``, on the reasoning that a missing tool is an unknown
result rather than a passing one. That reasoning is right about the result and wrong
about the consequence: unittest reports a skipped test as a green run, CI goes green,
and nobody reads the skip line. A runner without ``jq`` would therefore report success
having exercised not one guard -- the precise fail-open shape that both hooks and the
``_harness.sh`` classifier were rewritten to eliminate, reproduced one level up in the
thing that runs them.

A tool these tests require is a dependency, not an environmental accident. ``jq`` is
installed explicitly in ``.github/workflows/ci.yml`` so that failing here is safe:
if it ever goes missing, the correct signal is a red build naming the missing tool,
not a silent pass.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - runs trusted in-repo shell suites
import unittest
from pathlib import Path

from tests.fixtures import repo_root

HOOKS_DIR = repo_root() / ".claude" / "hooks"
TESTS_DIR = HOOKS_DIR / "tests"

# Each suite exits 0 on all-pass and 1 on any failure, and prints one line per case.
SUITES = (
    "block-destructive-bash.test.sh",
    "block-protected-paths.test.sh",
    "statusline.test.sh",
)


def _missing_tool() -> str | None:
    """Return the name of the first required tool that is not on PATH."""
    for tool in ("bash", "jq"):
        if shutil.which(tool) is None:
            return tool
    return None


class TestGuardHookSuites(unittest.TestCase):
    """Each .claude/hooks shell suite must exit 0."""

    def _run_suite(self, name: str) -> None:
        missing = _missing_tool()
        self.assertIsNone(
            missing,
            msg=(
                f"{missing} is not on PATH, so the guard-hook suites cannot run. "
                "This is a failure, not a skip: a skipped run reports green while "
                "exercising none of the guards, which is exactly the fail-open "
                "behaviour these hooks exist to prevent. Install it "
                "(macOS: brew install jq) -- CI installs it in ci.yml."
            ),
        )

        suite: Path = TESTS_DIR / name
        self.assertTrue(suite.is_file(), f"missing hook suite: {suite}")

        # encoding/errors are pinned rather than left to the locale. statusline.sh
        # emits box-drawing and middle-dot characters, and text=True alone decodes
        # with the locale's preferred encoding -- ASCII on a CI runner with no
        # LANG set, which raises UnicodeDecodeError on the first '·' and turns a
        # passing suite into an error. errors="replace" keeps a decoding problem
        # from masking the assertion the test actually makes.
        # B607: "bash" is resolved from PATH deliberately. /bin/bash does not exist
        # on NixOS, and the Linux CI runner and macOS dev machines put it in
        # different places. Anyone who can alter PATH for this process can already
        # edit the test file, so the partial path adds no new exposure. The nosec
        # must stay on the flagged line below -- bandit ignores it on a preceding
        # comment line, exactly like NOSONAR.
        proc = subprocess.run(  # nosec B603 B607 - trusted in-repo script, no user input
            ["bash", str(suite)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(repo_root()),
            timeout=180,
        )
        # The suite's own output is the useful failure message: it names every case
        # that failed and what it expected. Reproducing that in assert messages would
        # duplicate it and then drift.
        self.assertEqual(
            proc.returncode,
            0,
            msg=f"\n--- {name} ---\n{proc.stdout}\n{proc.stderr}",
        )
        # An empty run is not a passing run. A suite whose cases were all deleted, or
        # that exited before running anything, exits 0 and would otherwise read as
        # green -- the same fail-open shape the suites themselves guard against.
        self.assertIn("ALL PASS", proc.stdout, msg=proc.stdout)

    def test_block_destructive_bash_suite(self) -> None:
        """Bash guard: credential reads/writes, rm -rf targets, malformed payloads."""
        self._run_suite("block-destructive-bash.test.sh")

    def test_block_protected_paths_suite(self) -> None:
        """Write/Edit guard: credential paths, .git/, key material, templates."""
        self._run_suite("block-protected-paths.test.sh")

    def test_statusline_suite(self) -> None:
        """Statusline: unknown-vs-zero context, thresholds, prefix precedence."""
        self._run_suite("statusline.test.sh")

    def test_every_suite_in_the_directory_is_wired_in(self) -> None:
        """A new *.test.sh must be added to SUITES, not left unrun.

        The failure this prevents is the one that made this wrapper necessary in the
        first place: a suite that exists, passes when run by hand, and is never
        invoked by anything automated.
        """
        on_disk = {p.name for p in TESTS_DIR.glob("*.test.sh")}
        self.assertEqual(
            on_disk,
            set(SUITES),
            msg="hook suites on disk do not match the SUITES tuple in this file",
        )


if __name__ == "__main__":
    unittest.main()
