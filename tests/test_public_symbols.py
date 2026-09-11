"""Unit tests for workflows/code/scripts/public_symbols.py.

The script exists because the export-parity check in
workflows/code/qlty-complexity-sweep.yaml compares a module's symbols before
and after a refactor, and the two sides must apply the SAME predicate. These
tests pin the three asymmetries that made the previous grep/dir() pair
unusable:

- private names must be excluded from BOTH sides (a grep for "^def " keeps
  them, a dir() filter drops them, so every private helper read as missing)
- ``async def`` must be included (the grep missed it entirely, so public
  coroutines were never checked)
- imported-and-re-exported names must NOT count as the module's own (a bare
  dir() lists them, masking a genuinely deleted definition)
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
import unittest
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "workflows"
    / "code"
    / "scripts"
    / "public_symbols.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("public_symbols_under_test", _SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the script under test from {_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


public_symbols = _load()


class FromSourceTests(unittest.TestCase):
    """Source-side extraction, which reads a `git show HEAD:path` blob."""

    def _write(self, body: str) -> str:
        path = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        target = path / "mod.py"
        target.write_text(textwrap.dedent(body))
        return str(target)

    def test_public_defs_and_classes(self):
        src = self._write(
            """
            class Alpha: pass
            def beta(): pass
            """
        )
        self.assertEqual(public_symbols.from_source(src), ["Alpha", "beta"])

    def test_async_def_is_included(self):
        # The old `grep "^def "` missed async functions, so a public coroutine
        # silently escaped the parity check.
        src = self._write(
            """
            async def fetch(): pass
            def plain(): pass
            """
        )
        self.assertEqual(public_symbols.from_source(src), ["fetch", "plain"])

    def test_private_names_excluded(self):
        src = self._write(
            """
            def _helper(): pass
            class _Internal: pass
            def public(): pass
            """
        )
        self.assertEqual(public_symbols.from_source(src), ["public"])

    def test_dunder_excluded(self):
        src = self._write(
            """
            def __getattr__(name): pass
            def real(): pass
            """
        )
        self.assertEqual(public_symbols.from_source(src), ["real"])

    def test_nested_defs_are_not_top_level(self):
        src = self._write(
            """
            def outer():
                def inner(): pass
                return inner
            """
        )
        self.assertEqual(public_symbols.from_source(src), ["outer"])

    def test_imports_are_not_definitions(self):
        src = self._write(
            """
            from os import getcwd
            import sys
            def mine(): pass
            """
        )
        self.assertEqual(public_symbols.from_source(src), ["mine"])

    def test_assignments_are_not_definitions(self):
        src = self._write(
            """
            CONST = 5
            def mine(): pass
            """
        )
        self.assertEqual(public_symbols.from_source(src), ["mine"])

    def test_result_is_sorted(self):
        src = self._write(
            """
            def zeta(): pass
            def alpha(): pass
            """
        )
        self.assertEqual(public_symbols.from_source(src), ["alpha", "zeta"])

    def test_empty_module(self):
        self.assertEqual(public_symbols.from_source(self._write('"""Doc."""')), [])

    def test_syntax_error_raises(self):
        with self.assertRaises(SyntaxError):
            public_symbols.from_source(self._write("def broken("))


class FromModuleTests(unittest.TestCase):
    """Runtime-side extraction, restricted to the module's own definitions."""

    def test_own_definitions_only(self):
        # json re-exports names from json.decoder/json.encoder; those must not
        # be attributed to json itself, which is the asymmetry a bare dir()
        # introduced.
        names = public_symbols.from_module("json")
        self.assertIn("dumps", names)
        self.assertNotIn("JSONDecoder", names)

    def test_imported_submodules_excluded(self):
        # `import json.decoder` binds the submodule as an attribute of `json`.
        # A module object has no __module__, so a check that defaults the
        # attribute to the current module misattributes it — this caught a
        # real bug in the first version of from_module().
        names = public_symbols.from_module("json")
        for submodule in ("codecs", "decoder", "encoder", "scanner"):
            self.assertNotIn(submodule, names)

    def test_excludes_private(self):
        for name in public_symbols.from_module("json"):
            self.assertFalse(name.startswith("_"), name)

    def test_sorted(self):
        names = public_symbols.from_module("json")
        self.assertEqual(names, sorted(names))

    def test_unimportable_raises(self):
        with self.assertRaises(ImportError):
            public_symbols.from_module("no.such.module.anywhere")


class CliTests(unittest.TestCase):
    """The CLI must fail loudly — a silent 0 would read as 'no symbols'."""

    def test_missing_source_exits_nonzero(self):
        self.assertEqual(public_symbols.main(["--source", "/nonexistent.py"]), 1)

    def test_unimportable_module_exits_nonzero(self):
        self.assertEqual(public_symbols.main(["--module", "no.such.module"]), 1)

    def test_module_mode_succeeds(self):
        self.assertEqual(public_symbols.main(["--module", "json"]), 0)

    def test_source_and_module_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            public_symbols.main(["--source", "a.py", "--module", "json"])

    def test_one_of_them_is_required(self):
        with self.assertRaises(SystemExit):
            public_symbols.main([])


class ParityTests(unittest.TestCase):
    """The two modes must agree on a real module — the script's whole point."""

    def test_source_and_module_agree(self):
        import json as json_mod

        from_source = public_symbols.from_source(json_mod.__file__)
        from_module = public_symbols.from_module("json")
        self.assertEqual(from_source, from_module)


if __name__ == "__main__":
    unittest.main()
