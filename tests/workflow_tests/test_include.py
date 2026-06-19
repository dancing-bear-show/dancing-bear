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


if __name__ == "__main__":
    unittest.main()
