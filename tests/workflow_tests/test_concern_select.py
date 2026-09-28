"""Tests for workflow.concern_select — canonical guide selector.

Covers:
- Each glob rule (extension, test files, SKILL.md, iOS, slides)
- resume-copy override (suppresses generic .yaml rule)
- task_type rules
- always-include (patterns.md always present)
- unknown extension → only patterns.md
- deduplication and order
- Every concerns/*.md (except README.md) is reachable by some rule
- selection.yaml references only guides that exist
- CLI subcommand: json output and exit codes
- Guard: thread-fixer.md, code-review-swarm.yaml, load-concerns.yaml each
  reference ``select-concerns`` (so nobody reintroduces a hand-written table)
"""

from __future__ import annotations

import argparse
import json
import re as _re
import tempfile
import unittest
from pathlib import Path

from workflow.concern_select import (
    all_concern_guides,
    reachable_guides,
    select_guides,
    select_guides_with_reasons,
)
from workflow.cli_dispatch_review import _cmd_select_concerns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(**kwargs) -> argparse.Namespace:
    """Build a minimal Namespace for _cmd_select_concerns."""
    defaults = {
        "paths": [],
        "paths_file": "",
        "task_type": "",
        "format": "text",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# select_guides: always-include
# ---------------------------------------------------------------------------


class TestAlwaysInclude(unittest.TestCase):
    def test_patterns_always_included_for_py(self) -> None:
        guides = select_guides(paths=["src/foo.py"])
        self.assertIn("patterns.md", guides)

    def test_patterns_always_included_for_yaml(self) -> None:
        guides = select_guides(paths=["workflows/foo.yaml"])
        self.assertIn("patterns.md", guides)

    def test_patterns_always_included_with_no_input(self) -> None:
        guides = select_guides()
        self.assertIn("patterns.md", guides)

    def test_patterns_appears_once(self) -> None:
        guides = select_guides(paths=["src/foo.py", "workflows/bar.yaml"])
        self.assertEqual(guides.count("patterns.md"), 1)


# ---------------------------------------------------------------------------
# select_guides: Python source files
# ---------------------------------------------------------------------------


class TestPythonRule(unittest.TestCase):
    def test_py_adds_correctness(self) -> None:
        guides = select_guides(paths=["src/mail/cli.py"])
        self.assertIn("correctness.md", guides)

    def test_py_adds_security(self) -> None:
        guides = select_guides(paths=["src/mail/cli.py"])
        self.assertIn("security.md", guides)

    def test_py_adds_tests(self) -> None:
        guides = select_guides(paths=["src/mail/cli.py"])
        self.assertIn("tests.md", guides)

    def test_py_adds_reuse(self) -> None:
        guides = select_guides(paths=["src/mail/cli.py"])
        self.assertIn("reuse.md", guides)

    def test_py_adds_complexity(self) -> None:
        guides = select_guides(paths=["src/mail/cli.py"])
        self.assertIn("complexity.md", guides)


# ---------------------------------------------------------------------------
# select_guides: test files
# ---------------------------------------------------------------------------


class TestTestFileRule(unittest.TestCase):
    def test_tests_tree_adds_tests_md(self) -> None:
        guides = select_guides(paths=["tests/mail_tests/test_foo.py"])
        self.assertIn("tests.md", guides)

    def test_test_underscore_file_adds_tests_md(self) -> None:
        guides = select_guides(paths=["src/mail/test_helpers.py"])
        self.assertIn("tests.md", guides)

    def test_tests_tree_also_adds_correctness(self) -> None:
        guides = select_guides(paths=["tests/workflow_tests/test_cli.py"])
        self.assertIn("correctness.md", guides)


# ---------------------------------------------------------------------------
# select_guides: YAML/YML workflow files
# ---------------------------------------------------------------------------


class TestYamlRule(unittest.TestCase):
    def test_yaml_adds_workflow(self) -> None:
        guides = select_guides(paths=["workflows/my-flow.yaml"])
        self.assertIn("workflow.md", guides)

    def test_yaml_adds_workflow_stages(self) -> None:
        guides = select_guides(paths=["workflows/my-flow.yaml"])
        self.assertIn("workflow-stages.md", guides)

    def test_yaml_adds_workflow_fanout(self) -> None:
        guides = select_guides(paths=["workflows/my-flow.yaml"])
        self.assertIn("workflow-fanout.md", guides)

    def test_yaml_adds_workflow_fragments(self) -> None:
        guides = select_guides(paths=["workflows/my-flow.yaml"])
        self.assertIn("workflow-fragments.md", guides)

    def test_yml_extension_also_matches(self) -> None:
        guides = select_guides(paths=["workflows/my-flow.yml"])
        self.assertIn("workflow.md", guides)

    def test_yaml_adds_patterns(self) -> None:
        guides = select_guides(paths=["workflows/my-flow.yaml"])
        self.assertIn("patterns.md", guides)


# ---------------------------------------------------------------------------
# select_guides: SKILL.md
# ---------------------------------------------------------------------------


class TestSkillMdRule(unittest.TestCase):
    def test_skill_md_adds_docs(self) -> None:
        guides = select_guides(paths=[".claude/skills/code-review/SKILL.md"])
        self.assertIn("docs.md", guides)

    def test_skill_md_adds_workflow(self) -> None:
        guides = select_guides(paths=["SKILL.md"])
        self.assertIn("workflow.md", guides)

    def test_skill_md_adds_workflow_stages(self) -> None:
        guides = select_guides(paths=["SKILL.md"])
        self.assertIn("workflow-stages.md", guides)


# ---------------------------------------------------------------------------
# select_guides: Markdown / README
# ---------------------------------------------------------------------------


class TestMarkdownRule(unittest.TestCase):
    def test_md_adds_docs(self) -> None:
        guides = select_guides(paths=["docs/DESIGN.md"])
        self.assertIn("docs.md", guides)

    def test_readme_no_ext_adds_docs(self) -> None:
        guides = select_guides(paths=["src/mail/README"])
        self.assertIn("docs.md", guides)


# ---------------------------------------------------------------------------
# select_guides: resume-copy override
# ---------------------------------------------------------------------------


class TestResumeCopyOverride(unittest.TestCase):
    """Resume config/example yaml paths get resume-copy.md, NOT the workflow set."""

    def test_resume_config_adds_resume_copy(self) -> None:
        guides = select_guides(paths=["src/resume/config/profiles/bcs.yaml"])
        self.assertIn("resume-copy.md", guides)

    def test_resume_config_does_not_add_workflow(self) -> None:
        guides = select_guides(paths=["src/resume/config/profiles/bcs.yaml"])
        self.assertNotIn("workflow.md", guides)

    def test_resume_examples_adds_resume_copy(self) -> None:
        guides = select_guides(paths=["src/resume/examples/sample.yaml"])
        self.assertIn("resume-copy.md", guides)

    def test_linkedin_yaml_adds_resume_copy(self) -> None:
        guides = select_guides(paths=["linkedin-profile.yaml"])
        self.assertIn("resume-copy.md", guides)

    def test_linkedin_yml_adds_resume_copy(self) -> None:
        guides = select_guides(paths=["linkedin-export.yml"])
        self.assertIn("resume-copy.md", guides)

    def test_non_resume_yaml_does_not_add_resume_copy(self) -> None:
        guides = select_guides(paths=["workflows/code/my-flow.yaml"])
        self.assertNotIn("resume-copy.md", guides)

    def test_mixed_resume_and_workflow_yaml_adds_both_sets(self) -> None:
        """When a diff touches both resume config AND a workflow YAML, both sets load."""
        guides = select_guides(
            paths=[
                "src/resume/config/profiles/bcs.yaml",
                "workflows/code/my-flow.yaml",
            ]
        )
        self.assertIn("resume-copy.md", guides)
        self.assertIn("workflow.md", guides)


# ---------------------------------------------------------------------------
# select_guides: iOS layout
# ---------------------------------------------------------------------------


class TestIosLayoutRule(unittest.TestCase):
    def test_ios_iconlayout_json_adds_phone_layout(self) -> None:
        guides = select_guides(paths=["out/ios.iconlayout.json"])
        self.assertIn("phone-layout.md", guides)

    def test_out_ios_prefix_adds_phone_layout(self) -> None:
        guides = select_guides(paths=["out/ios-layout-backup.json"])
        self.assertIn("phone-layout.md", guides)

    def test_src_phone_adds_phone_layout(self) -> None:
        guides = select_guides(paths=["src/phone/cli.py"])
        self.assertIn("phone-layout.md", guides)


# ---------------------------------------------------------------------------
# select_guides: slides
# ---------------------------------------------------------------------------


class TestSlidesRule(unittest.TestCase):
    def test_src_slides_adds_slides_yaml(self) -> None:
        guides = select_guides(paths=["src/slides/schema.py"])
        self.assertIn("slides-yaml.md", guides)

    def test_pptx_adds_slides_yaml(self) -> None:
        guides = select_guides(paths=["out/deck.pptx"])
        self.assertIn("slides-yaml.md", guides)


# ---------------------------------------------------------------------------
# select_guides: task_type rules
# ---------------------------------------------------------------------------


class TestTaskTypeRules(unittest.TestCase):
    def test_feature_adds_correctness(self) -> None:
        guides = select_guides(task_type="feature")
        self.assertIn("correctness.md", guides)

    def test_feature_adds_security(self) -> None:
        guides = select_guides(task_type="feature")
        self.assertIn("security.md", guides)

    def test_feature_adds_reuse(self) -> None:
        guides = select_guides(task_type="feature")
        self.assertIn("reuse.md", guides)

    def test_test_type_adds_tests_md(self) -> None:
        guides = select_guides(task_type="test")
        self.assertIn("tests.md", guides)

    def test_security_type_adds_security(self) -> None:
        guides = select_guides(task_type="security")
        self.assertIn("security.md", guides)

    def test_docs_type_adds_docs(self) -> None:
        guides = select_guides(task_type="docs")
        self.assertIn("docs.md", guides)

    def test_refactor_adds_complexity(self) -> None:
        guides = select_guides(task_type="refactor")
        self.assertIn("complexity.md", guides)

    def test_refactor_adds_reuse(self) -> None:
        guides = select_guides(task_type="refactor")
        self.assertIn("reuse.md", guides)

    def test_workflow_type_adds_workflow_stages(self) -> None:
        guides = select_guides(task_type="workflow")
        self.assertIn("workflow-stages.md", guides)

    def test_task_type_unioned_with_paths(self) -> None:
        guides = select_guides(paths=["src/foo.py"], task_type="docs")
        self.assertIn("correctness.md", guides)
        self.assertIn("docs.md", guides)


# ---------------------------------------------------------------------------
# select_guides: unknown extension → only patterns.md (from always)
# ---------------------------------------------------------------------------


class TestUnknownExtension(unittest.TestCase):
    def test_unknown_ext_gets_only_patterns(self) -> None:
        guides = select_guides(paths=["data/file.csv"])
        self.assertEqual(guides, ["patterns.md"])

    def test_no_input_returns_defaults(self) -> None:
        guides = select_guides()
        self.assertIn("correctness.md", guides)
        self.assertIn("patterns.md", guides)


# ---------------------------------------------------------------------------
# select_guides: deduplication and order
# ---------------------------------------------------------------------------


class TestDedup(unittest.TestCase):
    def test_no_duplicates_with_many_py_files(self) -> None:
        guides = select_guides(
            paths=["src/a.py", "src/b.py", "tests/test_a.py"]
        )
        self.assertEqual(len(guides), len(set(guides)))

    def test_patterns_first_from_always(self) -> None:
        guides = select_guides(paths=["src/a.py"])
        # patterns.md is in the always list → should appear before anything
        # that comes only from glob rules
        self.assertEqual(guides[0], "patterns.md")


# ---------------------------------------------------------------------------
# select_guides_with_reasons: matched field
# ---------------------------------------------------------------------------


class TestSelectGuidesWithReasons(unittest.TestCase):
    def test_returns_dict_of_guide_to_reasons(self) -> None:
        result = select_guides_with_reasons(paths=["src/foo.py"])
        self.assertIsInstance(result, dict)
        for guide, reasons in result.items():
            self.assertIsInstance(guide, str)
            self.assertIsInstance(reasons, list)
            self.assertGreaterEqual(len(reasons), 1)

    def test_always_reason_for_patterns(self) -> None:
        result = select_guides_with_reasons(paths=["src/foo.py"])
        self.assertIn("always", result.get("patterns.md", []))


# ---------------------------------------------------------------------------
# Catalogue: every guide is reachable
# ---------------------------------------------------------------------------


class TestCatalogueCompleteness(unittest.TestCase):
    def test_every_guide_is_reachable(self) -> None:
        """Every concerns/*.md (except README.md) must be reachable by some rule."""
        all_guides = set(all_concern_guides())
        reachable = reachable_guides()
        unreachable = all_guides - reachable
        self.assertEqual(
            unreachable,
            set(),
            f"These guides exist in concerns/ but no rule in selection.yaml reaches them: "
            f"{sorted(unreachable)}",
        )

    def test_selection_yaml_references_only_existing_guides(self) -> None:
        """selection.yaml must not reference guides that do not exist."""
        concerns_dir = Path(__file__).parent.parent.parent / "concerns"
        existing = {p.name for p in concerns_dir.iterdir() if p.suffix == ".md"}
        reachable = reachable_guides()
        missing = reachable - existing
        self.assertEqual(
            missing,
            set(),
            f"selection.yaml references these non-existent guides: {sorted(missing)}",
        )


# ---------------------------------------------------------------------------
# CLI: _cmd_select_concerns exit codes and output
# ---------------------------------------------------------------------------


class TestCmdSelectConcerns(unittest.TestCase):
    def test_text_format_prints_one_guide_per_line(self) -> None:
        args = _make_args(paths=["src/foo.py"], format="text")
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _cmd_select_concerns(args)
        self.assertEqual(rc, 0)
        lines = [line for line in buf.getvalue().splitlines() if line.strip()]
        self.assertGreater(len(lines), 0)
        for line in lines:
            self.assertTrue(line.endswith(".md"), f"unexpected line: {line!r}")

    def test_json_format_returns_guides_and_matched(self) -> None:
        args = _make_args(paths=["src/foo.py"], format="json")
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _cmd_select_concerns(args)
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("guides", data)
        self.assertIn("matched", data)
        self.assertIsInstance(data["guides"], list)
        self.assertIsInstance(data["matched"], dict)

    def test_missing_paths_file_returns_exit_1(self) -> None:
        args = _make_args(paths_file="/tmp/does-not-exist-abcdef.txt")  # nosec B108 - test path
        import io
        from contextlib import redirect_stderr

        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = _cmd_select_concerns(args)
        self.assertEqual(rc, 1)

    def test_paths_file_is_read(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("src/foo.py\n")
            fh.write("workflows/bar.yaml\n")
            tmp_path = fh.name

        import io
        from contextlib import redirect_stdout

        try:
            args = _make_args(paths_file=tmp_path, format="json")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = _cmd_select_concerns(args)
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertIn("correctness.md", data["guides"])
            self.assertIn("workflow.md", data["guides"])
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_task_type_passed_through(self) -> None:
        args = _make_args(task_type="security", format="json")
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _cmd_select_concerns(args)
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("security.md", data["guides"])

    def test_no_paths_no_task_type_returns_defaults(self) -> None:
        args = _make_args(format="json")
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _cmd_select_concerns(args)
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("correctness.md", data["guides"])
        self.assertIn("patterns.md", data["guides"])


# ---------------------------------------------------------------------------
# Guard: consumers reference select-concerns, not hand-written tables
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Reason deduplication
# ---------------------------------------------------------------------------


class TestReasonDedup(unittest.TestCase):
    def test_same_reason_not_repeated_for_multiple_paths(self) -> None:
        """Two .py files must not produce duplicate 'glob:*.py' reasons."""
        result = select_guides_with_reasons(
            paths=["src/workflow/cli.py", "tests/workflow_tests/test_x.py"]
        )
        for guide, reasons in result.items():
            self.assertEqual(
                len(reasons),
                len(set(reasons)),
                f"guide {guide!r} has duplicate reasons: {reasons}",
            )

    def test_always_reason_appears_once(self) -> None:
        result = select_guides_with_reasons(
            paths=["src/a.py", "src/b.py", "workflows/c.yaml"]
        )
        patterns_reasons = result.get("patterns.md", [])
        self.assertEqual(patterns_reasons.count("always"), 1)

    def test_task_type_reason_appears_once_even_with_paths(self) -> None:
        result = select_guides_with_reasons(
            paths=["src/a.py"], task_type="feature"
        )
        for guide, reasons in result.items():
            self.assertEqual(
                len(reasons),
                len(set(reasons)),
                f"guide {guide!r} has duplicate reasons: {reasons}",
            )


# ---------------------------------------------------------------------------
# Guard: consumers reference select-concerns, not hand-written tables
# ---------------------------------------------------------------------------

# Files that must reference select-concerns or selection.yaml:
_CONSUMER_FILES = [
    ".claude/agents/thread-fixer.md",
    "workflows/shared/code-review-swarm.yaml",
    "workflows/code/load-concerns.yaml",
    ".claude/agents/reviewer.md",
    ".claude/agents/code-writer.md",
    ".claude/agents/code-writer-opus.md",
    ".claude/skills/code-review/SKILL.md",
    ".github/copilot-instructions.md",
    # Adversarial critique pipeline
    "workflows/shared/plan-critic.yaml",
    "workflows/shared/critique.yaml",
    ".claude/agents/critic.md",
]

# Pattern that detects an inlined path→guide table row.
# Matches Markdown table rows of the form: | <filetype or path> | ...<guide>.md... |
# e.g. | `.py` files | `correctness.md`, ... |
# We require: starts with `|`, contains a backtick-quoted .md filename,
# and also contains a backtick-quoted file type (.py, .yaml, .yml, SKILL.md)
# or path pattern (src/resume/, linkedin).
_TABLE_ROW_RE = _re.compile(
    r"^\s*\|[^|]*`(?:\.py|\.yaml|\.yml|SKILL\.md|src/resume/|linkedin)[^`]*`"
    r"[^|]*\|[^|]*`[a-z][a-z0-9_-]*\.md`",
    _re.MULTILINE,
)


class TestConsumersReferenceSelector(unittest.TestCase):
    """Ensure each consumer calls select-concerns rather than inlining rules."""

    def _read(self, rel_path: str) -> str:
        root = Path(__file__).parent.parent.parent
        return (root / rel_path).read_text(encoding="utf-8")

    # --- each consumer references select-concerns or selection.yaml ---

    def test_thread_fixer_references_select_concerns(self) -> None:
        content = self._read(".claude/agents/thread-fixer.md")
        self.assertIn(
            "select-concerns",
            content,
            ".claude/agents/thread-fixer.md must reference select-concerns",
        )

    def test_code_review_swarm_references_select_concerns(self) -> None:
        content = self._read("workflows/shared/code-review-swarm.yaml")
        self.assertIn(
            "select-concerns",
            content,
            "workflows/shared/code-review-swarm.yaml must reference select-concerns",
        )

    def test_load_concerns_references_select_concerns(self) -> None:
        content = self._read("workflows/code/load-concerns.yaml")
        self.assertIn(
            "select-concerns",
            content,
            "workflows/code/load-concerns.yaml must reference select-concerns",
        )

    def test_reviewer_references_selection_yaml_or_select_concerns(self) -> None:
        content = self._read(".claude/agents/reviewer.md")
        self.assertTrue(
            "select-concerns" in content or "selection.yaml" in content,
            ".claude/agents/reviewer.md must reference select-concerns or selection.yaml",
        )

    def test_code_writer_references_select_concerns(self) -> None:
        content = self._read(".claude/agents/code-writer.md")
        self.assertIn(
            "select-concerns",
            content,
            ".claude/agents/code-writer.md must reference select-concerns",
        )

    def test_code_writer_opus_references_select_concerns(self) -> None:
        content = self._read(".claude/agents/code-writer-opus.md")
        self.assertIn(
            "select-concerns",
            content,
            ".claude/agents/code-writer-opus.md must reference select-concerns",
        )

    def test_code_review_skill_md_references_selection_yaml_or_select_concerns(self) -> None:
        content = self._read(".claude/skills/code-review/SKILL.md")
        self.assertTrue(
            "select-concerns" in content or "selection.yaml" in content,
            ".claude/skills/code-review/SKILL.md must reference select-concerns or selection.yaml",
        )

    def test_copilot_instructions_references_selection_yaml(self) -> None:
        content = self._read(".github/copilot-instructions.md")
        self.assertIn(
            "selection.yaml",
            content,
            ".github/copilot-instructions.md must reference selection.yaml",
        )

    def test_plan_critic_references_select_concerns(self) -> None:
        content = self._read("workflows/shared/plan-critic.yaml")
        self.assertIn(
            "select-concerns",
            content,
            "workflows/shared/plan-critic.yaml must reference select-concerns",
        )

    def test_critique_references_select_concerns(self) -> None:
        content = self._read("workflows/shared/critique.yaml")
        self.assertIn(
            "select-concerns",
            content,
            "workflows/shared/critique.yaml must reference select-concerns",
        )

    def test_critic_agent_references_select_concerns(self) -> None:
        content = self._read(".claude/agents/critic.md")
        self.assertIn(
            "select-concerns",
            content,
            ".claude/agents/critic.md must reference select-concerns",
        )

    # --- no hand-written path→guide tables ---

    def test_no_inlined_table_rows_in_consumers(self) -> None:
        """No consumer file may contain a Markdown table row pairing file types
        with concerns/*.md guide names — those rules belong in selection.yaml."""
        for rel_path in _CONSUMER_FILES:
            content = self._read(rel_path)
            match = _TABLE_ROW_RE.search(content)
            row_text = match.group(0) if match else ""
            self.assertIsNone(
                match,
                f"{rel_path} still contains an inlined path-to-guide table row: "
                f"{row_text!r}. Move the rule to concerns/selection.yaml instead.",
            )

    def test_table_row_detector_has_teeth(self) -> None:
        """The detector must fire on a known bad row, not just pass silently."""
        bad_row = "| `.py` files | `correctness.md`, `security.md` |"
        self.assertIsNotNone(
            _TABLE_ROW_RE.search(bad_row),
            "The table-row detector failed to match a known bad row — "
            "the guard would be vacuous.",
        )

    def test_table_row_detector_ignores_cli_reference_table(self) -> None:
        """A CLI quick-reference table (no .md guide names) must not trigger."""
        ok_row = "| PR metadata | `gh pr view N --json ...` |"
        self.assertIsNone(
            _TABLE_ROW_RE.search(ok_row),
            "The table-row detector incorrectly matched a CLI reference row.",
        )


if __name__ == "__main__":
    unittest.main()
