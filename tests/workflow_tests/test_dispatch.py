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

    def test_every_defined_agent_is_a_known_role(self) -> None:
        """Each .claude/agents/<name>.md must appear in KNOWN_ROLES.

        A role missing here still dispatches — build_dispatch_instruction only
        logs a warning — so the gap is invisible on an unattended run. This
        test is what makes adding an agent definition without registering it a
        red build instead of a log line nobody reads.
        """
        agents_dir = Path(__file__).resolve().parents[2] / ".claude" / "agents"
        defined = {p.stem for p in agents_dir.glob("*.md")}
        self.assertTrue(defined, f"no agent definitions found under {agents_dir}")
        missing = sorted(defined - set(KNOWN_ROLES))
        self.assertEqual(
            missing,
            [],
            f"agent definitions absent from KNOWN_ROLES: {missing}",
        )

    def test_unknown_role_still_dispatches_with_warning(self) -> None:
        """An unregistered role must warn but still pass through as agent_type.

        The sad path to the test above: dispatch must not raise or silently
        rewrite the role, or a typo would fail in a way that is harder to
        diagnose than the warning.
        """
        stage = make_resolved_stage(
            spec=make_stage_spec(
                name="bogus-stage",
                kind=StageKind.gather,
                agent=make_agent_spec(role="definitely-not-a-role"),
            )
        )
        with self.assertLogs("workflow.dispatch", level="WARNING") as captured:
            instruction = build_dispatch_instruction(stage, "test-workflow", "/tmp/ws")
        self.assertEqual(instruction["agent_type"], "definitely-not-a-role")
        self.assertTrue(
            any("definitely-not-a-role" in line for line in captured.output),
            f"expected a warning naming the role, got {captured.output}",
        )


# ---------------------------------------------------------------------------
# build_agent_prompt — gather stage
# ---------------------------------------------------------------------------


class TestBuildAgentPromptIsolation(unittest.TestCase):
    """An isolated agent's prompt must not point at the shared workspace.

    It cannot write there, and the orchestrator waits on files that would
    never appear — the stage deadlocks instead of failing.
    """

    def _prompt(self, isolation: str | None) -> str:
        from workflow.models import AgentSpec

        spec = make_stage_spec(
            name="iso",
            agent=AgentSpec(role="code-writer", isolation=isolation),
            writes_to=("outputs/report.json",),
        )
        return build_agent_prompt(make_resolved_stage(spec=spec, index=1), "wf", "/ws")

    def test_isolated_prompt_has_no_workspace_paths(self) -> None:
        prompt = self._prompt("worktree")
        self.assertNotIn("/ws/", prompt)
        self.assertIn("<your-cwd>", prompt)

    def test_isolated_prompt_explains_copy_back(self) -> None:
        prompt = self._prompt("worktree")
        self.assertIn("OWN git worktree", prompt)
        self.assertIn("copies your outputs/", prompt)

    def test_non_isolated_prompt_still_uses_workspace(self) -> None:
        prompt = self._prompt(None)
        self.assertIn("/ws/outputs/report.json", prompt)
        self.assertNotIn("<your-cwd>", prompt)

    def test_isolated_validate_fallback_stays_in_worktree(self) -> None:
        """A validate stage with no writes_to must not fall back to {ws}.

        The no-writes_to branch emitted shared validation/ paths regardless of
        isolation, so the parent waited on files outside the agent's worktree.
        """
        from workflow.models import AgentSpec, StageKind, ValidationSpec, ValidationStrategy

        spec = make_stage_spec(
            name="iso-val",
            kind=StageKind.validate,
            agent=AgentSpec(role="reviewer", isolation="worktree"),
            validation=ValidationSpec(strategy=ValidationStrategy.unit, criteria=("check it",)),
        )
        prompt = build_agent_prompt(make_resolved_stage(spec=spec, index=2), "wf", "/ws")
        self.assertIn("<your-cwd>/validation/iso-val-findings.json", prompt)
        self.assertNotIn("/ws/validation/", prompt)

    def _prompt_with_inputs(self, isolation: str | None) -> str:
        """An execute stage that both reads upstream and writes output."""
        from workflow.models import AgentSpec, StageKind

        spec = make_stage_spec(
            name="iso",
            kind=StageKind.execute,
            agent=AgentSpec(role="code-writer", isolation=isolation),
            reads_from=("upstream",),
            writes_to=("outputs/report.json",),
        )
        return build_agent_prompt(make_resolved_stage(spec=spec, index=1), "wf", "/ws")

    def test_isolated_inputs_come_from_own_cwd(self) -> None:
        """The boundary applies to reads too, not only writes.

        An isolated agent cannot read the shared workspace either; pointing it
        at {ws} makes it read outside its worktree or find nothing.
        """
        prompt = self._prompt_with_inputs("worktree")
        self.assertIn("<your-cwd>/inputs/", prompt)
        self.assertIn("upstream", prompt)
        self.assertNotIn("/ws/", prompt)

    def test_isolated_inputs_do_not_name_a_synthetic_file(self) -> None:
        """Never name one <dep>.json per dependency.

        A stage may declare several outputs of different types (design.md AND
        design.json). Naming a single synthetic file points the agent at
        something that does not exist and silently drops the rest.
        """
        prompt = self._prompt_with_inputs("worktree")
        self.assertNotIn("inputs/upstream.json", prompt)
        self.assertIn("same relative path", prompt)

    def test_non_isolated_inputs_still_come_from_workspace(self) -> None:
        prompt = self._prompt_with_inputs(None)
        self.assertIn("/ws/stages/*-upstream.json", prompt)
        self.assertNotIn("<your-cwd>", prompt)


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

    # (g) isolation key is present in the payload and carries the agent's value
    def test_isolation_worktree_carried_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            agent = make_agent_spec(role="code-writer", isolation="worktree")
            stage = make_stage_spec(name="isolated-stage", agent=agent)
            resolved = make_resolved_stage(spec=stage, index=0)
            result = build_dispatch_instruction(resolved, "test-workflow", tmp_dir)
            self.assertIn("isolation", result)
            self.assertEqual(result["isolation"], "worktree")

    def test_isolation_none_carried_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            agent = make_agent_spec(role="researcher", isolation=None)
            stage = make_stage_spec(name="non-isolated-stage", agent=agent)
            resolved = make_resolved_stage(spec=stage, index=0)
            result = build_dispatch_instruction(resolved, "test-workflow", tmp_dir)
            self.assertIn("isolation", result)
            self.assertIsNone(result["isolation"])


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
