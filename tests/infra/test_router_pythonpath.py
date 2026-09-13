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
one.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - runs this repo's own router under a fixed interpreter
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTER = REPO_ROOT / "bin" / "_router.py"


def _make_fake_checkout(root: Path, package: str) -> Path:
    """A decoy checkout of THIS project: matching pyproject.toml plus src/<pkg>/.

    The marker must NAME this project. The router only strips a ``src`` entry
    whose sibling pyproject.toml says ``name = "personal-assistants"``, so an
    unrelated third-party entry — which very likely ships a pyproject.toml of
    its own — is left alone.
    """
    pkg = root / "src" / package
    pkg.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "personal-assistants"\nversion = "0.1.0"\n'
    )
    (pkg / "__init__.py").write_text('ORIGIN = "decoy"\n')
    return root / "src"


def _make_third_party_checkout(root: Path) -> Path:
    """A DIFFERENT project that also has src/ and its own pyproject.toml."""
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "some-other-lib"\n')
    return root / "src"


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
            foreign = _make_fake_checkout(Path(td, "other-checkout"), "mail")

            state = _run_prologue(str(foreign), REPO_ROOT)

            self.assertNotIn(
                str(foreign),
                state["pythonpath"],
                "a sibling checkout's src/ stayed on PYTHONPATH; imports would "
                "resolve to that tree",
            )

    def test_own_src_is_first_on_sys_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            foreign = _make_fake_checkout(Path(td, "other-checkout"), "mail")

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
            foreign = _make_fake_checkout(Path(td, "other-checkout"), "mail")
            # foreign first, ours second — the ordering that defeated the old guard
            combined = os.pathsep.join([str(foreign), str(REPO_ROOT / "src")])

            state = _run_prologue(combined, REPO_ROOT)

            self.assertEqual(state["sys_path0"], str(REPO_ROOT / "src"))
            self.assertNotIn(str(foreign), state["pythonpath"])

    def test_unrelated_pythonpath_entries_are_preserved(self) -> None:
        """Only checkouts of THIS project are stripped.

        A ``src`` directory with no sibling ``pyproject.toml`` belongs to some
        other setup; removing it would break things the router knows nothing
        about.
        """
        with tempfile.TemporaryDirectory() as td:
            unrelated = Path(td, "some-lib", "src")
            unrelated.mkdir(parents=True)  # deliberately NO pyproject.toml

            state = _run_prologue(str(unrelated), REPO_ROOT)

            self.assertIn(
                str(unrelated),
                state["pythonpath"],
                "an unrelated src/ was stripped; the check must require a "
                "sibling pyproject.toml",
            )

    def test_third_party_checkout_with_its_own_pyproject_is_preserved(self) -> None:
        """A pyproject.toml is not the marker — one naming THIS project is.

        Most third-party checkouts ship a pyproject.toml. Stripping on its mere
        presence would silently remove entries the router has no business
        touching and break setups it knows nothing about.
        """
        with tempfile.TemporaryDirectory() as td:
            other = _make_third_party_checkout(Path(td, "some-other-lib"))

            state = _run_prologue(str(other), REPO_ROOT)

            self.assertIn(
                str(other),
                state["pythonpath"],
                "a third-party src/ was stripped; the marker must name this "
                "project, not merely be a pyproject.toml",
            )

    def test_empty_pythonpath_is_left_alone(self) -> None:
        state = _run_prologue("", REPO_ROOT)

        self.assertEqual(state["pythonpath"], "")
        self.assertEqual(state["sys_path0"], str(REPO_ROOT / "src"))


if __name__ == "__main__":
    unittest.main()
