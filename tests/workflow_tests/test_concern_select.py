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
- Unknown task_type is rejected (selector raises, CLI exits 2)
- CLI subcommand: json output, exit codes, stdin paths-file, missing rules
  file, and an end-to-end run of the real ./bin/workflow wrapper
- Guard: every file in _CONSUMER_FILES references ``select-concerns`` or
  ``selection.yaml``, and no guarded file (consumers plus the role-fixed
  files in _ROLE_FIXED_FILES) restates a file-type-to-guide rule in any
  form — table row in either column order, arrow list, or prose
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re as _re
import subprocess  # nosec B404 - runs the repo's own ./bin/workflow wrapper
import sys
import tempfile
import unittest
import unittest.mock as mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from workflow import concern_select
from workflow.cli import main as workflow_main
from workflow.concern_select import (
    SelectionRulesNotFoundError,
    UnknownTaskTypeError,
    all_concern_guides,
    reachable_guides,
    select_guides,
    select_guides_with_reasons,
    valid_task_types,
)
from workflow.cli_dispatch_review import _cmd_select_concerns

_REPO_ROOT = Path(__file__).resolve().parents[2]


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


class TestCmdSelectConcernsPathsFileErrors(unittest.TestCase):
    """--paths-file I/O and decode errors must return exit 1, not raise.

    Covers the documented contract in _cmd_select_concerns's docstring:
    "Exit codes: 0 success, 1 on I/O or parse error."
    """

    def test_non_utf8_paths_file_returns_exit_1(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fh:
            fh.write(b"src/foo.py\n\xff\xfe not valid utf-8 \x80\x81\n")
            tmp_path = fh.name

        import io
        from contextlib import redirect_stderr

        try:
            args = _make_args(paths_file=tmp_path, format="json")
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = _cmd_select_concerns(args)
            self.assertEqual(rc, 1)
            self.assertIn("select-concerns: paths-file unreadable", buf.getvalue())
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_unreadable_paths_file_returns_exit_1(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("src/foo.py\n")
            tmp_path = fh.name
        Path(tmp_path).chmod(0o000)

        import io
        from contextlib import redirect_stderr

        try:
            args = _make_args(paths_file=tmp_path, format="json")
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = _cmd_select_concerns(args)
            self.assertEqual(rc, 1)
            self.assertIn("select-concerns: paths-file unreadable", buf.getvalue())
        finally:
            Path(tmp_path).chmod(0o644)
            Path(tmp_path).unlink(missing_ok=True)


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

# Files that must reference select-concerns or selection.yaml, and must not
# restate any file-type-to-guide rule:
_CONSUMER_FILES = [
    ".claude/agents/thread-fixer.md",
    "workflows/shared/code-review-swarm.yaml",
    "workflows/code/load-concerns.yaml",
    ".claude/agents/reviewer.md",
    ".claude/agents/code-writer.md",
    ".claude/agents/code-writer-opus.md",
    ".claude/skills/code-review/SKILL.md",
    ".claude/skills/code-review/README.md",
    ".github/copilot-instructions.md",
    # Adversarial critique pipeline
    "workflows/shared/plan-critic.yaml",
    "workflows/shared/critique.yaml",
    ".claude/agents/critic.md",
]

# Files that name guides for a fixed ROLE rather than for a file type — a
# tester always loads tests.md and reuse.md; validate-code's single-pass
# reviewer always loads its four — so they need not call the selector. They
# are still scanned: a file-type-to-guide rule added to one of them fails.
_ROLE_FIXED_FILES = [
    ".claude/agents/tester.md",
    ".claude/agents/tester-opus.md",
    "workflows/shared/validate-code.yaml",
]

# Guide names are derived from concerns/, so a new guide is covered at once.
# The lookarounds stop "workflow.md" matching inside "my-workflow.md".
_GUIDE_RE = _re.compile(
    r"(?<![\w-])(?:concerns/)?(?:"
    + "|".join(_re.escape(g) for g in all_concern_guides())
    + r")(?![\w.-])"
)

# Tokens that name a file type or file class. Applied AFTER guide names are
# removed from the line, because every guide name itself ends in ".md".
_FILE_TYPE_RE = _re.compile(
    r"\.(?:py|ya?ml|md|json|pptx)\b"  # .py, .yaml, SKILL.md, FLOWS.yaml, ...
    r"|\bREADME\b"
    r"|\btests?/"                       # tests/ paths
    r"|\btest_"                         # test_*.py names
    r"|\btest files?\b"
    r"|\bPython\b"
    r"|\bYAML\b"
)


def _restated_rule_lines(text: str) -> list[str]:
    """Lines pairing a file-type token with at least one concerns/*.md guide.

    Orientation-free: a table row in either column order, an arrow list
    (``.py -> correctness.md``), and prose all match, because the check is
    "both kinds of token on one line", not a positional pattern.
    """
    hits = []
    for line in text.splitlines():
        if not _GUIDE_RE.search(line):
            continue
        if _FILE_TYPE_RE.search(_GUIDE_RE.sub(" ", line)):
            hits.append(line.strip())
    return hits


def _closed_guide_lists(text: str, limit: int = 4) -> list[str]:
    """Paragraphs naming ``limit`` or more distinct guides — a hand-kept list.

    A fixed enumeration drifts the moment the selector can return a guide it
    omits (code-review-swarm's validator listed 10 of 14).
    """
    return [
        para.strip()[:120]
        for para in _re.split(r"\n\s*\n", text)
        if len(set(_GUIDE_RE.findall(para))) >= limit
    ]


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

    def test_every_consumer_references_the_selector(self) -> None:
        for rel_path in _CONSUMER_FILES:
            with self.subTest(file=rel_path):
                content = self._read(rel_path)
                self.assertTrue(
                    "select-concerns" in content or "selection.yaml" in content,
                    f"{rel_path} must reference select-concerns or selection.yaml",
                )

    # --- no restated file-type-to-guide rules, in any shape ---

    def test_no_restated_rules_in_guarded_files(self) -> None:
        """No guarded file may pair a file type with a guide name on one line."""
        for rel_path in _CONSUMER_FILES + _ROLE_FIXED_FILES:
            with self.subTest(file=rel_path):
                hits = _restated_rule_lines(self._read(rel_path))
                self.assertEqual(
                    hits, [],
                    f"{rel_path} restates a file-type-to-guide rule; move it to "
                    "concerns/selection.yaml and point at select-concerns instead",
                )

    def test_no_closed_guide_list_in_consumers(self) -> None:
        for rel_path in _CONSUMER_FILES:
            with self.subTest(file=rel_path):
                self.assertEqual(_closed_guide_lists(self._read(rel_path)), [])

    def test_workflow_consumers_never_pass_an_interpolated_path(self) -> None:
        """A {param} after --paths puts caller data on a command line."""
        for rel_path in _CONSUMER_FILES:
            if not rel_path.endswith(".yaml"):
                continue
            with self.subTest(file=rel_path):
                self.assertIsNone(
                    _re.search(r"--paths\s+\{", self._read(rel_path)),
                    f"{rel_path} interpolates a param after --paths; write the "
                    "paths to a file with the Write tool and use --paths-file",
                )

    def test_thread_fixer_routes_the_review_path_through_a_file(self) -> None:
        content = self._read(".claude/agents/thread-fixer.md")
        self.assertNotIn("--paths <path>", content)
        self.assertIn("--paths-file", content)


class TestRestatedRuleDetectorHasTeeth(unittest.TestCase):
    """Each shape this PR deleted, or that a critique found the old regex
    missed, must be caught — and legitimate lines must not be."""

    HISTORICAL_SHAPES = {
        # .claude/skills/code-review/SKILL.md (guide column first)
        "skill_md_row": "| `concerns/correctness.md` | diff contains `.py` files |",
        # .github/copilot-instructions.md (guide first, prose file class)
        "copilot_flows_row": "| `workflow.md` | `FLOWS.yaml`, CLI references, plan/apply order |",
        "copilot_python_row": "| `correctness.md` | any Python — type safety, logic errors |",
        "copilot_tests_row": "| `tests.md` | test files — quality, coverage, fixture patterns |",
        # workflows/code/load-concerns.yaml (arrow list)
        "load_concerns_arrow": (
            '- file_paths contains ".py" (and not test_) → correctness.md, '
            "security.md, patterns.md, reuse.md, complexity.md"
        ),
        # .claude/agents/reviewer.md (file-type column first)
        "reviewer_row": (
            "| `.py` files | `correctness.md`, `security.md`, `patterns.md`, "
            "`reuse.md`, `complexity.md`, `tests.md` |"
        ),
        # .claude/skills/code-review/README.md
        "readme_docs_row": "| `docs.md` | diff contains `.md`, `README`, or `SKILL.md` files |",
        # .claude/agents/thread-fixer.md prose rule
        "thread_fixer_prose": "When you write or edit test files, ensure `tests.md` is among the guides read.",
        # .claude/agents/code-writer.md prose rule
        "code_writer_prose": "`.py` files: `concerns/correctness.md`, `concerns/patterns.md`.",
    }

    LEGITIMATE = {
        "cli_reference_row": "| PR metadata | `gh pr view N --json ...` |",
        "json_example": '{"guides": ["correctness.md", "patterns.md", ...]}',
        "role_fixed": "Read `concerns/tests.md` and `concerns/reuse.md` before writing",
        "rules_pointer": "The rules live in `concerns/selection.yaml`.",
        "non_guide_md": "Write professional prose per .claude/WRITING_GUIDE.md.",
    }

    def test_every_historical_shape_is_caught(self) -> None:
        for name, line in self.HISTORICAL_SHAPES.items():
            with self.subTest(shape=name):
                self.assertEqual(_restated_rule_lines(line), [line.strip()])

    def test_legitimate_lines_are_not_flagged(self) -> None:
        for name, line in self.LEGITIMATE.items():
            with self.subTest(line=name):
                self.assertEqual(_restated_rule_lines(line), [])

    def test_guide_name_needs_a_word_boundary(self) -> None:
        self.assertEqual(_restated_rule_lines("see my-workflow.md for .py"), [])

    def test_closed_list_detector_catches_the_old_swarm_list(self) -> None:
        old = (
            "concerns/ for concern_id (correctness.md, security.md, tests.md,\n"
            "patterns.md, reuse.md, complexity.md, workflow.md, workflow-fanout.md,\n"
            "workflow-fragments.md, or docs.md)."
        )
        self.assertEqual(len(_closed_guide_lists(old)), 1)
        self.assertEqual(_closed_guide_lists("patterns.md and correctness.md"), [])


# ---------------------------------------------------------------------------
# select_guides: absolute-path normalization
# ---------------------------------------------------------------------------


class TestAbsolutePathNormalization(unittest.TestCase):
    """Absolute paths under the checkout must match repo-relative globs.

    ``select_guides`` documents that callers may pass absolute paths. Before
    this fix, an absolute path was left unconverted, so repo-relative globs
    like ``src/phone/**`` and the resume overrides never matched it — only
    extension/name rules fired.
    """

    def _repo_root(self) -> Path:
        # tests/workflow_tests/test_concern_select.py -> repo root
        return Path(__file__).resolve().parent.parent.parent

    def test_absolute_src_phone_path_adds_phone_layout(self) -> None:
        abs_path = str(self._repo_root() / "src" / "phone" / "cli.py")
        guides = select_guides(paths=[abs_path])
        self.assertIn(
            "phone-layout.md",
            guides,
            "an absolute path under src/phone/ must match the src/phone/** glob",
        )

    def test_absolute_path_matches_relative_path_result(self) -> None:
        """Sanity check: absolute and relative forms of the same path agree."""
        abs_path = str(self._repo_root() / "src" / "phone" / "cli.py")
        self.assertEqual(
            select_guides(paths=[abs_path]),
            select_guides(paths=["src/phone/cli.py"]),
        )

    def test_absolute_resume_config_path_adds_resume_copy_not_workflow(self) -> None:
        abs_path = str(
            self._repo_root() / "src" / "resume" / "config" / "profiles" / "bcs.yaml"
        )
        guides = select_guides(paths=[abs_path])
        self.assertIn(
            "resume-copy.md",
            guides,
            "an absolute resume-config path must match the resume override group",
        )
        self.assertNotIn(
            "workflow.md",
            guides,
            "the resume override group must still suppress the generic yaml rule "
            "for an absolute path, exactly as it does for a relative one",
        )

    def test_sad_path_absolute_outside_checkout_falls_back_to_extension_only(
        self,
    ) -> None:
        """An absolute path outside the checkout cannot be made repo-relative.

        It must not crash and must not spuriously match a repo-relative glob
        — only extension/name rules apply, same as before this fix.
        """
        outside = Path(tempfile.gettempdir()) / "outside-the-checkout" / "src" / "phone" / "cli.py"
        guides = select_guides(paths=[str(outside)])
        self.assertNotIn(
            "phone-layout.md",
            guides,
            "a path outside the checkout must not match src/phone/** just "
            "because its tail happens to look like one",
        )
        self.assertIn("correctness.md", guides)


# ---------------------------------------------------------------------------
# Unknown task_type is rejected, never silently narrowed
# ---------------------------------------------------------------------------


class TestUnknownTaskType(unittest.TestCase):
    def test_selector_raises_on_a_typo(self) -> None:
        with self.assertRaises(UnknownTaskTypeError):
            select_guides(task_type="features")

    def test_valid_types_come_from_selection_yaml(self) -> None:
        self.assertEqual(
            set(valid_task_types()),
            {"feature", "test", "security", "docs", "refactor", "workflow"},
        )

    def test_cli_exits_2_listing_valid_types_without_echoing_the_value(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = _cmd_select_concerns(_make_args(task_type="features$(id)"))
        self.assertEqual(rc, 2)
        message = err.getvalue()
        for task_type in valid_task_types():
            self.assertIn(task_type, message)
        self.assertNotIn("$(id)", message)

    def test_cli_accepts_every_valid_type(self) -> None:
        for task_type in valid_task_types():
            with self.subTest(task_type=task_type):
                out = io.StringIO()
                with redirect_stdout(out):
                    rc = _cmd_select_concerns(_make_args(task_type=task_type, format="json"))
                self.assertEqual(rc, 0)
                self.assertTrue(json.loads(out.getvalue())["guides"])


# ---------------------------------------------------------------------------
# CLI: stdin paths-file and a missing rules file
# ---------------------------------------------------------------------------


class TestCmdSelectConcernsStdinAndMissingRules(unittest.TestCase):
    def test_paths_file_dash_reads_stdin(self) -> None:
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("src/a.py\nworkflows/b.yaml\n")), \
                redirect_stdout(out):
            rc = _cmd_select_concerns(_make_args(paths_file="-", format="json"))
        self.assertEqual(rc, 0)
        guides = json.loads(out.getvalue())["guides"]
        self.assertIn("correctness.md", guides)
        self.assertIn("workflow.md", guides)

    def test_missing_rules_file_is_one_line_exit_1(self) -> None:
        missing = Path(tempfile.gettempdir()) / "no-such-checkout" / "concerns" / "selection.yaml"
        concern_select._load_rules.cache_clear()
        self.addCleanup(concern_select._load_rules.cache_clear)
        err = io.StringIO()
        with mock.patch.object(concern_select, "_SELECTION_YAML", missing), \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = _cmd_select_concerns(_make_args(paths=["src/a.py"]))
        self.assertEqual(rc, 1)
        lines = err.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1, err.getvalue())
        self.assertIn(str(missing), lines[0])
        self.assertIn("repository checkout", lines[0])
        self.assertNotIn("Traceback", err.getvalue())

    def test_missing_rules_file_raises_the_named_error(self) -> None:
        missing = Path(tempfile.gettempdir()) / "no-such-checkout" / "selection.yaml"
        concern_select._load_rules.cache_clear()
        self.addCleanup(concern_select._load_rules.cache_clear)
        with mock.patch.object(concern_select, "_SELECTION_YAML", missing), \
                self.assertRaises(SelectionRulesNotFoundError):
            select_guides(paths=["src/a.py"])


# ---------------------------------------------------------------------------
# End to end: registration and argparse wiring, not a hand-built Namespace
# ---------------------------------------------------------------------------


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = workflow_main(argv)
    return rc, out.getvalue(), err.getvalue()


class TestSelectConcernsThroughMain(unittest.TestCase):
    def test_paths_json(self) -> None:
        rc, out, _ = _run_main(["select-concerns", "--paths", "src/a.py", "--format", "json"])
        self.assertEqual(rc, 0)
        self.assertIn("correctness.md", json.loads(out)["guides"])

    def test_separator_form_the_workflow_engine_emits(self) -> None:
        rc, out, _ = _run_main(["select-concerns", "--", "--paths", "src/a.py", "--format", "json"])
        self.assertEqual(rc, 0)
        self.assertIn("correctness.md", json.loads(out)["guides"])

    def test_paths_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "paths.txt"
            pf.write_text("workflows/x.yaml\n", encoding="utf-8")
            rc, out, _ = _run_main(["select-concerns", "--paths-file", str(pf), "--format", "json"])
        self.assertEqual(rc, 0)
        self.assertIn("workflow-stages.md", json.loads(out)["guides"])

    def test_unknown_task_type_exits_2(self) -> None:
        rc, _, err = _run_main(["select-concerns", "--task-type", "features"])
        self.assertEqual(rc, 2)
        self.assertIn("valid types", err)


class TestSelectConcernsWrapper(unittest.TestCase):
    """Run the real ./bin/workflow wrapper with PYTHONPATH unset."""

    def _run(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        return subprocess.run(  # nosec B603 - fixed argv, repo-owned wrapper
            [str(_REPO_ROOT / "bin" / "workflow"), "select-concerns", *args],
            cwd=_REPO_ROOT, env=env, input=stdin, capture_output=True,
            text=True, timeout=60, check=False,
        )

    def test_paths_json(self) -> None:
        proc = self._run("--paths", "src/a.py", "workflows/b.yaml", "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("correctness.md", data["guides"])
        self.assertIn("workflow.md", data["guides"])
        self.assertEqual(set(data["matched"]), set(data["guides"]))

    def test_paths_file_and_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "paths.txt"
            pf.write_text("src/a.py\n", encoding="utf-8")
            from_file = self._run("--paths-file", str(pf), "--format", "json")
        from_stdin = self._run("--paths-file", "-", "--format", "json", stdin="src/a.py\n")
        self.assertEqual(from_file.returncode, 0, from_file.stderr)
        self.assertEqual(from_stdin.returncode, 0, from_stdin.stderr)
        self.assertEqual(json.loads(from_file.stdout), json.loads(from_stdin.stdout))

    def test_unknown_task_type_exits_2(self) -> None:
        proc = self._run("--task-type", "features")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("valid types", proc.stderr)


# ---------------------------------------------------------------------------
# select_guides: "**/"-prefixed globs must match a root-level path too
# ---------------------------------------------------------------------------


class TestDoubleStarPrefixMatchesRootLevelPath(unittest.TestCase):
    """A leading "**/" in a glob must match a path with zero directories.

    Plain fnmatch requires "**/" to consume at least one path separator, so
    fnmatch("README", "**/README") is False and a repo-root README fell back
    to only patterns.md instead of loading docs.md. _path_matches now retries
    with the "**/" prefix stripped when the unmodified pattern fails.
    """

    # -- happy path: root-level files matching a "**/"-only pattern ---------

    def test_root_readme_adds_docs(self) -> None:
        guides = select_guides(paths=["README"])
        self.assertIn("docs.md", guides)

    def test_root_test_file_adds_tests_and_correctness(self) -> None:
        guides = select_guides(paths=["test_x.py"])
        self.assertIn("tests.md", guides)
        self.assertIn("correctness.md", guides)

    def test_root_ios_iconlayout_json_adds_phone_layout(self) -> None:
        guides = select_guides(paths=["ios.iconlayout.json"])
        self.assertIn("phone-layout.md", guides)

    def test_root_pptx_adds_slides_yaml(self) -> None:
        guides = select_guides(paths=["deck.pptx"])
        self.assertIn("slides-yaml.md", guides)

    def test_root_linkedin_yaml_adds_resume_copy(self) -> None:
        guides = select_guides(paths=["linkedin-export.yaml"])
        self.assertIn("resume-copy.md", guides)

    def test_root_linkedin_yml_adds_resume_copy(self) -> None:
        guides = select_guides(paths=["linkedin-export.yml"])
        self.assertIn("resume-copy.md", guides)

    # -- happy path: nested forms of the same patterns still match ----------

    def test_nested_readme_still_adds_docs(self) -> None:
        guides = select_guides(paths=["src/mail/README"])
        self.assertIn("docs.md", guides)

    def test_nested_test_file_still_adds_tests(self) -> None:
        guides = select_guides(paths=["tests/workflow_tests/test_y.py"])
        self.assertIn("tests.md", guides)

    def test_nested_ios_iconlayout_json_still_adds_phone_layout(self) -> None:
        guides = select_guides(paths=["src/phone/data/ios.iconlayout.json"])
        self.assertIn("phone-layout.md", guides)

    def test_nested_pptx_still_adds_slides_yaml(self) -> None:
        guides = select_guides(paths=["out/decks/deck.pptx"])
        self.assertIn("slides-yaml.md", guides)

    # -- sad path: near-miss names must NOT match ----------------------------

    def test_notreadme_does_not_add_docs_via_readme_rule(self) -> None:
        """A name that merely ends with "README" is not the README rule.

        NOTREADME is not matched by ext=.md either, so docs.md must be
        entirely absent — proving the "**/" stripped-prefix retry does not
        degrade into a substring/suffix match.
        """
        guides = select_guides(paths=["NOTREADME"])
        self.assertNotIn("docs.md", guides)

    def test_readme_dot_md_does_not_match_bare_readme_rule(self) -> None:
        """README.md matches the *.md rule, not "**/README" (exact basename)."""
        reasons = select_guides_with_reasons(paths=["README.md"])
        self.assertIn("docs.md", reasons)
        self.assertNotIn("glob:**/README", reasons["docs.md"])
        self.assertIn("glob:*.md", reasons["docs.md"])

    def test_suffix_match_does_not_fire_test_file_rule(self) -> None:
        """A path merely ending in the stripped pattern text must not match."""
        guides = select_guides(paths=["src/xtest_y.txt"])
        self.assertNotIn("tests.md", guides)

    def test_root_prefix_retry_does_not_widen_ios_rule(self) -> None:
        """A file that only shares the suffix must not fire the iOS rule."""
        guides = select_guides(paths=["notios.iconlayout.json"])
        self.assertNotIn("phone-layout.md", guides)


class TestWorkflowFragmentsRule(unittest.TestCase):
    """.llm/ context files and .claude/agents/ definitions select workflow-fragments.md."""

    def test_llm_context_file_adds_workflow_fragments(self) -> None:
        guides = select_guides(paths=[".llm/CONTEXT.md"])
        self.assertIn("workflow-fragments.md", guides)

    def test_llm_flows_yaml_adds_workflow_fragments(self) -> None:
        guides = select_guides(paths=[".llm/FLOWS.yaml"])
        self.assertIn("workflow-fragments.md", guides)

    def test_claude_agents_definition_adds_workflow_fragments(self) -> None:
        guides = select_guides(paths=[".claude/agents/foo.md"])
        self.assertIn("workflow-fragments.md", guides)

    def test_plain_docs_file_does_not_add_workflow_fragments_via_agent_rule(
        self,
    ) -> None:
        """docs/foo.md must not match the .claude/agents/ rule."""
        reasons = select_guides_with_reasons(paths=["docs/foo.md"])
        if "workflow-fragments.md" in reasons:
            self.assertNotIn(
                "glob:.claude/agents/**",
                reasons["workflow-fragments.md"],
                "docs/foo.md incorrectly matched the .claude/agents/** rule",
            )


if __name__ == "__main__":
    unittest.main()
