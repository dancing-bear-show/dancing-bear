"""Tests for workflow.dispatch — agent prompt building and dispatch instructions."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    make_output_spec,
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


class TestKnownRoles:
    def test_all_expected_roles_present(self) -> None:
        for role in _EXPECTED_ROLES:
            assert role in KNOWN_ROLES, f"Missing role in KNOWN_ROLES: {role}"

    def test_all_values_are_strings(self) -> None:
        for role in KNOWN_ROLES:
            assert isinstance(role, str)

    def test_minimum_seven_roles(self) -> None:
        assert len(KNOWN_ROLES) >= 7


# ---------------------------------------------------------------------------
# build_agent_prompt — gather stage
# ---------------------------------------------------------------------------


class TestBuildAgentPromptGather:
    def test_contains_stage_name(self, tmp_path: Path) -> None:
        stage = make_stage_spec(
            name="gather-filters",
            kind=StageKind.gather,
            agent=make_agent_spec(role="researcher"),
        )
        resolved = make_resolved_stage(
            spec=stage,
            cli_commands=("./bin/mail-assistant filters list -- --format json",),
        )
        prompt = build_agent_prompt(resolved, "my-workflow", str(tmp_path))
        assert "gather-filters" in prompt

    def test_contains_cli_commands(self, tmp_path: Path) -> None:
        cmd = "./bin/mail-assistant filters list -- --format json"
        stage = make_stage_spec(name="gather-filters", kind=StageKind.gather)
        resolved = make_resolved_stage(spec=stage, cli_commands=(cmd,))
        prompt = build_agent_prompt(resolved, "my-workflow", str(tmp_path))
        assert cmd in prompt

    def test_contains_workspace_path(self, tmp_path: Path) -> None:
        stage = make_stage_spec(name="gather-data", kind=StageKind.gather)
        resolved = make_resolved_stage(spec=stage)
        prompt = build_agent_prompt(resolved, "my-workflow", str(tmp_path))
        assert str(tmp_path) in prompt

    def test_contains_output_files(self, tmp_path: Path) -> None:
        stage = make_stage_spec(
            name="gather-data",
            kind=StageKind.gather,
            writes_to=("filters.json", "labels.json"),
        )
        resolved = make_resolved_stage(spec=stage)
        prompt = build_agent_prompt(resolved, "my-workflow", str(tmp_path))
        assert "filters.json" in prompt
        assert "labels.json" in prompt


# ---------------------------------------------------------------------------
# build_agent_prompt — validate stage
# ---------------------------------------------------------------------------


class TestBuildAgentPromptValidate:
    def test_contains_domain_rules(self, tmp_path: Path) -> None:
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
        prompt = build_agent_prompt(resolved, "my-workflow", str(tmp_path))
        assert "DR-001" in prompt or "Accuracy" in prompt

    def test_contains_strategy(self, tmp_path: Path) -> None:
        validation = make_validation_spec(strategy="cross_unit")
        stage = make_stage_spec(
            name="cross-validate",
            kind=StageKind.validate,
            validation=validation,
        )
        resolved = make_resolved_stage(spec=stage)
        prompt = build_agent_prompt(resolved, "my-workflow", str(tmp_path))
        assert "cross_unit" in prompt or "cross" in prompt


# ---------------------------------------------------------------------------
# build_agent_prompt — returns non-empty string
# ---------------------------------------------------------------------------


def test_build_agent_prompt_returns_non_empty_string(tmp_path: Path) -> None:
    stage = make_stage_spec(name="simple-stage")
    resolved = make_resolved_stage(spec=stage)
    prompt = build_agent_prompt(resolved, "test-workflow", str(tmp_path))
    assert isinstance(prompt, str)
    assert len(prompt) > 0


# ---------------------------------------------------------------------------
# build_dispatch_instruction
# ---------------------------------------------------------------------------


class TestBuildDispatchInstruction:
    def test_returns_dict(self, tmp_path: Path) -> None:
        stage = make_stage_spec(name="dispatch-stage")
        resolved = make_resolved_stage(spec=stage, index=0)
        result = build_dispatch_instruction(resolved, "test-workflow", str(tmp_path))
        assert isinstance(result, dict)

    def test_has_agent_type(self, tmp_path: Path) -> None:
        stage = make_stage_spec(name="dispatch-stage")
        resolved = make_resolved_stage(spec=stage, index=0)
        result = build_dispatch_instruction(resolved, "test-workflow", str(tmp_path))
        assert "agent_type" in result

    def test_has_prompt(self, tmp_path: Path) -> None:
        stage = make_stage_spec(name="dispatch-stage")
        resolved = make_resolved_stage(spec=stage, index=0)
        result = build_dispatch_instruction(resolved, "test-workflow", str(tmp_path))
        assert "prompt" in result
        assert isinstance(result["prompt"], str)

    def test_has_workspace_dir(self, tmp_path: Path) -> None:
        stage = make_stage_spec(name="dispatch-stage")
        resolved = make_resolved_stage(spec=stage, index=0)
        result = build_dispatch_instruction(resolved, "test-workflow", str(tmp_path))
        assert "workspace_dir" in result
        assert result["workspace_dir"] == str(tmp_path)


# ---------------------------------------------------------------------------
# build_group_dispatch
# ---------------------------------------------------------------------------


class TestBuildGroupDispatch:
    def test_returns_list_of_dicts(self, tmp_path: Path) -> None:
        resolved_stages = {
            f"stage-{i}": make_resolved_stage(spec=make_stage_spec(name=f"stage-{i}"), index=i)
            for i in range(3)
        }
        group = tuple(f"stage-{i}" for i in range(3))
        result = build_group_dispatch(group, resolved_stages, "test-workflow", str(tmp_path))
        assert isinstance(result, list)
        assert len(result) == 3
        for item in result:
            assert isinstance(item, dict)

    def test_each_item_has_prompt(self, tmp_path: Path) -> None:
        resolved_stages = {
            f"stage-{i}": make_resolved_stage(spec=make_stage_spec(name=f"stage-{i}"), index=i)
            for i in range(2)
        }
        group = tuple(f"stage-{i}" for i in range(2))
        result = build_group_dispatch(group, resolved_stages, "test-workflow", str(tmp_path))
        for item in result:
            assert "prompt" in item
