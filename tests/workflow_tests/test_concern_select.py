"""Selector rules and logic for workflow.concern_select.

Covers:
- Each glob rule (extension, test files, SKILL.md, iOS, slides)
- resume-copy override (suppresses generic .yaml rule)
- task_type rules
- always-include (patterns.md always present)
- unknown extension → only patterns.md
- deduplication and order
- Every concerns/*.md (except README.md) is reachable by some rule
- selection.yaml references only guides that exist
- Unknown task_type is rejected (selector raises)
- Absolute-path normalization
- ``**/``-prefixed glob matching at root level
- inner ``**/`` matching zero directories
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.concern_select import (
    UnknownTaskTypeError,
    all_concern_guides,
    reachable_guides,
    select_guides,
    select_guides_with_reasons,
    valid_task_types,
)


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


class TestInnerDoubleStarMatchesZeroDirectories(unittest.TestCase):
    """A ``**/`` anywhere in a glob must also match zero directories.

    fnmatch needs a separator for every ``**/``, so ``workflows/**/*.yaml``
    missed ``workflows/ios-reorg.yaml`` and ``tests/**/*.py`` missed
    ``tests/fixtures.py`` -- the leading-only fix did not cover these.
    """

    def test_top_level_workflow_file_gets_collateral_damage(self) -> None:
        guides = select_guides(paths=["workflows/ios-reorg.yaml"])
        self.assertIn("collateral-damage.md", guides)

    def test_nested_workflow_file_still_matches(self) -> None:
        guides = select_guides(paths=["workflows/code/x.yaml"])
        self.assertIn("collateral-damage.md", guides)

    def test_top_level_tests_file_matches_tests_rule(self) -> None:
        reasons = select_guides_with_reasons(paths=["tests/fixtures.py"])
        self.assertIn("glob:tests/**/*.py", reasons["tests.md"])

    def test_top_level_src_file_gets_collateral_damage(self) -> None:
        guides = select_guides(paths=["src/setup_helper.py"])
        self.assertIn("collateral-damage.md", guides)

    def test_sibling_directory_with_shared_prefix_does_not_match(self) -> None:
        """Dropping ``**/`` must not let ``workflowsx/`` pass as ``workflows/``."""
        guides = select_guides(paths=["workflowsx/a.yaml"])
        self.assertNotIn("collateral-damage.md", guides)

    def test_yaml_outside_workflows_does_not_get_collateral_damage(self) -> None:
        guides = select_guides(paths=["config/filters.yaml"])
        self.assertNotIn("collateral-damage.md", guides)


if __name__ == "__main__":
    unittest.main()
