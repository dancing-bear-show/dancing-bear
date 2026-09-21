"""The router must not import from another checkout of this repo.

`.envrc` exports ``PYTHONPATH="$PWD/src"``, and direnv loads the ``.envrc`` of
whichever checkout the shell started in. Start a shell in the main checkout,
move into ``.claude/worktrees/<wt>``, and ``PYTHONPATH`` still names the MAIN
``src/``: the worktree's ``.envrc`` is a different file and is not on direnv's
allow list. A ``PYTHONPATH`` entry also outranks the editable install's
``.pth``, so even the worktree's own ``.venv`` interpreter resolves
``mail``/``resume``/``core`` to the other tree.

The failure mode is silence. The command runs, exits 0, and reports behaviour
from source nobody is editing; a suite passes against unmodified code. These
tests pin the repair in ``bin/_router.py`` so it cannot regress into a no-op.

Each test builds a throwaway fake checkout on disk rather than pointing at a
real sibling worktree, so it does not depend on the developer's machine having
one. Those builders live in ``tests/infra/pathrepair_fixtures.py`` because
``test_pathrepair_shared.py`` needs the identical decoy shape — two copies could
drift so that one suite tested the old marker and the other the new.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - runs this repo's own router under a fixed interpreter
import sys
import tempfile
import unittest
from pathlib import Path

from tests.infra.pathrepair_fixtures import (
    make_fake_checkout,
    make_third_party_checkout,
    make_unmarked_src,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTER = REPO_ROOT / "bin" / "_router.py"


def _run_prologue(pythonpath: str, cwd: Path) -> dict[str, str]:
    """Execute the router's path-fixing prologue and report the resulting state.

    Only the prologue is executed (everything before the generated dispatch
    section), because the dispatch would try to run a CLI.
    """
    probe = (
        "import os, sys, json\n"
        f"src = open({str(ROUTER)!r}).read()\n"
        'prologue = src.split("# --- BEGIN GENERATED SECTION")[0]\n'
        f'ns = {{"__file__": {str(ROUTER)!r}, "__name__": "_router_under_test"}}\n'
        'exec(compile(prologue, "_router.py", "exec"), ns)\n'
        "print(json.dumps({\n"
        '    "pythonpath": os.environ.get("PYTHONPATH", ""),\n'
        '    "sys_path0": sys.path[0],\n'
        "}))\n"
    )
    env = {**os.environ, "PYTHONPATH": pythonpath}
    proc = subprocess.run(  # nosec B603 - fixed interpreter, no shell, no user input
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        # Bounded so a stalled interpreter fails this one test instead of
        # hanging the whole suite. The probe only parses a file and prints JSON,
        # so 60s is generous even on a loaded machine.
        timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(f"router prologue failed: {proc.stderr}")
    import json as _json

    return _json.loads(proc.stdout.strip().splitlines()[-1])


class TestRouterStripsForeignCheckouts(unittest.TestCase):
    """A sibling checkout's src/ must never survive on the import path."""

    def test_foreign_repo_src_is_removed_from_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            foreign = make_fake_checkout(Path(td, "other-checkout"), "mail")

            state = _run_prologue(str(foreign), REPO_ROOT)

            self.assertNotIn(
                str(foreign),
                state["pythonpath"],
                "a sibling checkout's src/ stayed on PYTHONPATH; imports would "
                "resolve to that tree",
            )

    def test_own_src_is_first_on_sys_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            foreign = make_fake_checkout(Path(td, "other-checkout"), "mail")

            state = _run_prologue(str(foreign), REPO_ROOT)

            self.assertEqual(
                state["sys_path0"],
                str(REPO_ROOT / "src"),
                "this checkout's src/ must be first, not merely present — an "
                "entry behind a foreign one loses the import race silently",
            )

    def test_own_src_wins_even_when_already_present_but_later(self) -> None:
        """The bug the original guard had: membership checked, order ignored.

        ``if str(SRC_ROOT) not in sys.path`` did nothing when our src/ was on
        the path but sat *behind* a foreign entry, so the foreign tree still won.
        """
        with tempfile.TemporaryDirectory() as td:
            foreign = make_fake_checkout(Path(td, "other-checkout"), "mail")
            # foreign first, ours second — the ordering that defeated the old guard
            combined = os.pathsep.join([str(foreign), str(REPO_ROOT / "src")])

            state = _run_prologue(combined, REPO_ROOT)

            self.assertEqual(state["sys_path0"], str(REPO_ROOT / "src"))
            self.assertNotIn(str(foreign), state["pythonpath"])

    def test_entries_that_are_not_this_project_are_preserved(self) -> None:
        """Only checkouts of THIS project are stripped — nothing else.

        Two ways an entry can fail to be ours, both of which must survive:

        * a third-party checkout that ships its own pyproject.toml — most do,
          so a pyproject.toml is not the marker; one NAMING this project is;
        * a bare ``src`` directory with no sibling pyproject.toml at all.

        Removing either would break setups the router knows nothing about.
        """
        cases = (
            ("third-party checkout", make_third_party_checkout, "some-other-lib"),
            ("src without pyproject", make_unmarked_src, "some-lib"),
        )
        for label, build, dirname in cases:
            with (
                self.subTest(case=label),
                tempfile.TemporaryDirectory() as td,
            ):
                entry = build(Path(td, dirname))

                state = _run_prologue(str(entry), REPO_ROOT)

                self.assertIn(
                    str(entry),
                    state["pythonpath"],
                    f"a {label} was stripped; only a src/ beside a "
                    "pyproject.toml NAMING this project is ours",
                )

    def test_empty_pythonpath_is_left_alone(self) -> None:
        state = _run_prologue("", REPO_ROOT)

        self.assertEqual(state["pythonpath"], "")
        self.assertEqual(state["sys_path0"], str(REPO_ROOT / "src"))


if __name__ == "__main__":
    unittest.main()
