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

import re
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

# The summary line every suite ends with, e.g. "statusline: 76 passed, 0 failed, 76 total".
# Parsed rather than merely searched for "ALL PASS" -- see _assert_ran_cases below.
_SUMMARY_RE = re.compile(
    r"^\S+: (?P<passed>\d+) passed, (?P<failed>\d+) failed, (?P<total>\d+) total$",
    re.MULTILINE,
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
        # "ALL PASS" is necessary but NOT sufficient -- see _assert_ran_cases, which
        # checks that cases actually ran and that all of them passed.
        self.assertIn("ALL PASS", proc.stdout, msg=proc.stdout)
        self._assert_ran_cases(name, proc.stdout)

    def _assert_ran_cases(self, name: str, stdout: str) -> None:
        """A suite that ran zero cases has not tested anything.

        ``ALL PASS`` alone is not evidence of a passing run. ``_summary`` prints it
        whenever no case FAILED, and a suite whose cases were all deleted -- or that
        exited before reaching them -- fails nothing. Both counters sit at zero, the
        exit code is 0, and every layer above reports green having exercised not one
        guard. ``_harness.sh`` now refuses that case at the source; this asserts the
        same thing here so the wrapper cannot be satisfied by a suite that silently
        stopped running cases.
        """
        match = _SUMMARY_RE.search(stdout)
        if match is None:
            self.fail(f"{name} printed no parsable summary line:\n{stdout}")
        passed = int(match.group("passed"))
        failed = int(match.group("failed"))
        total = int(match.group("total"))
        self.assertGreater(
            total,
            0,
            msg=f"{name} ran zero cases -- an empty suite is not a passing suite",
        )
        self.assertEqual(
            passed,
            total,
            msg=f"{name} reported {failed} failure(s) of {total}:\n{stdout}",
        )

    def test_each_suite_on_disk_is_listed_and_passes(self) -> None:
        """Every *.test.sh is in SUITES, and every entry in SUITES runs and passes.

        CONSOLIDATED from three hand-written per-suite methods plus a separate
        directory-match test. That arrangement checked the SUITES tuple against disk
        but never ITERATED it: execution came from the three methods, so a suite added
        to the tuple with no matching ``test_*`` method satisfied the equality check
        and was never run. The tuple looked like the source of truth while the method
        list actually was one, and the two could drift silently in the direction that
        loses coverage.

        Driving both the membership check and the execution from SUITES means a name
        can only be in one of three states: absent from the tuple (the directory check
        fails), present and passing, or present and failing. There is no fourth state
        where it is listed and quietly skipped.
        """
        on_disk = {p.name for p in TESTS_DIR.glob("*.test.sh")}
        self.assertEqual(
            on_disk,
            set(SUITES),
            msg="hook suites on disk do not match the SUITES tuple in this file",
        )
        # Guards the guard: an emptied SUITES would make the assertEqual above pass
        # against an emptied directory and run nothing at all.
        self.assertTrue(SUITES, msg="SUITES is empty -- no hook suite would run")

        for name in SUITES:
            with self.subTest(suite=name):
                self._run_suite(name)


if __name__ == "__main__":
    unittest.main()
