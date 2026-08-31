"""Unit tests for workflow.models.

Covers enums, frozen-dataclass enforcement, default values, and field semantics
for every public class in the data model.  No mocking is required — all types
are pure-Python dataclasses or enums.
"""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from workflow.models import (
    AgentSpec,
    DomainRule,
    OutputMode,
    OutputSpec,
    StageKind,
    StageSpec,
    StageStatus,
    TriggerSpec,
    ValidationSpec,
    WorkflowRun,
)
from tests.workflow_tests.helpers.factories import (
    TEST_FINISHED_AT,
    TEST_STARTED_AT,
    make_agent_spec,
    make_domain_rule,
    make_output_spec,
    make_resolved_stage,
    make_stage_result,
    make_stage_spec,
    make_trigger_spec,
    make_validation_spec,
    make_workflow_definition,
    make_workflow_manifest,
)


# ---------------------------------------------------------------------------
# Enum membership and string-value contract
# ---------------------------------------------------------------------------


class TestStageKindValues(unittest.TestCase):
    def test_values(self) -> None:
        cases = [
            (StageKind.gather, "gather"),
            (StageKind.propose, "propose"),
            (StageKind.execute, "execute"),
            (StageKind.validate, "validate"),
            (StageKind.publish, "publish"),
            (StageKind.sub_workflow, "sub-workflow"),
        ]
        for member, expected_value in cases:
            with self.subTest(member=member):
                self.assertEqual(member, expected_value)
                self.assertIsInstance(member, str)


class TestStageStatusValues(unittest.TestCase):
    def test_values(self) -> None:
        cases = [
            (StageStatus.pending, "pending"),
            (StageStatus.running, "running"),
            (StageStatus.success, "success"),
            (StageStatus.failed, "failed"),
            (StageStatus.skipped, "skipped"),
            (StageStatus.awaiting_human, "awaiting_human"),
        ]
        for member, expected_value in cases:
            with self.subTest(member=member):
                self.assertEqual(member, expected_value)
                self.assertIsInstance(member, str)


class TestOutputModeValues(unittest.TestCase):
    def test_values(self) -> None:
        cases = [
            (OutputMode.invoke, "invoke"),
            (OutputMode.generate, "generate"),
            (OutputMode.template, "template"),
        ]
        for member, expected_value in cases:
            with self.subTest(member=member):
                self.assertEqual(member, expected_value)
                self.assertIsInstance(member, str)


# ---------------------------------------------------------------------------
# Frozen enforcement — one representative test per frozen dataclass
# ---------------------------------------------------------------------------


class TestFrozenDataclasses(unittest.TestCase):
    def test_agent_spec_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            spec = make_agent_spec()
            spec.role = "changed"  # type: ignore[misc]

    def test_output_spec_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            spec = make_output_spec()
            spec.name = "changed"  # type: ignore[misc]

    def test_domain_rule_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            rule = make_domain_rule()
            rule.id = "changed"  # type: ignore[misc]

    def test_validation_spec_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            spec = make_validation_spec()
            spec.strategy = "changed"  # type: ignore[misc]

    def test_stage_spec_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            spec = make_stage_spec()
            spec.name = "changed"  # type: ignore[misc]

    def test_trigger_spec_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            spec = make_trigger_spec()
            spec.source = "changed"  # type: ignore[misc]

    def test_workflow_definition_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            wf = make_workflow_definition()
            wf.name = "changed"  # type: ignore[misc]

    def test_stage_result_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            result = make_stage_result()
            result.stage_name = "changed"  # type: ignore[misc]

    def test_resolved_stage_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            resolved = make_resolved_stage()
            resolved.index = 99  # type: ignore[misc]

    def test_workflow_manifest_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            manifest = make_workflow_manifest()
            manifest.manifest_version = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AgentSpec
# ---------------------------------------------------------------------------


class TestAgentSpec(unittest.TestCase):
    def test_required_fields(self) -> None:
        spec = AgentSpec(role="code-writer")
        self.assertEqual(spec.role, "code-writer")
        self.assertIsNone(spec.model)
        self.assertEqual(spec.tools, ())
        self.assertEqual(spec.access, "read-only")

    def test_all_fields(self) -> None:
        spec = AgentSpec(
            role="reviewer",
            model="sonnet",
            tools=("Read", "Grep"),
            access="read-write",
        )
        self.assertEqual(spec.role, "reviewer")
        self.assertEqual(spec.model, "sonnet")
        self.assertEqual(spec.tools, ("Read", "Grep"))
        self.assertEqual(spec.access, "read-write")

    def test_tools_is_tuple(self) -> None:
        spec = make_agent_spec(tools=("Bash", "Edit"))
        self.assertIsInstance(spec.tools, tuple)

    def test_isolation_defaults_to_none(self) -> None:
        spec = AgentSpec(role="code-writer")
        self.assertIsNone(spec.isolation)

    def test_isolation_worktree(self) -> None:
        spec = AgentSpec(role="code-writer", isolation="worktree")
        self.assertEqual(spec.isolation, "worktree")

    def test_isolation_none_explicit(self) -> None:
        spec = AgentSpec(role="researcher", isolation=None)
        self.assertIsNone(spec.isolation)


# ---------------------------------------------------------------------------
# OutputSpec
# ---------------------------------------------------------------------------


class TestOutputSpec(unittest.TestCase):
    def test_defaults(self) -> None:
        spec = OutputSpec(name="out", mode=OutputMode.generate)
        self.assertEqual(spec.description, "")
        self.assertIsNone(spec.skill)
        self.assertEqual(spec.input_mapping, {})
        self.assertIsNone(spec.template_ref)
        self.assertIsNone(spec.writing_guide_ref)
        self.assertIsNone(spec.example_ref)
        self.assertIsNone(spec.schema)
        self.assertIsNone(spec.when)

    def test_invoke_mode(self) -> None:
        spec = OutputSpec(
            name="cli-out",
            mode=OutputMode.invoke,
            skill="/bin/github pr-view",
            input_mapping={"pr_id": "--pr"},
        )
        self.assertEqual(spec.mode, OutputMode.invoke)
        self.assertEqual(spec.skill, "/bin/github pr-view")
        self.assertEqual(spec.input_mapping, {"pr_id": "--pr"})

    def test_template_mode(self) -> None:
        spec = OutputSpec(
            name="report",
            mode=OutputMode.template,
            template_ref="templates/postmortem/TEMPLATE.md",
            writing_guide_ref="templates/postmortem/WRITING_GUIDE.md",
            example_ref="templates/postmortem/EXAMPLE.md",
        )
        self.assertEqual(spec.mode, OutputMode.template)
        self.assertEqual(spec.template_ref, "templates/postmortem/TEMPLATE.md")
        self.assertEqual(spec.writing_guide_ref, "templates/postmortem/WRITING_GUIDE.md")
        self.assertEqual(spec.example_ref, "templates/postmortem/EXAMPLE.md")

    def test_generate_mode_with_schema(self) -> None:
        schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
        spec = OutputSpec(name="structured", mode=OutputMode.generate, schema=schema)
        self.assertEqual(spec.mode, OutputMode.generate)
        self.assertEqual(spec.schema, schema)


# ---------------------------------------------------------------------------
# DomainRule
# ---------------------------------------------------------------------------


class TestDomainRule(unittest.TestCase):
    def test_defaults(self) -> None:
        rule = DomainRule(id="DR-001", description="Accuracy rule")
        self.assertEqual(rule.severity, "minor")
        self.assertEqual(rule.category, "accuracy")
        self.assertIsNone(rule.source_cmd)

    def test_all_fields(self) -> None:
        rule = DomainRule(
            id="DR-002",
            description="Critical rule",
            severity="critical",
            category="consistency",
            source_cmd="./bin/mail-assistant filters list",
        )
        self.assertEqual(rule.severity, "critical")
        self.assertEqual(rule.category, "consistency")
        self.assertEqual(rule.source_cmd, "./bin/mail-assistant filters list")


# ---------------------------------------------------------------------------
# ValidationSpec
# ---------------------------------------------------------------------------


class TestValidationSpec(unittest.TestCase):
    def test_defaults(self) -> None:
        spec = ValidationSpec(strategy="fact_check")
        self.assertEqual(spec.criteria, ())
        self.assertEqual(spec.domain_rules, ())
        self.assertEqual(spec.max_revisions, 2)

    def test_with_domain_rules(self) -> None:
        rule = make_domain_rule(id="DR-003", severity="critical")
        spec = ValidationSpec(
            strategy="adversarial",
            criteria=("No hallucinated numbers",),
            domain_rules=(rule,),
            max_revisions=3,
        )
        self.assertEqual(spec.strategy, "adversarial")
        self.assertEqual(len(spec.domain_rules), 1)
        self.assertEqual(spec.domain_rules[0].id, "DR-003")
        self.assertEqual(spec.max_revisions, 3)


# ---------------------------------------------------------------------------
# StageSpec
# ---------------------------------------------------------------------------


class TestStageSpec(unittest.TestCase):
    def test_defaults(self) -> None:
        spec = StageSpec(
            name="gather-data",
            kind=StageKind.gather,
            description="Gathers data",
            agent=make_agent_spec(),
        )
        self.assertEqual(spec.depends_on, ())
        self.assertEqual(spec.outputs, ())
        self.assertIsNone(spec.validation)
        self.assertIs(spec.human_gate, False)
        self.assertIs(spec.required, True)
        self.assertEqual(spec.reads_from, ())
        self.assertEqual(spec.writes_to, ())
        self.assertEqual(spec.sub_workflow, "")

    def test_depends_on(self) -> None:
        spec = make_stage_spec(depends_on=("stage-a", "stage-b"))
        self.assertEqual(spec.depends_on, ("stage-a", "stage-b"))

    def test_human_gate(self) -> None:
        spec = make_stage_spec(human_gate=True)
        self.assertIs(spec.human_gate, True)

    def test_reads_writes(self) -> None:
        spec = make_stage_spec(
            reads_from=("gather-stage",),
            writes_to=("report.md", "summary.json"),
        )
        self.assertEqual(spec.reads_from, ("gather-stage",))
        self.assertEqual(spec.writes_to, ("report.md", "summary.json"))

    def test_with_validation(self) -> None:
        validation = make_validation_spec(strategy="cross_unit")
        spec = make_stage_spec(validation=validation)
        self.assertIsNotNone(spec.validation)
        self.assertEqual(spec.validation.strategy, "cross_unit")


# ---------------------------------------------------------------------------
# TriggerSpec
# ---------------------------------------------------------------------------


class TestTriggerSpec(unittest.TestCase):
    def test_defaults(self) -> None:
        spec = TriggerSpec(source="zoom")
        self.assertEqual(spec.params, {})

    def test_with_params(self) -> None:
        spec = TriggerSpec(source="manual", params={"incident_id": "INC-123"})
        self.assertEqual(spec.source, "manual")
        self.assertEqual(spec.params["incident_id"], "INC-123")


# ---------------------------------------------------------------------------
# WorkflowDefinition
# ---------------------------------------------------------------------------


class TestWorkflowDefinition(unittest.TestCase):
    def test_defaults(self) -> None:
        wf = make_workflow_definition()
        self.assertIsNone(wf.workspace_dir)
        self.assertEqual(wf.metadata, {})

    def test_stages_is_tuple(self) -> None:
        stage_a = make_stage_spec(name="stage-a")
        stage_b = make_stage_spec(name="stage-b", kind=StageKind.validate)
        wf = make_workflow_definition(stages=(stage_a, stage_b))
        self.assertIsInstance(wf.stages, tuple)
        self.assertEqual(len(wf.stages), 2)

    def test_multiple_stages_order(self) -> None:
        stages = tuple(make_stage_spec(name=f"stage-{i}") for i in range(3))
        wf = make_workflow_definition(stages=stages)
        self.assertEqual(wf.stages[0].name, "stage-0")
        self.assertEqual(wf.stages[2].name, "stage-2")

    def test_metadata(self) -> None:
        wf = make_workflow_definition(metadata={"owner": "platform", "ticket": "WF-42"})
        self.assertEqual(wf.metadata["owner"], "platform")


# ---------------------------------------------------------------------------
# StageResult
# ---------------------------------------------------------------------------


class TestStageResult(unittest.TestCase):
    def test_defaults(self) -> None:
        result = make_stage_result()
        self.assertEqual(result.data, {})
        self.assertEqual(result.errors, [])
        self.assertEqual(result.output_files, [])
        self.assertEqual(result.input_stages, [])
        self.assertEqual(result.metadata, {})

    def test_status_enum_round_trip(self) -> None:
        result = make_stage_result(status=StageStatus.success)
        self.assertEqual(result.status, "success")
        self.assertIs(result.status, StageStatus.success)

    def test_failed_status(self) -> None:
        result = make_stage_result(status=StageStatus.failed, errors=["timeout"])
        self.assertEqual(result.status, StageStatus.failed)
        self.assertIn("timeout", result.errors)

    def test_timestamps(self) -> None:
        result = make_stage_result()
        self.assertEqual(result.started_at, TEST_STARTED_AT)
        self.assertEqual(result.finished_at, TEST_FINISHED_AT)
        self.assertEqual(result.duration_ms, 60000)


# ---------------------------------------------------------------------------
# ResolvedStage
# ---------------------------------------------------------------------------


class TestResolvedStage(unittest.TestCase):
    def test_defaults(self) -> None:
        resolved = make_resolved_stage()
        self.assertEqual(resolved.cli_commands, ())
        self.assertIsNone(resolved.prompt)
        self.assertIsNone(resolved.template_content)
        self.assertIsNone(resolved.guide_content)

    def test_with_prompt(self) -> None:
        resolved = make_resolved_stage(prompt="Gather all mail filters.")
        self.assertEqual(resolved.prompt, "Gather all mail filters.")

    def test_spec_reference(self) -> None:
        stage = make_stage_spec(name="custom-stage", kind=StageKind.publish)
        resolved = make_resolved_stage(spec=stage, index=3)
        self.assertEqual(resolved.spec.name, "custom-stage")
        self.assertEqual(resolved.spec.kind, StageKind.publish)
        self.assertEqual(resolved.index, 3)


# ---------------------------------------------------------------------------
# WorkflowManifest
# ---------------------------------------------------------------------------


class TestWorkflowManifest(unittest.TestCase):
    def test_defaults(self) -> None:
        manifest = make_workflow_manifest()
        self.assertEqual(manifest.resolved_stages, {})
        self.assertEqual(manifest.compiled_at, "")
        self.assertEqual(manifest.manifest_version, 1)

    def test_parallel_groups_structure(self) -> None:
        manifest = make_workflow_manifest(
            parallel_groups=(("stage-a",), ("stage-b", "stage-c"))
        )
        self.assertIsInstance(manifest.parallel_groups, tuple)
        self.assertEqual(manifest.parallel_groups[0], ("stage-a",))
        self.assertEqual(manifest.parallel_groups[1], ("stage-b", "stage-c"))

    def test_with_resolved_stages(self) -> None:
        resolved = make_resolved_stage(spec=make_stage_spec(name="gather"))
        manifest = make_workflow_manifest(resolved_stages={"gather": resolved})
        self.assertIn("gather", manifest.resolved_stages)
        self.assertEqual(manifest.resolved_stages["gather"].spec.name, "gather")


# ---------------------------------------------------------------------------
# WorkflowRun
# ---------------------------------------------------------------------------


class TestWorkflowRun(unittest.TestCase):
    def _make_run(self):
        return WorkflowRun(
            manifest=make_workflow_manifest(),
            workspace_dir="/tmp/runs/test-run",  # nosec B108 - test string only
            run_id="run-abc-123",
            started_at=TEST_STARTED_AT,
        )

    def test_default_status_is_pending(self) -> None:
        run = self._make_run()
        self.assertEqual(run.status, StageStatus.pending)
        self.assertEqual(run.status, "pending")

    def test_stage_results_default_empty(self) -> None:
        run = self._make_run()
        self.assertEqual(run.stage_results, {})

    def test_frozen(self) -> None:
        run = self._make_run()
        with self.assertRaises(FrozenInstanceError):
            run.run_id = "changed"


if __name__ == "__main__":
    unittest.main()
