"""The standalone bin/ scripts must not import from another checkout of this repo.

``bin/_router.py`` backs every *generated* wrapper (bin/mail, bin/workflow, ...)
as a symlink, and ``tests/infra/test_router_pythonpath.py`` pins its repair.
``bin/llm`` and ``bin/path-guard`` are NOT symlinks — they are standalone
scripts with their own preamble, and they were missed by that fix. With another
checkout of this repo ahead of ours on ``PYTHONPATH`` they raised
``ModuleNotFoundError: No module named 'core.llm_cli'`` / ``'core.path_guard'``.

A crash is the lucky outcome. Against a real sibling checkout — which does have
``core.llm_cli`` — both would have imported and run the OTHER tree's code
silently, exiting 0 while reporting behaviour from source nobody is editing.

All three entry points now share ``bin/_pathrepair.py`` rather than carrying
three divergent copies of security-critical path logic. These tests exercise the
scripts as executed programs, so they pin the real preamble (including its
ordering relative to the ``.venv`` re-exec), not a reimplementation of it.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404 - runs this repo's own bin/ scripts, fixed argv
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from tests.infra.pathrepair_fixtures import (
    make_fake_checkout,
    make_third_party_checkout,
    make_unmarked_src,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "bin"
PATHREPAIR = BIN_DIR / "_pathrepair.py"
OWN_SRC = str(REPO_ROOT / "src")

#: The standalone (non-symlink) scripts this suite covers, with the module each
#: imports from ``core`` — the import that failed before the fix.
STANDALONE_SCRIPTS = (
    ("llm", "core.llm_cli"),
    ("path-guard", "core.path_guard"),
)


@dataclass(frozen=True)
class PreambleState:
    """Import-path state observed after a script's preamble has executed."""

    pythonpath: str
    sys_path: list[str]

    @property
    def sys_path0(self) -> str:
        """The winning entry — what an ambiguous module name resolves against."""
        return self.sys_path[0]


def _run_preamble(script: str, pythonpath: str) -> PreambleState:
    """Execute a standalone script's preamble and report the resulting state.

    The script is executed up to (but not including) its first ``from core.…``
    import, because completing that import would run a CLI. Everything under
    test — the foreign-path strip, the ``.venv`` re-exec guard, and the
    ``sys.path`` precedence fix — lives in that preamble.

    Running the real file, rather than restating its logic here, is what makes
    this a regression test: reverting the fix in ``bin/llm`` must fail it.
    """
    path = BIN_DIR / script
    probe = (
        "import os, sys, json\n"
        f"src = open({str(path)!r}).read()\n"
        # Cut at the first repo import; keep everything above it.
        'head = src.split("\\nfrom core.")[0]\n'
        f'ns = {{"__file__": {str(path)!r}, "__name__": "_preamble_under_test"}}\n'
        'exec(compile(head, "preamble", "exec"), ns)\n'
        "print(json.dumps({\n"
        '    "pythonpath": os.environ.get("PYTHONPATH", ""),\n'
        '    "sys_path": sys.path,\n'
        "}))\n"
    )
    env = {**os.environ, "PYTHONPATH": pythonpath}
    proc = subprocess.run(  # nosec B603 - fixed interpreter, no shell, no user input
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        # Bounded so a stalled interpreter fails this one test instead of
        # hanging the whole suite.
        timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(f"{script} preamble failed: {proc.stderr}")
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return PreambleState(
        pythonpath=payload["pythonpath"], sys_path=list(payload["sys_path"])
    )


class TestStandaloneScriptsStripForeignCheckouts(unittest.TestCase):
    """bin/llm and bin/path-guard must repair the path like the router does."""

    def test_foreign_ahead_of_ours_loses_the_import_race(self) -> None:
        """The actual bug: foreign entry ORDERED BEFORE ours.

        This is the case with teeth. A foreign entry on an otherwise-empty
        PYTHONPATH passes even against the OLD broken guard, because
        ``if str(SRC_ROOT) not in sys.path`` did insert our src/ when it was
        genuinely absent. The guard only failed when our src/ was already
        present but sat BEHIND the foreign one — then the membership test was
        satisfied, nothing was inserted, and the foreign tree kept winning.
        """
        for script, _module in STANDALONE_SCRIPTS:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as td:
                foreign = make_fake_checkout(Path(td, "other-checkout"))
                # foreign FIRST, ours second — the ordering that defeated the
                # old guard and produced ModuleNotFoundError in practice.
                combined = os.pathsep.join([str(foreign), OWN_SRC])

                state = _run_preamble(script, combined)

                self.assertEqual(
                    state.sys_path0,
                    OWN_SRC,
                    f"bin/{script}: this checkout's src/ must be FIRST, not "
                    "merely present — an entry behind a foreign one loses the "
                    "import race silently",
                )
                self.assertNotIn(
                    str(foreign),
                    state.pythonpath,
                    f"bin/{script}: the foreign src/ stayed on PYTHONPATH, so a "
                    "re-exec or child process would still resolve to that tree",
                )
                self.assertNotIn(
                    str(foreign),
                    state.sys_path,
                    f"bin/{script}: the foreign src/ stayed on sys.path; "
                    "rewriting the environment alone does not help a process "
                    "that does not re-exec",
                )

    def test_foreign_entry_actually_shadows_core_without_the_fix(self) -> None:
        """Pin that the decoy is a real threat, not an inert fixture.

        Without the repair, the decoy checkout's ``core`` package is what
        ``import core`` resolves to. If this ever stops being true the tests
        above would still pass while testing nothing, so assert it directly.
        """
        with tempfile.TemporaryDirectory() as td:
            foreign = make_fake_checkout(Path(td, "other-checkout"))
            env = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join([str(foreign), OWN_SRC]),
            }
            proc = subprocess.run(  # nosec B603 - fixed interpreter, no shell
                [sys.executable, "-c", "import core; print(core.__file__)"],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                env=env,
                timeout=60,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(
                proc.stdout.strip().startswith(str(foreign)),
                "the decoy no longer shadows `core`, so the ordering tests "
                f"above would pass vacuously; resolved to {proc.stdout.strip()!r}",
            )

    def test_entries_that_are_not_this_project_are_preserved(self) -> None:
        """Only checkouts of THIS project are stripped — nothing else.

        Two ways an entry can fail to be ours, both of which must survive:

        * a third-party checkout that ships its own pyproject.toml — most do,
          so stripping on its mere presence would silently remove entries these
          scripts have no business touching;
        * a bare ``src`` directory with no sibling pyproject.toml at all.
        """
        cases = (
            ("third-party checkout", make_third_party_checkout, "some-other-lib"),
            ("src without pyproject", make_unmarked_src, "some-lib"),
        )
        for script, _module in STANDALONE_SCRIPTS:
            for label, build, dirname in cases:
                with (
                    self.subTest(script=script, case=label),
                    tempfile.TemporaryDirectory() as td,
                ):
                    entry = build(Path(td, dirname))

                    state = _run_preamble(
                        script, os.pathsep.join([str(entry), OWN_SRC])
                    )

                    self.assertIn(
                        str(entry),
                        state.pythonpath,
                        f"bin/{script}: a {label} was stripped; only a src/ "
                        "beside a pyproject.toml NAMING this project is ours",
                    )

    def test_empty_pythonpath_is_left_alone(self) -> None:
        """No PYTHONPATH means nothing to repair — but ours still goes first."""
        for script, _module in STANDALONE_SCRIPTS:
            with self.subTest(script=script):
                state = _run_preamble(script, "")

                self.assertEqual(
                    state.pythonpath,
                    "",
                    f"bin/{script}: an empty PYTHONPATH must not be rewritten",
                )
                self.assertEqual(state.sys_path0, OWN_SRC)


class TestStandaloneScriptsImportSuccessfully(unittest.TestCase):
    """End-to-end: the scripts must actually run with a foreign path ahead.

    The preamble tests above inspect state; these execute the real binaries.
    Before the fix both exited non-zero with ModuleNotFoundError here.
    """

    def _run(self, script: str, args: list[str], pythonpath: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONPATH": pythonpath}
        return subprocess.run(  # nosec B603 - this repo's own script, fixed argv
            [str(BIN_DIR / script), *args],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            timeout=120,
        )

    def test_llm_help_succeeds_with_foreign_checkout_ahead(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            foreign = make_fake_checkout(Path(td, "other-checkout"))
            combined = os.pathsep.join([str(foreign), OWN_SRC])

            proc = self._run("llm", ["--help"], combined)

            self.assertEqual(
                proc.returncode,
                0,
                "bin/llm failed with a sibling checkout ahead on PYTHONPATH:\n"
                f"{proc.stderr}",
            )

    def test_path_guard_imports_with_foreign_checkout_ahead(self) -> None:
        """path-guard exits 2 on bad usage; that is its contract, not a failure.

        What matters is that it reaches its own argument handling at all — an
        import failure exits 1 with ModuleNotFoundError instead.
        """
        with tempfile.TemporaryDirectory() as td:
            foreign = make_fake_checkout(Path(td, "other-checkout"))
            combined = os.pathsep.join([str(foreign), OWN_SRC])

            proc = self._run("path-guard", [], combined)

            self.assertNotIn("ModuleNotFoundError", proc.stderr)
            self.assertIn(
                "Usage: path-guard",
                proc.stdout + proc.stderr,
                f"bin/path-guard did not reach its own usage handler:\n{proc.stderr}",
            )

    def test_path_guard_accepts_a_real_path_with_foreign_checkout_ahead(self) -> None:
        """A full happy-path call, so this is not only an error-path assertion."""
        with tempfile.TemporaryDirectory() as td:
            foreign = make_fake_checkout(Path(td, "other-checkout"))
            combined = os.pathsep.join([str(foreign), OWN_SRC])

            proc = self._run(
                "path-guard", [str(REPO_ROOT), "bin/_pathrepair.py"], combined
            )

            self.assertEqual(
                proc.returncode,
                0,
                f"path-guard refused a legitimate repo file:\n{proc.stderr}",
            )


class TestPathRepairIsShared(unittest.TestCase):
    """One implementation, not three copies.

    The point of ``bin/_pathrepair.py`` is that security-critical path logic
    exists once. A future edit that re-inlines the logic into any one script
    would let the three drift apart silently — each would keep passing its own
    tests while diverging from the others.
    """

    def test_all_three_entry_points_load_the_shared_module(self) -> None:
        scripts = ["_router.py", "llm", "path-guard"]
        for script in scripts:
            with self.subTest(script=script):
                text = (BIN_DIR / script).read_text()
                self.assertIn(
                    "_pathrepair.py",
                    text,
                    f"bin/{script} no longer loads the shared path-repair module",
                )
                self.assertIn(
                    "strip_foreign_src_paths",
                    text,
                    f"bin/{script} does not call strip_foreign_src_paths",
                )
                self.assertIn(
                    "force_own_src_first",
                    text,
                    f"bin/{script} does not call force_own_src_first",
                )

    def test_strip_runs_before_the_venv_reexec(self) -> None:
        """Ordering is load-bearing, and nothing else would catch it.

        The strip must precede ``os.execv`` so the corrected PYTHONPATH is
        inherited by the re-exec'd interpreter. Move it after, and the fix
        still passes every state assertion in this file on machines without a
        ``.venv`` — while silently doing nothing on machines with one.
        """
        for script in ["_router.py", "llm", "path-guard"]:
            with self.subTest(script=script):
                text = (BIN_DIR / script).read_text()
                strip_at = text.index("strip_foreign_src_paths(_REPO_ROOT)")
                exec_at = text.index("os.execv(")
                force_at = text.index("force_own_src_first(")

                self.assertLess(
                    strip_at,
                    exec_at,
                    f"bin/{script}: the PYTHONPATH strip must run BEFORE the "
                    ".venv re-exec, or the correction is not inherited",
                )
                self.assertLess(
                    exec_at,
                    force_at,
                    f"bin/{script}: the sys.path precedence fix must run AFTER "
                    "the re-exec, immediately before the first repo import",
                )

    def test_shared_module_is_not_under_src(self) -> None:
        """It must not live where it would depend on the path it repairs.

        Under ``src/core/`` a broken path would either fail to import it or —
        far worse — import the FOREIGN checkout's copy, which would then
        "repair" nothing and report success.
        """
        self.assertTrue(PATHREPAIR.is_file(), f"{PATHREPAIR} is missing")
        self.assertEqual(PATHREPAIR.parent, BIN_DIR)

    def test_scripts_load_it_by_path_not_by_import(self) -> None:
        """A plain ``import _pathrepair`` would be subject to the same hijack."""
        for script in ["_router.py", "llm", "path-guard"]:
            with self.subTest(script=script):
                text = (BIN_DIR / script).read_text()
                self.assertIn("spec_from_file_location", text)
                self.assertNotIn("import _pathrepair", text)


class TestUnresolvableEntriesDoNotBreakTheRepair(unittest.TestCase):
    """A hostile PYTHONPATH entry must be skipped, never fatal.

    The repair runs before every command in bin/. An entry it cannot resolve is
    a reason to leave that entry alone, not a reason to take the whole CLI down.
    """

    def test_a_symlink_loop_does_not_crash_the_wrappers(self) -> None:
        """``Path.resolve()`` raises RuntimeError — NOT an OSError — on a loop.

        Catching only OSError meant one looping entry anywhere on PYTHONPATH
        aborted the repair and every ./bin/* wrapper with it: a pathlib
        traceback and exit 120, from a path the command never needed to read.
        """
        with tempfile.TemporaryDirectory() as td:
            loop = Path(td, "loop")
            loop.parent.mkdir(parents=True, exist_ok=True)
            loop.symlink_to(loop)  # self-referential: resolve() cannot converge

            # Sanity: the fixture really does produce the fatal exception, so
            # this test cannot quietly pass against a path that resolves fine.
            with self.assertRaises(RuntimeError):
                loop.resolve()

            for script in ["mail", "llm"]:
                with self.subTest(script=script):
                    proc = subprocess.run(  # nosec B603 - repo's own wrapper
                        [str(BIN_DIR / script), "--help"],
                        capture_output=True,
                        text=True,
                        env={
                            **os.environ,
                            "PYTHONPATH": os.pathsep.join(
                                [str(loop), str(REPO_ROOT / "src")]
                            ),
                        },
                        timeout=120,
                    )
                    self.assertEqual(
                        proc.returncode,
                        0,
                        f"bin/{script} died on a looping PYTHONPATH entry:\n"
                        f"{proc.stderr[-800:]}",
                    )
                    self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
