"""Tests for workflow.dispatch — agent prompt building and dispatch instructions."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.dispatch import (
    KNOWN_ROLES,
    build_agent_prompt,
    build_dispatch_instruction,
    build_group_dispatch,
)
from workflow.models import StageKind

from tests.workflow_tests.helpers.factories import (
    make_agent_spec,
    make_domain_rule,
    make_resolved_stage,
    make_stage_spec,
    make_validation_spec,
)

# ---------------------------------------------------------------------------
# KNOWN_ROLES completeness
# ---------------------------------------------------------------------------

_EXPECTED_ROLES = {
    "researcher",
    "code-writer",
    "doc-writer",
    "reviewer",
    "tester",
    "ci-fixer",
    "fact-checker",
}


class TestKnownRoles(unittest.TestCase):
    def test_all_expected_roles_present(self) -> None:
        for role in _EXPECTED_ROLES:
            with self.subTest(role=role):
                self.assertIn(role, KNOWN_ROLES)

    def test_all_values_are_strings(self) -> None:
        for role in KNOWN_ROLES:
            with self.subTest(role=role):
                self.assertIsInstance(role, str)

    def test_minimum_seven_roles(self) -> None:
        self.assertGreaterEqual(len(KNOWN_ROLES), 7)


# ---------------------------------------------------------------------------
# build_agent_prompt — gather stage
# ---------------------------------------------------------------------------


class TestBuildAgentPromptGather(unittest.TestCase):
    def test_contains_stage_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stage = make_stage_spec(
                name="gather-filters",
                kind=StageKind.gather,
                agent=make_agent_spec(role="researcher"),
            )
            resolved = make_resolved_stage(
                spec=stage,
                cli_commands=("./bin/mail-assistant filters list -- --format json",),
            )
            prompt = build_agent_prompt(resolved, "my-workflow", tmp_dir)
            self.assertIn("gather-filters", prompt)

    def test_contains_cli_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cmd = "./bin/mail-assistant filters list -- --format json"
            stage = make_stage_spec(name="gather-filters", kind=StageKind.gather)
            resolved = make_resolved_stage(spec=stage, cli_commands=(cmd,))
            prompt = build_agent_prompt(resolved, "my-workflow", tmp_dir)
            self.assertIn(cmd, prompt)

    def test_contains_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stage = make_stage_spec(name="gather-data", kind=StageKind.gather)
            resolved = make_resolved_stage(spec=stage)
            prompt = build_agent_prompt(resolved, "my-workflow", tmp_dir)
            self.assertIn(tmp_dir, prompt)

    def test_contains_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stage = make_stage_spec(
                name="gather-data",
                kind=StageKind.gather,
                writes_to=("filters.json", "labels.json"),
            )
            resolved = make_resolved_stage(spec=stage)
            prompt = build_agent_prompt(resolved, "my-workflow", tmp_dir)
            self.assertIn("filters.json", prompt)
            self.assertIn("labels.json", prompt)


# ---------------------------------------------------------------------------
# build_agent_prompt — validate stage
# ---------------------------------------------------------------------------


class TestBuildAgentPromptValidate(unittest.TestCase):
    def test_contains_domain_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            rule = make_domain_rule(id="DR-001", description="Accuracy must be > 0.9")
            validation = make_validation_spec(
                strategy="unit",
                domain_rules=(rule,),
            )
            stage = make_stage_spec(
                name="validate-filters",
                kind=StageKind.validate,
                validation=validation,
            )
            resolved = make_resolved_stage(spec=stage)
            prompt = build_agent_prompt(resolved, "my-workflow", tmp_dir)
            self.assertTrue("DR-001" in prompt or "Accuracy" in prompt)

    def test_contains_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            validation = make_validation_spec(strategy="cross_unit")
            stage = make_stage_spec(
                name="cross-validate",
                kind=StageKind.validate,
                validation=validation,
            )
            resolved = make_resolved_stage(spec=stage)
            prompt = build_agent_prompt(resolved, "my-workflow", tmp_dir)
            self.assertTrue("cross_unit" in prompt or "cross" in prompt)


# ---------------------------------------------------------------------------
# build_agent_prompt — returns non-empty string
# ---------------------------------------------------------------------------


class TestBuildAgentPromptNonEmpty(unittest.TestCase):
    def test_build_agent_prompt_returns_non_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stage = make_stage_spec(name="simple-stage")
            resolved = make_resolved_stage(spec=stage)
            prompt = build_agent_prompt(resolved, "test-workflow", tmp_dir)
            self.assertIsInstance(prompt, str)
            self.assertGreater(len(prompt), 0)


# ---------------------------------------------------------------------------
# build_dispatch_instruction
# ---------------------------------------------------------------------------


class TestBuildDispatchInstruction(unittest.TestCase):
    def test_returns_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stage = make_stage_spec(name="dispatch-stage")
            resolved = make_resolved_stage(spec=stage, index=0)
            result = build_dispatch_instruction(resolved, "test-workflow", tmp_dir)
            self.assertIsInstance(result, dict)

    def test_has_agent_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stage = make_stage_spec(name="dispatch-stage")
            resolved = make_resolved_stage(spec=stage, index=0)
            result = build_dispatch_instruction(resolved, "test-workflow", tmp_dir)
            self.assertIn("agent_type", result)

    def test_has_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stage = make_stage_spec(name="dispatch-stage")
            resolved = make_resolved_stage(spec=stage, index=0)
            result = build_dispatch_instruction(resolved, "test-workflow", tmp_dir)
            self.assertIn("prompt", result)
            self.assertIsInstance(result["prompt"], str)

    def test_has_workspace_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stage = make_stage_spec(name="dispatch-stage")
            resolved = make_resolved_stage(spec=stage, index=0)
            result = build_dispatch_instruction(resolved, "test-workflow", tmp_dir)
            self.assertIn("workspace_dir", result)
            # Resolve symlinks for macOS /var vs /private/var equivalence
            self.assertEqual(
                str(Path(result["workspace_dir"]).resolve()),
                str(Path(tmp_dir).resolve()),
            )


# ---------------------------------------------------------------------------
# build_group_dispatch
# ---------------------------------------------------------------------------


class TestBuildGroupDispatch(unittest.TestCase):
    def test_returns_list_of_dicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            resolved_stages = {
                f"stage-{i}": make_resolved_stage(spec=make_stage_spec(name=f"stage-{i}"), index=i)
                for i in range(3)
            }
            group = tuple(f"stage-{i}" for i in range(3))
            result = build_group_dispatch(group, resolved_stages, "test-workflow", tmp_dir)
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 3)
            for item in result:
                self.assertIsInstance(item, dict)

    def test_each_item_has_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            resolved_stages = {
                f"stage-{i}": make_resolved_stage(spec=make_stage_spec(name=f"stage-{i}"), index=i)
                for i in range(2)
            }
            group = tuple(f"stage-{i}" for i in range(2))
            result = build_group_dispatch(group, resolved_stages, "test-workflow", tmp_dir)
            for item in result:
                self.assertIn("prompt", item)


if __name__ == "__main__":
    unittest.main()
