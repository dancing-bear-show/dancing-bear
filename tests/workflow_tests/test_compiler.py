"""Tests for workflow.compiler — parallel group computation and manifest creation."""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow.compiler import WorkflowCompileError, compile_workflow
from workflow.models import OutputMode, StageKind
from workflow.parser import parse_workflow_str

from tests.workflow_tests.helpers.factories import (
    make_output_spec,
    make_stage_spec,
    make_workflow_definition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _group_of(parallel_groups: tuple, stage: str) -> int | None:
    """Return the group index that contains `stage`, or None if not found."""
    for i, g in enumerate(parallel_groups):
        if stage in g:
            return i
    return None


def _stages_before(parallel_groups: tuple, stage: str) -> set[str]:
    """Return all stage names that appear in groups before the group containing `stage`."""
    result: set[str] = set()
    for g in parallel_groups:
        if stage in g:
            break
        result.update(g)
    return result


def _make_linear_workflow() -> object:
    """Three stages A→B→C, each depending on the previous."""
    stage_a = make_stage_spec(name="a", kind=StageKind.gather)
    stage_b = make_stage_spec(name="b", kind=StageKind.propose, depends_on=("a",))
    stage_c = make_stage_spec(name="c", kind=StageKind.execute, depends_on=("b",))
    return make_workflow_definition(
        name="linear",
        stages=(stage_a, stage_b, stage_c),
    )


def _make_parallel_workflow() -> object:
    """Three independent stages — no dependencies."""
    return make_workflow_definition(
        name="parallel",
        stages=(
            make_stage_spec(name="x"),
            make_stage_spec(name="y"),
            make_stage_spec(name="z"),
        ),
    )


def _make_diamond_workflow() -> object:
    """Diamond: A and B are dep-free; C depends on both."""
    stage_a = make_stage_spec(name="a")
    stage_b = make_stage_spec(name="b")
    stage_c = make_stage_spec(name="c", depends_on=("a", "b"))
    return make_workflow_definition(
        name="diamond",
        stages=(stage_a, stage_b, stage_c),
    )


# ---------------------------------------------------------------------------
# Happy path — parallel group computation
# ---------------------------------------------------------------------------


class TestLinearWorkflow:
    """A→B→C produces 3 groups of 1."""

    def setup_method(self) -> None:
        wf = _make_linear_workflow()
        self.manifest = compile_workflow(wf)  # type: ignore[arg-type]

    def test_group_count(self) -> None:
        assert len(self.manifest.parallel_groups) == 3

    def test_each_group_has_one_stage(self) -> None:
        for group in self.manifest.parallel_groups:
            assert len(group) == 1

    def test_stage_order(self) -> None:
        names = [group[0] for group in self.manifest.parallel_groups]
        assert names == ["a", "b", "c"]


class TestParallelWorkflow:
    """Three independent stages produce 1 group of 3."""

    def setup_method(self) -> None:
        wf = _make_parallel_workflow()
        self.manifest = compile_workflow(wf)  # type: ignore[arg-type]

    def test_group_count(self) -> None:
        assert len(self.manifest.parallel_groups) == 1

    def test_all_stages_in_one_group(self) -> None:
        assert set(self.manifest.parallel_groups[0]) == {"x", "y", "z"}


class TestDiamondWorkflow:
    """Diamond: Group 0 = {A, B}, Group 1 = {C}."""

    def setup_method(self) -> None:
        wf = _make_diamond_workflow()
        self.manifest = compile_workflow(wf)  # type: ignore[arg-type]

    def test_group_count(self) -> None:
        assert len(self.manifest.parallel_groups) == 2

    def test_first_group_has_a_and_b(self) -> None:
        assert set(self.manifest.parallel_groups[0]) == {"a", "b"}

    def test_second_group_has_c(self) -> None:
        assert self.manifest.parallel_groups[1] == ("c",)


class TestHumanGateIsolation:
    """A stage with human_gate=True is isolated into its own group."""

    def test_gated_stage_alone_in_group(self) -> None:
        stage_a = make_stage_spec(name="a")
        stage_gated = make_stage_spec(name="gated", human_gate=True)
        stage_c = make_stage_spec(name="c")
        wf = make_workflow_definition(stages=(stage_a, stage_gated, stage_c))
        manifest = compile_workflow(wf)
        gated_groups = [g for g in manifest.parallel_groups if "gated" in g]
        assert len(gated_groups) == 1
        assert gated_groups[0] == ("gated",)

    def test_non_gated_stages_share_group(self) -> None:
        stage_a = make_stage_spec(name="a")
        stage_gated = make_stage_spec(name="gated", human_gate=True)
        stage_c = make_stage_spec(name="c")
        wf = make_workflow_definition(stages=(stage_a, stage_gated, stage_c))
        manifest = compile_workflow(wf)
        normal_groups = [g for g in manifest.parallel_groups if "gated" not in g]
        all_normal: set[str] = set()
        for g in normal_groups:
            all_normal.update(g)
        assert "a" in all_normal
        assert "c" in all_normal


# ---------------------------------------------------------------------------
# Stage indexing and manifest metadata
# ---------------------------------------------------------------------------


class TestStageIndexing:
    """Resolved stages have correct sequential index values."""

    def test_indices_are_sequential(self) -> None:
        wf = _make_linear_workflow()
        manifest = compile_workflow(wf)  # type: ignore[arg-type]
        indices = sorted(rs.index for rs in manifest.resolved_stages.values())
        assert indices == list(range(len(manifest.resolved_stages)))

    def test_first_group_stage_has_index_zero(self) -> None:
        wf = _make_linear_workflow()
        manifest = compile_workflow(wf)  # type: ignore[arg-type]
        first_name = manifest.parallel_groups[0][0]
        assert manifest.resolved_stages[first_name].index == 0


class TestManifestMetadata:
    """WorkflowManifest has compiled_at and manifest_version set."""

    def setup_method(self) -> None:
        wf = make_workflow_definition()
        self.manifest = compile_workflow(wf)

    def test_compiled_at_is_set(self) -> None:
        assert self.manifest.compiled_at != ""

    def test_compiled_at_looks_like_iso8601(self) -> None:
        assert "T" in self.manifest.compiled_at

    def test_manifest_version_is_one(self) -> None:
        assert self.manifest.manifest_version == 1


# ---------------------------------------------------------------------------
# Template resolution
# ---------------------------------------------------------------------------


class TestTemplateResolution:
    """Template and writing guide refs are loaded from project_root."""

    def test_template_loaded_when_file_exists(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "templates" / "test"
        template_dir.mkdir(parents=True)
        template_file = template_dir / "TEMPLATE.md"
        template_file.write_text("# Template content", encoding="utf-8")

        output = make_output_spec(
            name="out",
            mode=OutputMode.template,
            template_ref="templates/test/TEMPLATE.md",
        )
        stage = make_stage_spec(name="compose", outputs=(output,))
        wf = make_workflow_definition(stages=(stage,))
        manifest = compile_workflow(wf, project_root=tmp_path)

        resolved = manifest.resolved_stages["compose"]
        assert resolved.template_content == "# Template content"

    def test_missing_template_raises_compile_error(self, tmp_path: Path) -> None:
        output = make_output_spec(
            name="out",
            mode=OutputMode.template,
            template_ref="templates/nonexistent/TEMPLATE.md",
        )
        stage = make_stage_spec(name="compose", outputs=(output,))
        wf = make_workflow_definition(stages=(stage,))

        with pytest.raises(WorkflowCompileError, match="template not found"):
            compile_workflow(wf, project_root=tmp_path)

    def test_writing_guide_loaded_when_file_exists(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / "templates" / "test"
        guide_dir.mkdir(parents=True)
        guide_file = guide_dir / "WRITING_GUIDE.md"
        guide_file.write_text("# Writing guide", encoding="utf-8")

        output = make_output_spec(
            name="out",
            mode=OutputMode.template,
            writing_guide_ref="templates/test/WRITING_GUIDE.md",
        )
        stage = make_stage_spec(name="compose", outputs=(output,))
        wf = make_workflow_definition(stages=(stage,))
        manifest = compile_workflow(wf, project_root=tmp_path)

        resolved = manifest.resolved_stages["compose"]
        assert resolved.guide_content == "# Writing guide"

    def test_missing_writing_guide_raises_compile_error(self, tmp_path: Path) -> None:
        output = make_output_spec(
            name="out",
            mode=OutputMode.template,
            writing_guide_ref="templates/nonexistent/WRITING_GUIDE.md",
        )
        stage = make_stage_spec(name="compose", outputs=(output,))
        wf = make_workflow_definition(stages=(stage,))

        with pytest.raises(WorkflowCompileError, match="writing guide not found"):
            compile_workflow(wf, project_root=tmp_path)
