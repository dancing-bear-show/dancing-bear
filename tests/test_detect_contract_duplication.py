"""Unit tests for workflows/code/scripts/detect_contract_duplication.py.

Covers:
- Fixture reproducing the slides shape (3 shared calls): must be flagged.
- Fixture of an app-unique test sharing one helper: must NOT be flagged.
- A method overriding a contract method by the same name: must NOT be flagged.
- A method using patch.object (conditional-branch testing): must NOT be flagged.

The script lives outside the installed package, so we load it via importlib
the same way tests/test_detect_facades.py does.

Integration tests use importlib to call the scan() function directly, pointing
it at a temporary tree that mirrors the real MIXINS registry -- the detector's
MIXINS dict is monkey-patched for the duration of each test so that the helper
can find the temporary mixin file.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Load the module under test via importlib.
# We chdir to a temp dir during loading so the module-level os.walk does not
# scan a real tests/ tree -- the scan completes with an empty set, and we
# then call only the pure-function helpers or monkey-patch MIXINS.
# ---------------------------------------------------------------------------

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "workflows"
    / "code"
    / "scripts"
    / "detect_contract_duplication.py"
)


def _load_detector():
    spec = importlib.util.spec_from_file_location("detect_contract_duplication", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            spec.loader.exec_module(mod)
        finally:
            os.chdir(old_cwd)
    return mod


_det = _load_detector()

_parse = _det._parse
_calls = _det._calls
_all_names = _det._all_names
_uses_mocking = _det._uses_mocking
_load_mixin_methods = _det._load_mixin_methods
_jaccard = _det._jaccard
scan = _det.scan
SIMILARITY_THRESHOLD = _det.SIMILARITY_THRESHOLD
MIN_SHARED_CALLS = _det.MIN_SHARED_CALLS


# ---------------------------------------------------------------------------
# Helper: write files into a temp directory and run scan() from there.
# ---------------------------------------------------------------------------

class _TmpRepo:
    """Context manager that wires a mini tests/ tree for scan() integration."""

    def __init__(self, mixin_src: str, test_file_src: str):
        self._mixin_src = textwrap.dedent(mixin_src)
        self._test_src = textwrap.dedent(test_file_src)
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._old_cwd: str = ""
        self._old_tests: str = _det.TESTS
        self._old_mixins: dict = dict(_det.MIXINS)

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        tests = root / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("")
        mixin_path = str(tests / "fake_contract.py")
        Path(mixin_path).write_text(self._mixin_src)
        (tests / "test_fake_agentic.py").write_text(self._test_src)
        # Redirect scan() to look at our temporary tree.
        self._old_cwd = os.getcwd()
        os.chdir(root)
        _det.TESTS = "tests"
        _det.MIXINS.clear()
        _det.MIXINS[mixin_path] = "FakeContractMixin"
        return self

    def __exit__(self, *_):
        os.chdir(self._old_cwd)
        _det.TESTS = self._old_tests
        _det.MIXINS.clear()
        _det.MIXINS.update(self._old_mixins)
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# The mixin method calls: build_agentic_capsule, emit_agentic_context,
# getvalue, assertEqual, strip -- reproducing the slides calibration shape.
_SLIDES_MIXIN = """
class FakeContractMixin:
    def test_emit_output_matches_build_agentic_capsule(self):
        buf = StringIO()
        with redirect_stdout(buf):
            emit_agentic_context()
        self.assertEqual(buf.getvalue().strip(), build_agentic_capsule().strip())
"""

_ADOPTER = """
import unittest
from tests.fake_contract import FakeContractMixin

class TestFakeContract(FakeContractMixin, unittest.TestCase):
    MODULE_PATH = "fake.agentic"
    APP_ID = "fake"
"""


# ---------------------------------------------------------------------------
# Test: slides shape IS flagged
# ---------------------------------------------------------------------------

class TestSlidesShapeIsFlagged(unittest.TestCase):
    """The calibration case (slides, fixed pre-branch) must still be detected.

    The slides duplicate's local method had:
      shared = {build_agentic_capsule, emit_agentic_context, getvalue, assertEqual}
      similarity >= 0.45

    This fixture reproduces that shape with a separate class in the same file,
    ensuring the threshold (sim >= 0.45 AND shared >= 3) catches it.
    """

    def test_flagged(self):
        # The local method calls the same domain API functions as the mixin:
        # emit_agentic_context, build_agentic_capsule, getvalue, assertEqual.
        # sim = |shared| / |union|.  We keep it above SIMILARITY_THRESHOLD.
        local = """
        class TestFakeDomain(unittest.TestCase):
            def test_emit_output_matches_builder(self):
                buf = StringIO()
                with redirect_stdout(buf):
                    emit_agentic_context()
                self.assertEqual(buf.getvalue().strip(), build_agentic_capsule().strip())
        """
        test_src = _ADOPTER + "\n" + textwrap.dedent(local)
        with _TmpRepo(_SLIDES_MIXIN, test_src):
            findings = scan()

        match = [
            f for f in findings
            if f["local_method"] == "test_emit_output_matches_builder"
        ]
        self.assertGreater(
            len(match),
            0,
            msg=f"Expected finding for slides shape but got none. findings={findings}",
        )
        self.assertGreaterEqual(match[0]["similarity"], SIMILARITY_THRESHOLD)
        self.assertGreaterEqual(match[0]["shared_call_count"], MIN_SHARED_CALLS)


# ---------------------------------------------------------------------------
# Test: app-unique test sharing one helper is NOT flagged
# ---------------------------------------------------------------------------

class TestOneSharedCallNotFlagged(unittest.TestCase):
    """A local test that shares only assertIn and build_agentic_capsule is not reported.

    This is the charts false-positive pattern: shared_call_count == 2 < 3.
    """

    def test_not_flagged(self):
        mixin = """
        class FakeContractMixin:
            def test_capsule_declares_a_purpose(self):
                capsule = build_agentic_capsule()
                self.assertIn("purpose:", capsule)
        """
        local = """
        class TestFakeCapsuleContent(unittest.TestCase):
            def test_contains_render_command(self):
                capsule = build_agentic_capsule()
                self.assertIn("render", capsule)

            def test_contains_grid_command(self):
                capsule = build_agentic_capsule()
                self.assertIn("grid", capsule)
        """
        test_src = _ADOPTER + "\n" + textwrap.dedent(local)
        with _TmpRepo(textwrap.dedent(mixin), test_src):
            findings = scan()

        content_findings = [
            f for f in findings
            if f["local_method"].startswith("test_contains_")
        ]
        self.assertEqual(
            content_findings,
            [],
            msg=f"App-specific content tests must not be flagged: {content_findings}",
        )


# ---------------------------------------------------------------------------
# Test: override is NOT flagged
# ---------------------------------------------------------------------------

class TestOverrideNotFlagged(unittest.TestCase):
    """A method with the same name as a mixin method must not be flagged.

    A non-adopting class in the same file may define a method named
    ``test_capsule_declares_a_purpose`` to test stricter assertions.  The
    detector must not treat this as a duplicate of the mixin method with the
    same name -- overrides are intentional.
    """

    def test_not_flagged(self):
        mixin = """
        class FakeContractMixin:
            def test_capsule_declares_a_purpose(self):
                capsule = build_agentic_capsule()
                self.assertIn("purpose:", capsule)

            def test_emit_accepts_the_shared_positional_signature(self):
                buf = StringIO()
                with redirect_stdout(buf):
                    rc = emit_agentic_context("yaml", True)
                self.assertEqual(rc, 0)
        """
        # A class that has the SAME METHOD NAME as a mixin method but does
        # NOT inherit the mixin.  The detector must skip it (override rule).
        local = """
        class TestFakeDomain(unittest.TestCase):
            def test_capsule_declares_a_purpose(self):
                capsule = build_agentic_capsule()
                self.assertIn("purpose:", capsule)
                self.assertIn("my-domain", capsule)
        """
        test_src = _ADOPTER + "\n" + textwrap.dedent(local)
        with _TmpRepo(textwrap.dedent(mixin), test_src):
            findings = scan()

        override_findings = [
            f for f in findings
            if f["local_method"] == "test_capsule_declares_a_purpose"
        ]
        self.assertEqual(
            override_findings,
            [],
            msg=f"Override must not be flagged: {override_findings}",
        )


# ---------------------------------------------------------------------------
# Unit tests: _calls, _uses_mocking, _jaccard
# ---------------------------------------------------------------------------

def _parse_method(src: str) -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    raise AssertionError("no function found in src")


class TestCallsHelper(unittest.TestCase):
    """_calls extracts function/method names from a method body."""

    def test_bare_call(self):
        m = _parse_method("def f():\n    foo()\n")
        self.assertIn("foo", _calls(m))

    def test_method_call(self):
        m = _parse_method("def f():\n    self.assertIn(x, y)\n")
        self.assertIn("assertIn", _calls(m))

    def test_self_excluded(self):
        # 'self' is a Name in self.assertEqual(...) but must not appear in _calls.
        m = _parse_method("def f():\n    self.assertEqual(a, b)\n")
        self.assertNotIn("self", _calls(m))

    def test_chained_call(self):
        m = _parse_method("def f():\n    buf.getvalue()\n")
        self.assertIn("getvalue", _calls(m))


class TestUsesMocking(unittest.TestCase):
    """_uses_mocking detects patch, patch.object, MagicMock, etc."""

    def test_patch_object_detected(self):
        m = _parse_method("""\
            def f():
                with patch.object(mod, '_x', return_value=False):
                    cap = build_agentic_capsule()
                self.assertIsInstance(cap, str)
        """)
        self.assertTrue(_uses_mocking(m))

    def test_bare_patch_detected(self):
        m = _parse_method("""\
            def f():
                with patch('mod._x', return_value=False):
                    cap = build_agentic_capsule()
        """)
        self.assertTrue(_uses_mocking(m))

    def test_magicmock_detected(self):
        m = _parse_method("""\
            def f():
                m = MagicMock()
                m.return_value = "x"
        """)
        self.assertTrue(_uses_mocking(m))

    def test_no_mocking(self):
        m = _parse_method("""\
            def f():
                buf = StringIO()
                with redirect_stdout(buf):
                    rc = emit_agentic_context("yaml", True)
                self.assertEqual(rc, 0)
        """)
        self.assertFalse(_uses_mocking(m))


class TestJaccard(unittest.TestCase):
    def test_identical_sets(self):
        s = frozenset({"a", "b", "c"})
        self.assertAlmostEqual(_jaccard(s, s), 1.0)

    def test_disjoint_sets(self):
        self.assertAlmostEqual(_jaccard(frozenset({"a"}), frozenset({"b"})), 0.0)

    def test_empty_sets(self):
        self.assertAlmostEqual(_jaccard(frozenset(), frozenset()), 0.0)

    def test_partial_overlap(self):
        a = frozenset({"a", "b", "c"})
        b = frozenset({"b", "c", "d"})
        # intersection 2, union 4 -> 0.5
        self.assertAlmostEqual(_jaccard(a, b), 0.5)


if __name__ == "__main__":
    unittest.main()
