"""Tests for workflow include: fragment support.

Covers:
- Fragment parsing validation
- Stage prefixing and name rewriting
- depends_on and reads_from override on the first fragment stage
- Error cases (missing file, not-a-fragment, missing stages)
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from workflow.compiler import compile_workflow
from workflow.linter import lint_workflow
from workflow.parser import WorkflowParseError, parse_workflow_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_fragment(extra_stage_yaml: str = "") -> str:
    """Return a minimal fragment YAML with one stage."""
    return textwrap.dedent(f"""\
        fragment: true
        stages:
          - name: validate
            kind: validate
            description: Validate output
            agent:
              role: reviewer
          - name: correct
            kind: execute
            description: Apply corrections
            agent:
              role: code-writer
            depends_on: [validate]
            reads_from: [validate]
          - name: recheck
            kind: validate
            description: Recheck after corrections
            agent:
              role: reviewer
            depends_on: [correct]
            reads_from: [correct, validate]
        {extra_stage_yaml}
    """)


def _workflow_with_fragment(
    frag_path: str,
    prefix: str = "vc",
    depends_on: list[str] | None = None,
    reads_from: list[str] | None = None,
) -> str:
    dep_list = depends_on or ["compose"]
    rf_list = reads_from or ["compose"]
    dep_yaml = "[" + ", ".join(dep_list) + "]"
    rf_yaml = "[" + ", ".join(rf_list) + "]"
    return textwrap.dedent(f"""\
        name: test-include
        version: "1.0"
        description: Workflow with include
        trigger:
          source: manual
        stages:
          - name: compose
            kind: execute
            description: Generate output
            agent:
              role: doc-writer
        include:
          - path: {frag_path}
            prefix: {prefix}
            depends_on: {dep_yaml}
            reads_from: {rf_yaml}
    """)


# ---------------------------------------------------------------------------
# Fragment parsing validation
# ---------------------------------------------------------------------------


class TestParseFragmentValidation(unittest.TestCase):
    def test_missing_fragment_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            yaml = _workflow_with_fragment(str(tmp_path / "nonexistent.yaml"))
            with self.assertRaisesRegex(WorkflowParseError, "missing fragment file"):
                parse_workflow_str(yaml, source="workflows/test.yaml")

    def test_fragment_without_fragment_true_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "not-a-fragment.yaml"
            frag.write_text(
                textwrap.dedent("""\
                    stages:
                      - name: x
                        kind: gather
                        description: test
                        agent:
                          role: researcher
                """)
            )
            yaml = _workflow_with_fragment(str(frag))
            with self.assertRaisesRegex(WorkflowParseError, "fragment: true"):
                parse_workflow_str(yaml, source="workflows/test.yaml")

    def test_fragment_without_stages_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "empty-fragment.yaml"
            frag.write_text("fragment: true\n")
            yaml = _workflow_with_fragment(str(frag))
            with self.assertRaisesRegex(WorkflowParseError, "fragment missing required key 'stages'"):
                parse_workflow_str(yaml, source="workflows/test.yaml")


# ---------------------------------------------------------------------------
# Stage name prefixing
# ---------------------------------------------------------------------------


class TestStageNamePrefixing(unittest.TestCase):
    def _parse_with_fragment(self, tmp_path: Path) -> object:
        frag = tmp_path / "validate-and-correct.yaml"
        frag.write_text(_minimal_fragment())
        yaml = _workflow_with_fragment(str(frag), prefix="vc")
        return parse_workflow_str(yaml, source="workflows/test.yaml")

    def test_fragment_stage_names_are_prefixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            wf = self._parse_with_fragment(tmp_path)
            names = [s.name for s in wf.stages]
            self.assertIn("vc-validate", names)
            self.assertIn("vc-correct", names)
            self.assertIn("vc-recheck", names)

    def test_original_stage_name_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            wf = self._parse_with_fragment(tmp_path)
            names = [s.name for s in wf.stages]
            self.assertNotIn("validate", names)
            self.assertNotIn("correct", names)
            self.assertNotIn("recheck", names)

    def test_inline_stage_name_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            wf = self._parse_with_fragment(tmp_path)
            self.assertEqual(wf.stages[0].name, "compose")

    def test_total_stage_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            wf = self._parse_with_fragment(tmp_path)
            # 1 inline + 3 from fragment
            self.assertEqual(len(wf.stages), 4)


# ---------------------------------------------------------------------------
# depends_on override on first fragment stage
# ---------------------------------------------------------------------------


class TestDependsOnOverride(unittest.TestCase):
    def test_first_stage_depends_on_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "frag.yaml"
            frag.write_text(_minimal_fragment())
            yaml = _workflow_with_fragment(str(frag), depends_on=["compose"])
            wf = parse_workflow_str(yaml, source="workflows/test.yaml")
            stage_map = {s.name: s for s in wf.stages}
            self.assertEqual(stage_map["vc-validate"].depends_on, ("compose",))

    def test_subsequent_fragment_stages_not_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "frag.yaml"
            frag.write_text(_minimal_fragment())
            yaml = _workflow_with_fragment(str(frag), depends_on=["compose"])
            wf = parse_workflow_str(yaml, source="workflows/test.yaml")
            stage_map = {s.name: s for s in wf.stages}
            # vc-correct depends on vc-validate (intra-fragment, not compose)
            self.assertEqual(stage_map["vc-correct"].depends_on, ("vc-validate",))

    def test_first_stage_depends_on_empty_when_not_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "frag.yaml"
            frag.write_text(
                textwrap.dedent("""\
                    fragment: true
                    stages:
                      - name: step
                        kind: gather
                        description: step
                        agent:
                          role: researcher
                """)
            )
            yaml = textwrap.dedent(f"""\
                name: test
                version: "1.0"
                description: test
                trigger:
                  source: manual
                stages:
                  - name: s1
                    kind: gather
                    description: first
                    agent:
                      role: researcher
                include:
                  - path: {frag}
                    prefix: x
            """)
            wf = parse_workflow_str(yaml, source="<string>")
            stage_map = {s.name: s for s in wf.stages}
            self.assertEqual(stage_map["x-step"].depends_on, ())


# ---------------------------------------------------------------------------
# reads_from override on first fragment stage
# ---------------------------------------------------------------------------


class TestReadsFromOverride(unittest.TestCase):
    def test_first_stage_reads_from_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "frag.yaml"
            frag.write_text(_minimal_fragment())
            yaml = _workflow_with_fragment(str(frag), reads_from=["compose"])
            wf = parse_workflow_str(yaml, source="workflows/test.yaml")
            stage_map = {s.name: s for s in wf.stages}
            self.assertEqual(stage_map["vc-validate"].reads_from, ("compose",))

    def test_subsequent_stage_reads_from_rewritten_with_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "frag.yaml"
            frag.write_text(_minimal_fragment())
            yaml = _workflow_with_fragment(str(frag))
            wf = parse_workflow_str(yaml, source="workflows/test.yaml")
            stage_map = {s.name: s for s in wf.stages}
            # vc-recheck reads from vc-correct and vc-validate (prefixed internal refs)
            self.assertIn("vc-correct", stage_map["vc-recheck"].reads_from)
            self.assertIn("vc-validate", stage_map["vc-recheck"].reads_from)


# ---------------------------------------------------------------------------
# Round-trip: compile a workflow with include
# ---------------------------------------------------------------------------


class TestCompileWithInclude(unittest.TestCase):
    def test_compile_workflow_with_include_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "frag.yaml"
            frag.write_text(_minimal_fragment())
            yaml = _workflow_with_fragment(str(frag), prefix="vc")
            wf = parse_workflow_str(yaml, source="workflows/test.yaml")
            manifest = compile_workflow(wf)
            self.assertEqual(len(manifest.resolved_stages), 4)

    def test_linter_reports_missing_fragment_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            wf_yaml = textwrap.dedent("""\
                name: test
                version: "1.0"
                description: test
                trigger:
                  source: manual
                stages:
                  - name: gather
                    kind: gather
                    description: Gather data
                    agent:
                      role: researcher
                include:
                  - path: workflows/shared/nonexistent-fragment.yaml
                    prefix: x
                    depends_on: [gather]
            """)
            wf_file = tmp_path / "test.yaml"
            wf_file.write_text(wf_yaml)
            result = lint_workflow(wf_file)
            self.assertFalse(result.valid)
            self.assertTrue(any("not found" in e.message for e in result.errors))


# ---------------------------------------------------------------------------
# resolve_fragment_path: cwd-relative resolution
# ---------------------------------------------------------------------------


class TestResolveFragmentPath(unittest.TestCase):
    def test_absolute_path_returned_unchanged(self) -> None:
        from workflow.include import resolve_fragment_path

        p = Path("/some/absolute/path.yaml")
        result = resolve_fragment_path(str(p), Path("/other/dir/workflow.yaml"))
        self.assertEqual(result, p)

    def test_cwd_relative_returned_when_exists(self) -> None:
        """Line 54: cwd_relative.exists() is True — return cwd_relative."""
        import os

        from workflow.include import resolve_fragment_path

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "frag.yaml"
            frag.write_text("fragment: true\nstages: []\n")
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp_path)
                result = resolve_fragment_path("frag.yaml", tmp_path / "workflow.yaml")
                self.assertEqual(result.name, "frag.yaml")
                self.assertTrue(result.exists())
            finally:
                os.chdir(old_cwd)

    def test_source_relative_returned_when_cwd_relative_missing(self) -> None:
        """Fallback: cwd_relative does not exist — fall back to source parent."""
        from workflow.include import resolve_fragment_path

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "frag.yaml"
            frag.write_text("fragment: true\nstages: []\n")
            result = resolve_fragment_path("frag.yaml", tmp_path / "workflow.yaml")
            self.assertEqual(result, tmp_path / "frag.yaml")


# ---------------------------------------------------------------------------
# parse_fragment: FileNotFoundError and OSError paths (lines 90-93)
# ---------------------------------------------------------------------------


class TestParseFragment(unittest.TestCase):
    def test_missing_file_raises_parse_error(self) -> None:
        """Lines 90-91: FileNotFoundError -> WorkflowParseError."""
        from workflow.include import parse_fragment
        from workflow.parser import WorkflowParseError

        with self.assertRaisesRegex(WorkflowParseError, "fragment file not found"):
            parse_fragment("/nonexistent/path/frag.yaml")

    def test_oserror_raises_parse_error(self) -> None:
        """Lines 92-93: OSError -> WorkflowParseError."""
        from unittest.mock import patch

        from workflow.include import parse_fragment
        from workflow.parser import WorkflowParseError

        with tempfile.TemporaryDirectory() as tmp_dir:
            frag = Path(tmp_dir) / "frag.yaml"
            frag.write_text("fragment: true\nstages: []\n")
            with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
                with self.assertRaisesRegex(WorkflowParseError, "cannot read fragment"):
                    parse_fragment(str(frag))


# ---------------------------------------------------------------------------
# _parse_fragment_str: error branches (lines 115-116, 119, 131)
# ---------------------------------------------------------------------------


class TestParseFragmentStr(unittest.TestCase):
    def test_invalid_yaml_raises(self) -> None:
        """Lines 115-116: YAML parse error."""
        from workflow.include import _parse_fragment_str
        from workflow.parser import WorkflowParseError

        bad_yaml = ":\n  - invalid: [unclosed"
        with self.assertRaisesRegex(WorkflowParseError, "invalid YAML"):
            _parse_fragment_str(bad_yaml, source="test.yaml")

    def test_non_mapping_top_level_raises(self) -> None:
        """Line 119: top-level is a list, not a dict."""
        from workflow.include import _parse_fragment_str
        from workflow.parser import WorkflowParseError

        with self.assertRaisesRegex(WorkflowParseError, "expected a YAML mapping"):
            _parse_fragment_str("- item1\n- item2\n", source="test.yaml")

    def test_empty_stages_list_raises(self) -> None:
        """Line 131: stages is an empty list."""
        from workflow.include import _parse_fragment_str
        from workflow.parser import WorkflowParseError

        content = "fragment: true\nstages: []\n"
        with self.assertRaisesRegex(WorkflowParseError, "non-empty list"):
            _parse_fragment_str(content, source="test.yaml")

    def test_stages_not_a_list_raises(self) -> None:
        """Line 130: stages is not a list at all."""
        from workflow.include import _parse_fragment_str
        from workflow.parser import WorkflowParseError

        content = "fragment: true\nstages: not-a-list\n"
        with self.assertRaisesRegex(WorkflowParseError, "non-empty list"):
            _parse_fragment_str(content, source="test.yaml")


# ---------------------------------------------------------------------------
# _require_list and _require_dict: type-check branches (lines 140, 151)
# ---------------------------------------------------------------------------


class TestRequireListAndDict(unittest.TestCase):
    def test_require_list_raises_on_non_list(self) -> None:
        """Line 140: _require_list rejects a non-list value."""
        from workflow.include import _require_list
        from workflow.parser import WorkflowParseError

        with self.assertRaisesRegex(WorkflowParseError, "must be a list"):
            _require_list("not-a-list", "depends_on", "frag.yaml", "<test>")

    def test_require_list_accepts_list(self) -> None:
        """Happy path: list passes through."""
        from workflow.include import _require_list

        result = _require_list(["a", "b"], "depends_on", "frag.yaml", "<test>")
        self.assertEqual(result, ["a", "b"])

    def test_require_list_accepts_tuple(self) -> None:
        """Happy path: tuple is also accepted."""
        from workflow.include import _require_list

        result = _require_list(("x",), "depends_on", "frag.yaml", "<test>")
        self.assertEqual(result, ["x"])

    def test_require_dict_raises_on_non_dict(self) -> None:
        """Line 151: _require_dict rejects a non-dict value."""
        from workflow.include import _require_dict
        from workflow.parser import WorkflowParseError

        with self.assertRaisesRegex(WorkflowParseError, "must be a mapping"):
            _require_dict(["not", "a", "dict"], "params", "frag.yaml", "<test>")

    def test_require_dict_accepts_dict(self) -> None:
        """Happy path: dict passes through."""
        from workflow.include import _require_dict

        result = _require_dict({"k": "v"}, "params", "frag.yaml", "<test>")
        self.assertEqual(result, {"k": "v"})


# ---------------------------------------------------------------------------
# _parse_include: validation branches (lines 163, 167)
# ---------------------------------------------------------------------------


class TestParseInclude(unittest.TestCase):
    def test_non_dict_entry_raises(self) -> None:
        """Line 163: include entry is not a dict."""
        from workflow.include import _parse_include
        from workflow.parser import WorkflowParseError

        with self.assertRaisesRegex(WorkflowParseError, "must be a mapping"):
            _parse_include("just-a-string", source="<test>")

    def test_missing_path_key_raises(self) -> None:
        """Line 167: include entry dict has no 'path' key."""
        from workflow.include import _parse_include
        from workflow.parser import WorkflowParseError

        with self.assertRaisesRegex(WorkflowParseError, "missing required key 'path'"):
            _parse_include({"prefix": "x"}, source="<test>")

    def test_valid_entry_returns_include_spec(self) -> None:
        """Happy path: minimal valid include entry."""
        from workflow.include import _parse_include
        from workflow.models import IncludeSpec

        result = _parse_include({"path": "shared/frag.yaml"}, source="<test>")
        self.assertIsInstance(result, IncludeSpec)
        self.assertEqual(result.path, "shared/frag.yaml")
        self.assertEqual(result.prefix, "frag")  # stem of filename

    def test_depends_on_not_a_list_raises(self) -> None:
        """_require_list path via depends_on field."""
        from workflow.include import _parse_include
        from workflow.parser import WorkflowParseError

        with self.assertRaisesRegex(WorkflowParseError, "must be a list"):
            _parse_include({"path": "x.yaml", "depends_on": "not-a-list"}, source="<test>")

    def test_params_not_a_dict_raises(self) -> None:
        """_require_dict path via params field."""
        from workflow.include import _parse_include
        from workflow.parser import WorkflowParseError

        with self.assertRaisesRegex(WorkflowParseError, "must be a mapping"):
            _parse_include({"path": "x.yaml", "params": ["not", "a", "dict"]}, source="<test>")


# ---------------------------------------------------------------------------
# _load_frag_text: OSError path (lines 203-204)
# ---------------------------------------------------------------------------


class TestLoadFragText(unittest.TestCase):
    def test_oserror_raises_parse_error(self) -> None:
        """Lines 203-204: OSError on read -> WorkflowParseError."""
        from unittest.mock import patch

        from workflow.include import _load_frag_text
        from workflow.parser import WorkflowParseError

        with tempfile.TemporaryDirectory() as tmp_dir:
            frag_path = Path(tmp_dir) / "frag.yaml"
            frag_path.write_text("content")
            with patch.object(Path, "read_text", side_effect=OSError("disk error")):
                with self.assertRaisesRegex(WorkflowParseError, "cannot read fragment"):
                    _load_frag_text(frag_path, source="<test>")

    def test_missing_file_raises_parse_error(self) -> None:
        """FileNotFoundError -> WorkflowParseError."""
        from workflow.include import _load_frag_text
        from workflow.parser import WorkflowParseError

        missing = Path("/nonexistent/path/frag.yaml")
        with self.assertRaisesRegex(WorkflowParseError, "missing fragment file"):
            _load_frag_text(missing, source="<test>")


# ---------------------------------------------------------------------------
# _rewrite_fan_out: lines 256-259
# ---------------------------------------------------------------------------


class TestRewriteFanOut(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        """Lines 254-255: None fan_out returns None."""
        from workflow.include import _rewrite_fan_out

        result = _rewrite_fan_out(None, {"old": "new"})
        self.assertIsNone(result)

    def test_source_not_in_rename_map_returns_original(self) -> None:
        """Lines 256-258: source not in rename map — return original fan_out unchanged."""
        from workflow.include import _rewrite_fan_out
        from workflow.models import FanOutSpec

        fan_out = FanOutSpec(source="external-stage", field="items", key="name")
        result = _rewrite_fan_out(fan_out, {"old-stage": "prefix-old-stage"})
        self.assertIs(result, fan_out)

    def test_source_in_rename_map_returns_new_fan_out(self) -> None:
        """Line 259: source IS in rename map — return new FanOutSpec with updated source."""
        from workflow.include import _rewrite_fan_out
        from workflow.models import FanOutSpec

        fan_out = FanOutSpec(source="gather", field="items", key="name")
        rename = {"gather": "prefix-gather"}
        result = _rewrite_fan_out(fan_out, rename)
        self.assertIsNotNone(result)
        self.assertEqual(result.source, "prefix-gather")
        self.assertEqual(result.field, "items")
        self.assertEqual(result.key, "name")


# ---------------------------------------------------------------------------
# _expand_includes: circular include detection (line 281)
# ---------------------------------------------------------------------------


class TestExpandIncludesCircularDetection(unittest.TestCase):
    def test_circular_include_raises(self) -> None:
        """Line 281: circular include detected when visited set contains fragment path."""
        from workflow.include import FragmentContext, _expand_includes
        from workflow.models import IncludeSpec
        from workflow.parser import WorkflowParseError

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag_a = tmp_path / "frag_a.yaml"
            frag_a.write_text(textwrap.dedent("""\
                fragment: true
                stages:
                  - name: step-a
                    kind: gather
                    description: Step A
                    agent:
                      role: researcher
            """))
            inc = IncludeSpec(
                path=str(frag_a), prefix="a", depends_on=(), reads_from=(), params={}
            )
            ctx = FragmentContext(source="<test>", source_path=tmp_path / "workflow.yaml")
            # Pre-seed visited with frag_a's resolved key to trigger circular detection
            already_visited = frozenset([str(frag_a.resolve())])

            with self.assertRaisesRegex(WorkflowParseError, "circular include"):
                _expand_includes((), (inc,), ctx, _visited=already_visited)


# ---------------------------------------------------------------------------
# _expand_includes: nested includes (line 291)
# ---------------------------------------------------------------------------


class TestExpandIncludesNested(unittest.TestCase):
    def test_nested_include_expanded(self) -> None:
        """Line 291: frag_raw_includes is non-empty -> recursive _expand_includes."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            inner_frag = tmp_path / "inner.yaml"
            inner_frag.write_text(textwrap.dedent("""\
                fragment: true
                stages:
                  - name: inner-step
                    kind: gather
                    description: Inner step
                    agent:
                      role: researcher
            """))

            outer_frag = tmp_path / "outer.yaml"
            outer_frag.write_text(textwrap.dedent(f"""\
                fragment: true
                include:
                  - path: {inner_frag}
                    prefix: inner
                stages:
                  - name: outer-step
                    kind: gather
                    description: Outer step
                    agent:
                      role: researcher
            """))

            workflow_yaml = textwrap.dedent(f"""\
                name: test-nested
                version: "1.0"
                description: Test nested includes
                trigger:
                  source: manual
                stages:
                  - name: root-step
                    kind: gather
                    description: Root step
                    agent:
                      role: researcher
                include:
                  - path: {outer_frag}
                    prefix: outer
                    depends_on: [root-step]
            """)
            from workflow.parser import parse_workflow_str

            wf = parse_workflow_str(workflow_yaml, source="<test>")
            names = [s.name for s in wf.stages]
            self.assertIn("root-step", names)
            self.assertTrue(any("outer" in n for n in names))
            self.assertTrue(any("inner" in n for n in names))


# ---------------------------------------------------------------------------
# _parse_nested_includes: error branches (lines 308-309, 312, 317-325)
# ---------------------------------------------------------------------------


class TestParseNestedIncludes(unittest.TestCase):
    def test_invalid_yaml_returns_empty(self) -> None:
        """Lines 308-309: YAML parse error -> return ()."""
        from workflow.include import _parse_nested_includes

        result = _parse_nested_includes(":\n  - [unclosed", source="test.yaml")
        self.assertEqual(result, ())

    def test_non_dict_top_level_returns_empty(self) -> None:
        """Line 312: not a dict -> return ()."""
        from workflow.include import _parse_nested_includes

        result = _parse_nested_includes("- item1\n- item2\n", source="test.yaml")
        self.assertEqual(result, ())

    def test_no_include_key_returns_empty(self) -> None:
        """Line 315-316: include key absent -> return ()."""
        from workflow.include import _parse_nested_includes

        result = _parse_nested_includes("fragment: true\nstages: []\n", source="test.yaml")
        self.assertEqual(result, ())

    def test_include_not_a_list_raises(self) -> None:
        """Lines 317-320: include is not a list -> raise WorkflowParseError."""
        from workflow.include import _parse_nested_includes
        from workflow.parser import WorkflowParseError

        content = "fragment: true\ninclude: not-a-list\nstages: []\n"
        with self.assertRaisesRegex(WorkflowParseError, "'include' must be a list"):
            _parse_nested_includes(content, source="test.yaml")

    def test_empty_include_list_returns_empty(self) -> None:
        """Lines 322-323: include is empty list -> return ()."""
        from workflow.include import _parse_nested_includes

        content = "fragment: true\ninclude: []\nstages: []\n"
        result = _parse_nested_includes(content, source="test.yaml")
        self.assertEqual(result, ())

    def test_valid_include_list_returns_specs(self) -> None:
        """Line 325: valid include entries -> tuple of IncludeSpec."""
        from workflow.include import _parse_nested_includes
        from workflow.models import IncludeSpec

        content = textwrap.dedent("""\
            fragment: true
            include:
              - path: shared/helper.yaml
                prefix: h
            stages: []
        """)
        result = _parse_nested_includes(content, source="test.yaml")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], IncludeSpec)
        self.assertEqual(result[0].path, "shared/helper.yaml")


# ---------------------------------------------------------------------------
# extract_include_entries: YAML error and non-dict cases
# ---------------------------------------------------------------------------


class TestExtractIncludeEntries(unittest.TestCase):
    def test_invalid_yaml_returns_empty(self) -> None:
        from workflow.include import extract_include_entries

        result = extract_include_entries(":\n  - [unclosed")
        self.assertEqual(result, [])

    def test_non_dict_returns_empty(self) -> None:
        from workflow.include import extract_include_entries

        result = extract_include_entries("- item1\n- item2\n")
        self.assertEqual(result, [])

    def test_include_not_a_list_returns_empty(self) -> None:
        from workflow.include import extract_include_entries

        result = extract_include_entries("include: not-a-list\n")
        self.assertEqual(result, [])

    def test_valid_include_list_returned(self) -> None:
        from workflow.include import extract_include_entries

        content = "include:\n  - path: shared/frag.yaml\n"
        result = extract_include_entries(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["path"], "shared/frag.yaml")


if __name__ == "__main__":
    unittest.main()
