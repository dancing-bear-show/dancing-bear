"""Consumer and instruction guards for the ``select-concerns`` subcommand.

Covers:
- Every file in _CONSUMER_FILES references ``select-concerns`` or
  ``selection.yaml``, and no guarded file (consumers plus the role-fixed
  files in _ROLE_FIXED_FILES) restates a file-type-to-guide rule in any
  form — table row in either column order, arrow list, or prose
- The restated-rule detector has teeth against every historical shape
- No agent, skill, or workflow instruction passes paths inline via --paths
  (must use --paths-file)
"""

from __future__ import annotations

import re as _re
import unittest
from pathlib import Path

from workflow.concern_select import all_concern_guides

_REPO_ROOT = Path(__file__).resolve().parents[2]

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


class TestNoInlinePathsInAgentInstructions(unittest.TestCase):
    """Agent-facing text must pass paths via --paths-file, never --paths.

    ``select-concerns --paths <file>`` puts repository filenames into shell
    text: a space splits one, a metacharacter executes. thread-fixer.md was
    fixed first; code-writer.md and code-writer-opus.md kept the unsafe form
    until review found them, so this scans every agent, skill and workflow.
    """

    _INLINE = _re.compile(r"select-concerns\b[^\n]*--paths(?!-file)\b")

    def _instruction_files(self) -> list[Path]:
        root = _REPO_ROOT
        return sorted(
            [*root.glob(".claude/agents/*.md"),
             *root.glob(".claude/skills/**/*.md"),
             *root.glob("workflows/**/*.yaml")]
        )

    def test_no_instruction_passes_paths_inline(self) -> None:
        offenders = [
            f"{path.relative_to(_REPO_ROOT)}:{n}"
            for path in self._instruction_files()
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if self._INLINE.search(line)
        ]
        self.assertEqual(offenders, [], "use --paths-file, not inline --paths")

    def test_detector_flags_inline_form(self) -> None:
        self.assertTrue(self._INLINE.search(
            "./bin/workflow select-concerns --paths <file1> --format json"))

    def test_detector_allows_paths_file_form(self) -> None:
        self.assertFalse(self._INLINE.search(
            "git diff --name-only | ./bin/workflow select-concerns --paths-file - --format json"))


if __name__ == "__main__":
    unittest.main()
