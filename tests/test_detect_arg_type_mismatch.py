"""Unit tests for workflows/code/scripts/detect_arg_type_mismatch.py.

Covers:
- True positive: None passed to a ``str``-annotated parameter.
- True negative: None passed to ``str | None`` (union that permits None).
- True negative: Any/object annotations (permissive).
- The cls-shift regression: a plain function named ``_render_cls_group(cls: str,
  group: list, tool_name: str)`` must not have its ``cls`` stripped, so
  ``_render_cls_group(None, [], "tool")`` must flag ``cls`` (index 0), not
  ``group`` (index 1).
- Classmethod receiver IS stripped: ``Foo.from_str(None)`` does NOT flag the
  ``cls`` receiver, it flags the first real parameter.
- Instance method receiver IS stripped: ``Foo().parse(None)`` flags the first
  non-self parameter.

The script lives outside the installed package, so we load it via importlib
the same way tests/test_detect_facades.py does.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Load the module under test via importlib (same idiom as test_detect_facades).
# We chdir to a temp directory so the module-level os.environ reads do not
# accidentally walk a real src/ or tests/ tree during import.
# ---------------------------------------------------------------------------

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "workflows"
    / "code"
    / "scripts"
    / "detect_arg_type_mismatch.py"
)


def _load_detector():
    spec = importlib.util.spec_from_file_location("detect_arg_type_mismatch", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            spec.loader.exec_module(mod)
        finally:
            os.chdir(old_cwd)
    return mod


_dm = _load_detector()

collect_signatures = _dm.collect_signatures
scan_test_files = _dm.scan_test_files
_collect_params = _dm._collect_params
_is_mismatch = _dm._is_mismatch


# ---------------------------------------------------------------------------
# Helper: write a minimal fake src/ and tests/ tree in a temp dir.
# ---------------------------------------------------------------------------

class _TempRepo:
    """Context manager that creates a src/ and tests/ dir pair in a temp dir."""

    def __init__(self, src_code: str, test_code: str):
        self._src_code = textwrap.dedent(src_code)
        self._test_code = textwrap.dedent(test_code)
        self._tmp: tempfile.TemporaryDirectory | None = None

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        src = os.path.join(root, "src", "mymod")
        tests = os.path.join(root, "tests")
        os.makedirs(src)
        os.makedirs(tests)
        with open(os.path.join(src, "helpers.py"), "w") as fh:
            fh.write(self._src_code)
        with open(os.path.join(tests, "test_helpers.py"), "w") as fh:
            fh.write(self._test_code)
        self.src_root = os.path.join(root, "src")
        self.test_root = tests
        return self

    def __exit__(self, *_):
        self._tmp.cleanup()


class TestIsMismatch(unittest.TestCase):
    """Unit tests for the _is_mismatch predicate."""

    def test_none_vs_str_is_mismatch(self):
        self.assertTrue(_is_mismatch(None, "str"))

    def test_none_vs_str_or_none_is_ok(self):
        self.assertFalse(_is_mismatch(None, "str | None"))

    def test_none_vs_optional_str_is_ok(self):
        self.assertFalse(_is_mismatch(None, "Optional[str]"))

    def test_none_vs_any_is_ok(self):
        self.assertFalse(_is_mismatch(None, "Any"))

    def test_none_vs_object_is_ok(self):
        self.assertFalse(_is_mismatch(None, "object"))

    def test_str_vs_int_annotation_is_mismatch(self):
        self.assertTrue(_is_mismatch("hello", "int"))

    def test_int_vs_str_annotation_is_mismatch(self):
        self.assertTrue(_is_mismatch(42, "str"))

    def test_int_vs_int_is_ok(self):
        self.assertFalse(_is_mismatch(42, "int"))

    def test_bool_literal_not_flagged(self):
        # bool is a subclass of int; we explicitly exclude bools
        self.assertFalse(_is_mismatch(True, "int"))


class TestCollectParams(unittest.TestCase):
    """Unit tests for receiver-skipping logic."""

    def _parse_func(self, src: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
        # Annotated as the union the isinstance check actually admits. It said
        # `ast.FunctionDef` while returning either, which the changed-files
        # mypy gate correctly rejected.
        tree = ast.parse(textwrap.dedent(src))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        raise AssertionError("no function found")

    def test_plain_function_cls_not_stripped(self):
        """A plain function named with first param 'cls: str' keeps it."""
        func = self._parse_func(
            """\
            def _render_cls_group(cls: str, group: list, tool_name: str) -> list[str]:
                pass
            """
        )
        params = _collect_params(func, is_method=False, is_classmethod=False)
        names = [p[0] for p in params]
        # cls must be index 0 — NOT stripped
        self.assertEqual(names[0], "cls")
        self.assertEqual(names[1], "group")
        self.assertEqual(names[2], "tool_name")

    def test_instance_method_self_stripped(self):
        src = """\
            class Foo:
                def parse(self, value: str) -> None:
                    pass
        """
        tree = ast.parse(textwrap.dedent(src))
        cls_node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        method = next(
            m for m in cls_node.body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        params = _collect_params(method, is_method=True, is_classmethod=False)
        names = [p[0] for p in params]
        self.assertNotIn("self", names)
        self.assertEqual(names[0], "value")

    def test_classmethod_cls_stripped(self):
        src = """\
            class Foo:
                @classmethod
                def from_str(cls, value: str) -> 'Foo':
                    pass
        """
        tree = ast.parse(textwrap.dedent(src))
        cls_node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        method = next(
            m for m in cls_node.body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        params = _collect_params(method, is_method=False, is_classmethod=True)
        names = [p[0] for p in params]
        self.assertNotIn("cls", names)
        self.assertEqual(names[0], "value")


class TestClsShiftRegression(unittest.TestCase):
    """Regression: _render_cls_group(cls: str, group: list, tool_name: str).

    The prototype stripped 'cls' by name, shifting group to index 0 and
    tool_name to index 1.  A call like _render_cls_group(None, [], "tool")
    would then flag group (None vs list) instead of cls (None vs str).
    This test pins the correct behaviour.
    """

    SRC = """\
        def _render_cls_group(cls: str, group: list, tool_name: str) -> list[str]:
            return []
    """
    TEST = """\
        from mymod.helpers import _render_cls_group

        def test_it():
            _render_cls_group(None, [], "tool")
    """

    def test_flags_cls_not_group(self):
        with _TempRepo(self.SRC, self.TEST) as repo:
            sigs = collect_signatures(repo.src_root)
            findings = scan_test_files(repo.test_root, sigs)
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0]["param"], "cls")
        self.assertEqual(findings[0]["literal_value"], "None")

    def test_no_false_positive_on_group(self):
        """Passing None to group (list) should also fire, but only once."""
        src = """\
            def _render_cls_group(cls: str, group: list, tool_name: str) -> list[str]:
                return []
        """
        test = """\
            from mymod.helpers import _render_cls_group

            def test_it():
                _render_cls_group("label", None, "tool")
        """
        with _TempRepo(src, test) as repo:
            sigs = collect_signatures(repo.src_root)
            findings = scan_test_files(repo.test_root, sigs)
        # None vs list is a mismatch on group (index 1 for a plain function)
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0]["param"], "group")


class TestTruePositive(unittest.TestCase):
    """None passed to a str-annotated parameter is flagged."""

    SRC = """\
        def greet(name: str) -> str:
            return f"Hello {name}"
    """
    TEST = """\
        from mymod.helpers import greet

        def test_bad():
            greet(None)
    """

    def test_flags_none_for_str(self):
        with _TempRepo(self.SRC, self.TEST) as repo:
            sigs = collect_signatures(repo.src_root)
            findings = scan_test_files(repo.test_root, sigs)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["callee"], "greet")
        self.assertEqual(findings[0]["param"], "name")
        self.assertEqual(findings[0]["annotation"], "str")
        self.assertEqual(findings[0]["literal_value"], "None")


class TestTrueNegativeUnion(unittest.TestCase):
    """None passed to ``str | None`` must NOT be flagged."""

    SRC = """\
        def greet(name: str | None) -> str:
            return f"Hello {name}"
    """
    TEST = """\
        from mymod.helpers import greet

        def test_ok():
            greet(None)
    """

    def test_no_finding_for_optional(self):
        with _TempRepo(self.SRC, self.TEST) as repo:
            sigs = collect_signatures(repo.src_root)
            findings = scan_test_files(repo.test_root, sigs)
        self.assertEqual(findings, [])


class TestTrueNegativeAny(unittest.TestCase):
    """None passed to ``Any``-annotated parameter must NOT be flagged."""

    SRC = """\
        from typing import Any
        def consume(value: Any) -> None:
            pass
    """
    TEST = """\
        from mymod.helpers import consume

        def test_ok():
            consume(None)
    """

    def test_no_finding_for_any(self):
        with _TempRepo(self.SRC, self.TEST) as repo:
            sigs = collect_signatures(repo.src_root)
            findings = scan_test_files(repo.test_root, sigs)
        self.assertEqual(findings, [])


class TestMockedCallee(unittest.TestCase):
    """A call whose name is NOT imported from a src module is ignored.

    This simulates a test file that patches/mocks a function: the local name
    is bound via MagicMock or patch, not via ``from mymod.helpers import``.
    """

    SRC = """\
        def do_thing(value: str) -> None:
            pass
    """
    TEST = """\
        # do_thing is NOT imported here — it would come from a mock.
        # The detector must not flag this call.
        def test_mocked():
            do_thing = lambda x: None
            do_thing(None)
    """

    def test_no_finding_for_unimported_name(self):
        with _TempRepo(self.SRC, self.TEST) as repo:
            sigs = collect_signatures(repo.src_root)
            findings = scan_test_files(repo.test_root, sigs)
        self.assertEqual(findings, [])


class TestStaticmethodKeepsFirstParam(unittest.TestCase):
    """@staticmethod takes no receiver, so its first parameter is real.

    Treating it as an instance method deleted index 0 and shifted the rest --
    the same index-shift bug the cls fix addressed, reached another way. A
    one-parameter staticmethod collapsed to zero and went permanently
    invisible (94 staticmethods in src/).
    """

    def _parse_method(self, src: str):
        tree = ast.parse(textwrap.dedent(src))
        cls_node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        return next(
            m for m in cls_node.body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        )

    def test_staticmethod_detected(self):
        method = self._parse_method(
            """\
            class Tool:
                @staticmethod
                def render(label: str, count: int) -> str:
                    return label
            """
        )
        self.assertTrue(_dm._has_staticmethod_decorator(method))

    def test_first_param_survives_collection(self):
        src = """\
            class Tool:
                @staticmethod
                def render(label: str, count: int) -> str:
                    return label
        """
        cls_node = next(
            n for n in ast.walk(ast.parse(textwrap.dedent(src)))
            if isinstance(n, ast.ClassDef)
        )
        sigs = {}
        _dm._collect_class_sigs(cls_node, "p.py", "mod", sigs)
        names = [p[0] for p in sigs[("mod", "render")][2]]
        self.assertEqual(names, ["label", "count"])

    def test_single_param_staticmethod_not_erased(self):
        src = """\
            class Tool:
                @staticmethod
                def normalize(argv: str) -> str:
                    return argv
        """
        cls_node = next(
            n for n in ast.walk(ast.parse(textwrap.dedent(src)))
            if isinstance(n, ast.ClassDef)
        )
        sigs = {}
        _dm._collect_class_sigs(cls_node, "p.py", "mod", sigs)
        self.assertEqual([p[0] for p in sigs[("mod", "normalize")][2]], ["argv"])


class TestAttributeCallsNotResolved(unittest.TestCase):
    """`self.foo(...)` must not match an imported module-level `foo`.

    _callee_name returned `.attr`, discarding the receiver, so a.foo(), b.foo()
    and self.foo() were indistinguishable. 93 such calls in tests/ resolved
    against an unrelated function.
    """

    SRC = """\
        def _parse_agent(spec: str) -> str:
            return spec
    """
    TEST = """\
        from mymod.helpers import _parse_agent

        class T:
            def test_it(self):
                self._parse_agent(None)
    """

    def test_attribute_call_is_skipped(self):
        with _TempRepo(self.SRC, self.TEST) as repo:
            sigs = collect_signatures(repo.src_root)
            findings = scan_test_files(repo.test_root, sigs)
        self.assertEqual(findings, [])


class TestAmbiguousKeysDropped(unittest.TestCase):
    """Two same-named defs in one module must not resolve to an arbitrary one."""

    SRC = """\
        class A:
            def consume(self, payload: str) -> None:
                pass

        class B:
            def consume(self, payload: dict) -> None:
                pass
    """
    TEST = """\
        from mymod.helpers import consume

        def test_it():
            consume(None)
    """

    def test_collision_drops_the_key(self):
        with _TempRepo(self.SRC, self.TEST) as repo:
            sigs = collect_signatures(repo.src_root)
            findings = scan_test_files(repo.test_root, sigs)
        self.assertNotIn(("helpers", "consume"), sigs)
        self.assertEqual(findings, [])


class TestNoneUnionParsing(unittest.TestCase):
    """The None check parses the annotation instead of substring-matching."""

    def test_any_nested_in_generic_is_still_hostile(self):
        # `dict[str, Any]` contains "Any" as a substring but does not accept
        # None. 270 parameters in this repo carry it.
        self.assertTrue(_is_mismatch(None, "dict[str, Any]"))

    def test_callable_returning_none_is_hostile(self):
        self.assertTrue(_is_mismatch(None, "Callable[..., None]"))

    def test_bare_any_still_permits_none(self):
        self.assertFalse(_is_mismatch(None, "Any"))

    def test_union_spellings_permit_none(self):
        for ann in ("str | None", "Optional[str]", "Union[str, None]", "NoneType"):
            with self.subTest(ann=ann):
                self.assertFalse(_is_mismatch(None, ann))


class TestStrIntUnions(unittest.TestCase):
    """str/int literals must consider EVERY top-level union member.

    The None check was converted to parsed unions but the str/int paths were
    left on ``ann.split("[")[0]``, which reads only the first member: `int |
    None` looked like base ``int |``, matched no hostile base, and silently
    accepted a string. Member order decided the answer.
    """

    def test_str_into_optional_int_is_a_mismatch(self):
        for ann in ("int | None", "Optional[int]", "Union[int, None]"):
            with self.subTest(ann=ann):
                self.assertTrue(_is_mismatch("x", ann))

    def test_int_into_optional_str_is_a_mismatch(self):
        for ann in ("str | None", "Optional[str]"):
            with self.subTest(ann=ann):
                self.assertTrue(_is_mismatch(1, ann))

    def test_union_that_accepts_the_literal_is_not_flagged(self):
        # One accepting member is enough; order must not matter.
        self.assertFalse(_is_mismatch("x", "int | str"))
        self.assertFalse(_is_mismatch("x", "str | int"))
        self.assertFalse(_is_mismatch(1, "int | str"))
        self.assertFalse(_is_mismatch(1, "str | int"))

    def test_all_hostile_members_still_flag(self):
        self.assertTrue(_is_mismatch("x", "dict | list"))


class TestEmptyScanFailsLoudly(unittest.TestCase):
    """An empty scan must exit non-zero, not report a reassuring zero.

    0 findings from 0 scanned files is byte-identical to 0 findings from a
    clean tree. That false clean is the exact hazard this detector works
    around, so reproducing it here would be self-defeating. main() returns 2
    and stderr says so.
    """

    def _run_main(self, argv):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = _dm.main(argv)
        return code, json.loads(buf.getvalue()), err.getvalue()

    def test_missing_roots_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "nope")
            code, payload, err = self._run_main(["prog", missing, missing])
        self.assertEqual(code, 2)
        self.assertTrue(payload["scanned_nothing"])
        self.assertEqual(payload["stats"]["src_files_scanned"], 0)
        self.assertIn("scanned nothing", err)

    def test_real_scan_exits_zero_and_reports_counts(self):
        src = "def greet(name: str) -> str:\n    return name\n"
        test = "from mymod.helpers import greet\n\ndef test_ok():\n    greet('x')\n"
        with _TempRepo(src, test) as repo:
            code, payload, _ = self._run_main(
                ["prog", repo.src_root, repo.test_root]
            )
        self.assertEqual(code, 0)
        self.assertFalse(payload["scanned_nothing"])
        self.assertGreater(payload["stats"]["src_files_scanned"], 0)
        self.assertGreater(payload["stats"]["signatures_collected"], 0)


if __name__ == "__main__":
    unittest.main()
