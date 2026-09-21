"""Unit tests for workflows/code/scripts/module_callers.py.

The script exists because a grep cannot answer "who imports this module?" and
`detect_facades.py` cannot either — its caller map is keyed on modules that are
already pure facades, so a module being split is never a key and the answer
comes back empty.

These tests pin the three forms a string search misses, each of which is a real
caller that a split would break:

- relative imports (``from .target import x``) share no substring with the
  absolute dotted path
- lazy imports nested in function bodies are below ``tree.body``
- ``from pkg import submodule`` binds a module, so the target is
  ``pkg.submodule`` rather than ``pkg``
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import textwrap
from pathlib import Path

import unittest

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "workflows"
    / "code"
    / "scripts"
    / "module_callers.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("module_callers_under_test", _SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the script under test from {_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


module_callers = _load()


class TreeMixin(unittest.TestCase):
    """Builds a throwaway src/ tree and chdirs into it."""

    def setUp(self):
        import os
        import tempfile

        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.tmp / "src" / "pkg" / "sub").mkdir(parents=True)
        (self.tmp / "tests").mkdir()
        (self.tmp / "src" / "pkg" / "__init__.py").write_text("")
        (self.tmp / "src" / "pkg" / "sub" / "__init__.py").write_text("")
        (self.tmp / "src" / "pkg" / "sub" / "target.py").write_text("def thing(): pass\n")
        self._cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self._cwd)

    def _write(self, rel: str, body: str) -> None:
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body))

    def _callers(self, target: str, roots: list[str]) -> list[str]:
        """Caller list, asserting the scan covered every file.

        Every assertion in this class routes through here, so a regression
        that starts silently skipping files fails the whole suite rather than
        only the one test that looks at `unscannable` directly.
        """
        callers, unscannable = module_callers.callers_of(target, roots)
        self.assertEqual(unscannable, [], "scan was incomplete")
        return callers


class CallerDetectionTests(TreeMixin):
    def test_absolute_import_found(self):
        self._write("tests/abs_caller.py", "from pkg.sub.target import thing\n")
        self.assertEqual(
            self._callers("pkg.sub.target", ["src", "tests"]),
            ["tests/abs_caller.py"],
        )

    def test_relative_import_found(self):
        # `from .target import thing` inside src/pkg/sub/ targets
        # pkg.sub.target and shares no substring with it — invisible to grep.
        self._write("src/pkg/sub/rel_caller.py", "from .target import thing\n")
        self.assertEqual(
            self._callers("pkg.sub.target", ["src"]),
            ["src/pkg/sub/rel_caller.py"],
        )

    def test_parent_relative_import_found(self):
        self._write("src/pkg/sub/deep/__init__.py", "")
        self._write("src/pkg/sub/deep/caller.py", "from ..target import thing\n")
        self.assertIn(
            "src/pkg/sub/deep/caller.py",
            self._callers("pkg.sub.target", ["src"]),
        )

    def test_lazy_in_function_import_found(self):
        # Below tree.body; only ast.walk reaches it.
        self._write(
            "src/pkg/lazy_caller.py",
            """
            def run():
                from pkg.sub import target
                return target.thing()
            """,
        )
        self.assertEqual(
            self._callers("pkg.sub.target", ["src"]),
            ["src/pkg/lazy_caller.py"],
        )

    def test_from_package_import_submodule_binds_the_submodule(self):
        # `from pkg.sub import target` binds a MODULE; the real target is
        # pkg.sub.target, not pkg.sub.
        self._write("tests/sub_caller.py", "from pkg.sub import target\n")
        self.assertIn(
            "tests/sub_caller.py",
            self._callers("pkg.sub.target", ["src", "tests"]),
        )

    def test_plain_import_found(self):
        self._write("tests/plain.py", "import pkg.sub.target\n")
        self.assertIn(
            "tests/plain.py", self._callers("pkg.sub.target", ["src", "tests"])
        )

    def test_unrelated_module_not_reported(self):
        self._write("tests/other.py", "import pkg.sub\n")
        self.assertEqual(self._callers("pkg.sub.target", ["tests"]), [])

    def test_substring_lookalike_not_reported(self):
        # The wildcard-dot false positive a bare grep produces.
        self._write("tests/looks.py", "import pkgXsubXtarget\n")
        self.assertEqual(self._callers("pkg.sub.target", ["tests"]), [])

    def test_no_callers_is_a_real_answer(self):
        self.assertEqual(self._callers("pkg.sub.target", ["src", "tests"]), [])

    def test_each_caller_listed_once(self):
        self._write(
            "tests/twice.py",
            """
            from pkg.sub.target import thing

            def again():
                import pkg.sub.target
                return pkg.sub.target.thing()
            """,
        )
        self.assertEqual(
            self._callers("pkg.sub.target", ["tests"]), ["tests/twice.py"]
        )

    def test_unparseable_file_is_reported_not_silently_skipped(self):
        # The scan continues past a broken file — one bad file must not abort
        # the inventory — but the file is REPORTED. Returning ["tests/ok.py"]
        # with no signal would present a partial scan as a complete one.
        self._write("tests/broken.py", "def unterminated(\n")
        self._write("tests/ok.py", "from pkg.sub.target import thing\n")
        callers, unscannable = module_callers.callers_of("pkg.sub.target", ["tests"])
        self.assertEqual(callers, ["tests/ok.py"])
        self.assertEqual(unscannable, ["tests/broken.py"])

    def test_unparseable_file_does_not_masquerade_as_zero_callers(self):
        # The defect this guards: the ONLY caller is unparseable. A scan that
        # swallows the parse error reports zero callers, and acting on that
        # deletes a module that still has one.
        self._write(
            "tests/broken_caller.py",
            "from pkg.sub.target import thing\ndef unterminated(\n",
        )
        callers, unscannable = module_callers.callers_of("pkg.sub.target", ["tests"])
        self.assertEqual(callers, [])
        self.assertEqual(unscannable, ["tests/broken_caller.py"])


class AncestorImportTests(TreeMixin):
    """Importing a descendant imports its ancestor packages."""

    def test_from_import_of_descendant_reports_ancestor(self):
        # `from pkg.sub.target.child import value` executes
        # pkg/sub/target/__init__.py, so this file is a live caller of
        # pkg.sub.target. Recording only the leaf let a split of
        # pkg.sub.target proceed while this caller still depended on it.
        self._write("src/pkg/sub/target/__init__.py", "")
        self._write("src/pkg/sub/target/child.py", "value = 1\n")
        self._write("tests/deep.py", "from pkg.sub.target.child import value\n")
        self.assertIn("tests/deep.py", self._callers("pkg.sub.target", ["src", "tests"]))

    def test_plain_import_of_descendant_reports_ancestor(self):
        self._write("src/pkg/sub/target/__init__.py", "")
        self._write("src/pkg/sub/target/child.py", "value = 1\n")
        self._write("tests/deep2.py", "import pkg.sub.target.child\n")
        self.assertIn("tests/deep2.py", self._callers("pkg.sub.target", ["src", "tests"]))

    def test_intermediate_packages_all_reported(self):
        self._write("tests/deep3.py", "import pkg.sub.target\n")
        targets = module_callers._targets_in("tests/deep3.py", "src")
        self.assertEqual(
            {"pkg", "pkg.sub", "pkg.sub.target"} - targets, set(),
            "every ancestor package is imported at runtime",
        )


class PackageInitTests(TreeMixin):
    """An __init__.py is its own package, not a member of its parent."""

    def test_relative_import_in_initializer_resolves_within_the_package(self):
        # `from .target import thing` inside src/pkg/sub/__init__.py means
        # pkg.sub.target. Treating the file as a member of `pkg` resolved it
        # to pkg.target and missed the caller entirely.
        self._write("src/pkg/sub/__init__.py", "from .target import thing\n")
        self.assertIn(
            "src/pkg/sub/__init__.py", self._callers("pkg.sub.target", ["src"])
        )

    def test_initializer_does_not_resolve_into_the_parent(self):
        self._write("src/pkg/sub/__init__.py", "from .target import thing\n")
        targets = module_callers._targets_in("src/pkg/sub/__init__.py", "src")
        self.assertNotIn("pkg.target", targets)


class WalkErrorTests(TreeMixin):
    """A directory that cannot be listed must not read as 'no callers'."""

    def test_unreadable_directory_is_reported(self):
        import os

        self._write("src/pkg/locked/caller.py", "from pkg.sub.target import thing\n")
        locked = self.tmp / "src" / "pkg" / "locked"
        os.chmod(locked, 0o000)
        self.addCleanup(os.chmod, locked, 0o755)

        callers, unscannable = module_callers.callers_of("pkg.sub.target", ["src"])
        # os.walk defaults to onerror=None, which dropped the whole subtree
        # without a word: callers [], unscannable [], complete True, exit 0.
        self.assertNotEqual(unscannable, [], "an unreadable directory must be reported")
        self.assertEqual(callers, [])

    def test_unreadable_directory_exits_two(self):
        import os

        self._write("src/pkg/locked2/caller.py", "from pkg.sub.target import thing\n")
        locked = self.tmp / "src" / "pkg" / "locked2"
        os.chmod(locked, 0o000)
        self.addCleanup(os.chmod, locked, 0o755)

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = module_callers.main(["--module", "pkg.sub.target", "--roots", "src"])
        self.assertEqual(rc, 2)
        self.assertIn("INCOMPLETE", err.getvalue())


class AliasIsNotAlwaysAModuleTests(TreeMixin):
    """`from pkg import name` binds a submodule only if pkg/name.py exists.

    Otherwise *name* is a class, function or value re-exported by
    pkg/__init__.py. Recording pkg.name unconditionally invented a module and
    reported a false caller of it, which the sweep would then demand be
    rewritten.
    """

    def test_imported_class_is_not_reported_as_a_module(self):
        self._write("src/pkg/exports/__init__.py", "class Thing:\n    pass\n")
        self._write("tests/uses_class.py", "from pkg.exports import Thing\n")
        self.assertEqual(self._callers("pkg.exports.Thing", ["src", "tests"]), [])

    def test_imported_class_still_counts_as_a_caller_of_the_package(self):
        # The import DOES execute pkg/exports/__init__.py, so the package
        # itself keeps its caller — only the phantom submodule goes away.
        self._write("src/pkg/exports/__init__.py", "class Thing:\n    pass\n")
        self._write("tests/uses_class.py", "from pkg.exports import Thing\n")
        self.assertIn("tests/uses_class.py", self._callers("pkg.exports", ["src", "tests"]))

    def test_real_submodule_alias_is_still_reported(self):
        # The true-positive this line exists for must survive: target.py is a
        # real file, so `from pkg.sub import target` is a caller of it.
        self._write("tests/uses_submodule.py", "from pkg.sub import target\n")
        self.assertIn(
            "tests/uses_submodule.py", self._callers("pkg.sub.target", ["src", "tests"])
        )

    def test_package_submodule_alias_is_still_reported(self):
        self._write("src/pkg/sub/deep/__init__.py", "")
        self._write("tests/uses_pkg.py", "from pkg.sub import deep\n")
        self.assertIn("tests/uses_pkg.py", self._callers("pkg.sub.deep", ["src", "tests"]))

    def test_nonexistent_alias_does_not_fabricate_a_module(self):
        self._write("tests/uses_missing.py", "from pkg.sub import NoSuchThing\n")
        self.assertEqual(self._callers("pkg.sub.NoSuchThing", ["src", "tests"]), [])


class TestsRootNamingTests(TreeMixin):
    """A file under tests/ gets the name Python actually binds.

    tests/ and its subpackages carry __init__.py in this repo, so a test
    module's real dotted name is rooted at the repo (tests.pkg.mod), which is
    what the default --src-root src produces for any path outside src/.
    Pinning it because a "fix" that stripped the tests/ prefix would make
    every relative import in a test package resolve to a module that does not
    exist, and the scan would still exit 0.
    """

    def test_test_module_keeps_its_tests_prefix(self):
        self._write("tests/suite/__init__.py", "")
        self._write("tests/suite/helper.py", "X = 1\n")
        self.assertEqual(
            module_callers.module_path("tests/suite/helper.py", "src"),
            "tests.suite.helper",
        )

    def test_relative_import_in_a_test_package_resolves(self):
        self._write("tests/suite/__init__.py", "")
        self._write("tests/suite/helper.py", "X = 1\n")
        self._write("tests/suite/test_uses.py", "from .helper import X\n")
        self.assertIn(
            "tests/suite/test_uses.py",
            self._callers("tests.suite.helper", ["tests"]),
        )

    def test_src_file_is_unaffected_by_the_same_src_root(self):
        self.assertEqual(
            module_callers.module_path("src/pkg/sub/target.py", "src"),
            "pkg.sub.target",
        )


class AbsoluteRootTests(TreeMixin):
    """An absolute --roots must behave like a relative one.

    os.walk over an absolute root yields absolute filenames, which never start
    with "src/", so the whole filesystem path became the dotted module name
    (".var.folders...tmpXXXX.src.pkg.mod"). Relative imports in those files
    then resolved against a nonsense package and their callers vanished —
    while the scan still exited 0 and reported complete.
    """

    def test_absolute_root_finds_the_same_callers(self):
        self._write("src/pkg/sub/rel_caller.py", "from .target import thing\n")
        self._write("src/abs_caller.py", "from pkg.sub.target import thing\n")

        relative, _ = module_callers.callers_of("pkg.sub.target", ["src"])
        absolute, _ = module_callers.callers_of("pkg.sub.target", [str(self.tmp / "src")])

        self.assertEqual(len(absolute), len(relative), "absolute root lost callers")
        self.assertEqual(
            sorted(Path(p).name for p in absolute),
            sorted(Path(p).name for p in relative),
        )

    def test_absolute_root_resolves_relative_imports(self):
        # The relative-import caller is the one the bug dropped; the absolute
        # import was found either way, so asserting on the count alone would
        # have passed against the broken code.
        self._write("src/pkg/sub/rel_caller.py", "from .target import thing\n")
        found, _ = module_callers.callers_of("pkg.sub.target", [str(self.tmp / "src")])
        self.assertEqual([Path(p).name for p in found], ["rel_caller.py"])

    def test_module_path_handles_an_absolute_file(self):
        self.assertEqual(
            module_callers.module_path(str(self.tmp / "src" / "pkg" / "sub" / "mod.py"), "src"),
            "pkg.sub.mod",
        )

    def test_module_path_handles_an_absolute_src_root(self):
        self.assertEqual(
            module_callers.module_path(
                str(self.tmp / "src" / "pkg" / "mod.py"), str(self.tmp / "src")
            ),
            "pkg.mod",
        )

    def test_relative_path_still_resolves(self):
        self.assertEqual(module_callers.module_path("src/pkg/mod.py", "src"), "pkg.mod")


class ModulePathTests(unittest.TestCase):
    def test_init_maps_to_the_package(self):
        # Not pkg.providers.__init__, which would bind a second module object.
        self.assertEqual(
            module_callers.module_path("src/mail/providers/__init__.py"), "mail.providers"
        )

    def test_plain_module(self):
        self.assertEqual(
            module_callers.module_path("src/mail/config_resolver.py"), "mail.config_resolver"
        )


class ResolveRelativeTests(unittest.TestCase):
    def test_single_dot_is_current_package(self):
        self.assertEqual(module_callers.resolve_relative(1, "target", "pkg.sub"), "pkg.sub.target")

    def test_double_dot_walks_up(self):
        self.assertEqual(module_callers.resolve_relative(2, "target", "pkg.sub"), "pkg.target")

    def test_bare_from_dot_import(self):
        self.assertEqual(module_callers.resolve_relative(1, None, "pkg.sub"), "pkg.sub")


class CliTests(TreeMixin):
    def test_missing_root_exits_nonzero(self):
        # A mistyped root would otherwise report zero callers — the exact
        # false-clean this script exists to prevent.
        self.assertEqual(
            module_callers.main(["--module", "pkg.sub.target", "--roots", "nosuchdir"]), 1
        )

    def test_empty_module_exits_nonzero(self):
        self.assertEqual(module_callers.main(["--module", "  "]), 1)

    def test_success_exits_zero(self):
        self._write("tests/abs_caller.py", "from pkg.sub.target import thing\n")
        self.assertEqual(
            module_callers.main(["--module", "pkg.sub.target", "--roots", "src", "tests"]), 0
        )

    def test_missing_src_root_exits_nonzero(self):
        # --src-root drives relative-import resolution and the
        # submodule-vs-symbol check. A mistyped value made module_path() fall
        # back to the raw path, so relative callers vanished while the scan
        # exited 0 and called itself complete.
        self.assertEqual(
            module_callers.main(
                ["--module", "pkg.sub.target", "--roots", "src", "--src-root", "nosuchdir"]
            ),
            1,
        )

    def test_src_root_pointing_at_a_file_exits_nonzero(self):
        self._write("src/notadir.py", "x = 1\n")
        self.assertEqual(
            module_callers.main(
                ["--module", "pkg.sub.target", "--roots", "src", "--src-root", "src/notadir.py"]
            ),
            1,
        )

    def test_valid_src_root_still_scans(self):
        self._write("tests/ok_root.py", "from pkg.sub.target import thing\n")
        self.assertEqual(
            module_callers.main(
                ["--module", "pkg.sub.target", "--roots", "tests", "--src-root", "src"]
            ),
            0,
        )

    def test_zero_callers_still_exits_zero(self):
        # "no callers" is a real answer, not an error.
        self.assertEqual(
            module_callers.main(["--module", "pkg.sub.target", "--roots", "src"]), 0
        )

    def test_unparseable_file_exits_two(self):
        # Distinct from 0: a workflow reading the exit code must be able to
        # tell "zero callers, scan complete" from "zero callers, scan partial".
        self._write("tests/broken.py", "def unterminated(\n")
        self.assertEqual(
            module_callers.main(["--module", "pkg.sub.target", "--roots", "tests"]), 2
        )

    def test_unparseable_paths_named_on_stderr(self):
        self._write("tests/broken.py", "def unterminated(\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            module_callers.main(["--module", "pkg.sub.target", "--roots", "tests"])
        self.assertIn("tests/broken.py", err.getvalue())
        self.assertIn("INCOMPLETE", err.getvalue())

    def test_json_reports_completeness(self):
        self._write("tests/broken.py", "def unterminated(\n")
        self._write("tests/ok.py", "from pkg.sub.target import thing\n")
        out = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(out):
            rc = module_callers.main(
                ["--module", "pkg.sub.target", "--roots", "tests", "--format", "json"]
            )
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 2)
        self.assertIs(payload["complete"], False)
        self.assertEqual(payload["unscannable"], ["tests/broken.py"])
        self.assertEqual(payload["callers"], ["tests/ok.py"])

    def test_json_complete_true_on_a_clean_scan(self):
        self._write("tests/ok.py", "from pkg.sub.target import thing\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = module_callers.main(
                ["--module", "pkg.sub.target", "--roots", "tests", "--format", "json"]
            )
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertIs(payload["complete"], True)
        self.assertEqual(payload["unscannable"], [])


if __name__ == "__main__":
    unittest.main()
