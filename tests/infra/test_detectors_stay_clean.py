"""Run the repo's static detectors and fail when they report a finding.

WHY THIS EXISTS
---------------
``workflows/code/scripts/`` holds AST detectors that nothing invoked. A
detector nobody runs is a detector whose finding count is never observed, so a
regression that reintroduces what it detects lands silently -- and so does a
change that quietly breaks the detector itself into reporting zero. That is the
same false-clean hazard these tools were written to work around.

Shelling out from a discovered test is the smallest thing that fixes it, and
follows ``test_guard_hooks.py``: no new Makefile target to remember and no
second CI step to keep in sync, because ``make test``, ``make cov`` and
``.github/workflows/ci.yml`` all go through discovery.

WHY FAIL RATHER THAN SKIP
-------------------------
Same reasoning as the guard-hook suites. unittest reports a skip as a green
run, so a detector that could not execute would look identical to one that
found nothing. A detector that cannot run is an unknown result, and an unknown
result must not be reported as success.

WHY THE PROBE
-------------
``total_findings == 0`` is only meaningful if the detector still detects. A
resolver bug, a renamed directory, or an inverted condition all produce a
confident zero. ``test_detector_still_detects`` injects a known violation into
a temporary tree and requires the detector to report it, so a broken detector
fails here rather than going quietly green forever.

Detectors that report ranked *suspicions* rather than defects are deliberately
NOT gated on a zero count -- see ``_ZERO_FINDING_DETECTORS`` below.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404 - runs a trusted in-repo script, no user input
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


#: Detectors whose finding count must stay at zero.
#:
#: Only detect_arg_type_mismatch qualifies today. Its findings are concrete
#: type mismatches, so a non-zero count is a real regression. detect_facades
#: and detect_unadopted deliberately emit ranked suspicions ("Read before
#: acting"), and gating CI on those would fail the build for findings a human
#: is expected to triage rather than fix.
_ZERO_FINDING_DETECTORS = ("detect_arg_type_mismatch.py",)

_SCRIPTS = repo_root() / "workflows" / "code" / "scripts"


def _run_detector(script: Path, *args: str, cwd: Path | None = None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root() / "src")
    # B603: fixed in-repo script path and a fixed interpreter; no shell, and
    # nothing here comes from user input. The nosec must sit on the flagged
    # line, not a preceding comment.
    return subprocess.run(  # nosec B603 - trusted in-repo script, no user input
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd or repo_root()),
        env=env,
        timeout=300,
    )


class DetectorsStayCleanTests(unittest.TestCase):
    """The zero-finding detectors must keep reporting zero."""

    def test_scripts_exist(self) -> None:
        """A renamed or deleted detector must fail here, not vanish silently."""
        for name in _ZERO_FINDING_DETECTORS:
            with self.subTest(detector=name):
                self.assertTrue(
                    (_SCRIPTS / name).is_file(),
                    msg=f"{name} is gated by this test but no longer exists",
                )

    def test_no_findings(self) -> None:
        for name in _ZERO_FINDING_DETECTORS:
            with self.subTest(detector=name):
                proc = _run_detector(_SCRIPTS / name)
                # Exit 2 is the detector's own "I scanned nothing" guard. Treat
                # it as a failure with its stderr attached rather than parsing
                # a payload that the detector already called untrustworthy.
                self.assertEqual(
                    proc.returncode,
                    0,
                    msg=f"\n--- {name} ---\n{proc.stdout}\n{proc.stderr}",
                )
                payload = json.loads(proc.stdout)
                self.assertFalse(
                    payload["scanned_nothing"],
                    msg=f"{name} scanned nothing: {payload['stats']}",
                )
                self.assertEqual(
                    payload["total_findings"],
                    0,
                    msg=(
                        f"\n--- {name} reported findings ---\n"
                        + json.dumps(payload["findings"], indent=2)
                    ),
                )

    def test_detector_still_detects(self) -> None:
        """A known violation must be reported.

        Guards the assertion above: zero findings only means the tree is clean
        if the detector still works. Without this, a resolver that silently
        stopped matching would keep this suite green forever.
        """
        src = "def greet(name: str) -> str:\n    return name\n"
        call = "from probe_mod.helpers import greet\n\ndef test_probe():\n    greet(None)\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src_dir = root / "src" / "probe_mod"
            test_dir = root / "tests"
            src_dir.mkdir(parents=True)
            test_dir.mkdir(parents=True)
            (src_dir / "helpers.py").write_text(textwrap.dedent(src))
            (test_dir / "test_probe.py").write_text(textwrap.dedent(call))

            proc = _run_detector(
                _SCRIPTS / "detect_arg_type_mismatch.py",
                str(src_dir.parent),
                str(test_dir),
            )

        self.assertEqual(
            proc.returncode, 0, msg=f"{proc.stdout}\n{proc.stderr}"
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(
            payload["total_findings"],
            1,
            msg=(
                "detector did not report the injected violation; a zero count "
                "elsewhere in this suite cannot be trusted\n"
                + json.dumps(payload, indent=2)
            ),
        )
        finding = payload["findings"][0]
        self.assertEqual(finding["callee"], "greet")
        self.assertEqual(finding["param"], "name")


if __name__ == "__main__":
    unittest.main()
