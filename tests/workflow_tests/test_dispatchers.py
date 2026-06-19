"""Tests for workflow.dispatchers — LocalDispatcher, SkillDispatcher, CompositeDispatcher.

Note: WorkerQueueDispatcher tests are excluded — that class was stripped from
the dancing-bear port (it requires sreutils.worker infrastructure).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from workflow.dispatchers import (
    CompositeDispatcher,
    LocalDispatcher,
    SkillDispatcher,
)
from workflow.models import (
    OutputMode,
    StageKind,
    StageStatus,
)
from workflow.persistence import write_stage_result

from tests.workflow_tests.helpers.factories import (
    make_output_spec,
    make_resolved_stage,
    make_stage_result,
    make_stage_spec,
)

# ---------------------------------------------------------------------------
# LocalDispatcher
# ---------------------------------------------------------------------------


class TestLocalDispatcherInvokeSuccess:
    """Invoke mode success: subprocess called, returns success StageResult."""

    def test_status_is_success(self, tmp_path: Path) -> None:
        output = make_output_spec(name="metrics", mode=OutputMode.invoke)
        spec = make_stage_spec(name="gather-metrics", outputs=(output,))
        stage = make_resolved_stage(spec=spec, cli_commands=("./bin/mail-assistant filters list",))
        dispatcher = LocalDispatcher()

        with patch(
            "workflow.dispatchers.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr="",
            ),
        ):
            result = dispatcher.dispatch(stage, tmp_path)

        assert result.status == StageStatus.success

    def test_output_data_contains_status_ok(self, tmp_path: Path) -> None:
        output = make_output_spec(name="metrics", mode=OutputMode.invoke)
        spec = make_stage_spec(name="gather-metrics", outputs=(output,))
        stage = make_resolved_stage(spec=spec, cli_commands=("./bin/mail-assistant filters list",))
        dispatcher = LocalDispatcher()

        with patch(
            "workflow.dispatchers.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="result", stderr="",
            ),
        ):
            result = dispatcher.dispatch(stage, tmp_path)

        assert result.data["metrics"]["status"] == "ok"

    def test_stage_name_and_index_preserved(self, tmp_path: Path) -> None:
        output = make_output_spec(name="out", mode=OutputMode.invoke)
        spec = make_stage_spec(name="my-stage", outputs=(output,))
        stage = make_resolved_stage(spec=spec, index=3, cli_commands=("echo hi",))
        dispatcher = LocalDispatcher()

        with patch(
            "workflow.dispatchers.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="hi", stderr="",
            ),
        ):
            result = dispatcher.dispatch(stage, tmp_path)

        assert result.stage_name == "my-stage"
        assert result.stage_index == 3


class TestLocalDispatcherInvokeTimeout:
    """Invoke mode timeout: subprocess.TimeoutExpired → StageResult with errors."""

    def test_status_is_failed(self, tmp_path: Path) -> None:
        output = make_output_spec(name="data", mode=OutputMode.invoke)
        spec = make_stage_spec(name="slow-stage", outputs=(output,))
        stage = make_resolved_stage(spec=spec, cli_commands=("sleep 999",))
        dispatcher = LocalDispatcher()

        with patch(
            "workflow.dispatchers.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="sleep 999", timeout=300),
        ):
            result = dispatcher.dispatch(stage, tmp_path)

        assert result.status == StageStatus.failed

    def test_errors_list_populated(self, tmp_path: Path) -> None:
        output = make_output_spec(name="data", mode=OutputMode.invoke)
        spec = make_stage_spec(name="slow-stage", outputs=(output,))
        stage = make_resolved_stage(spec=spec, cli_commands=("sleep 999",))
        dispatcher = LocalDispatcher()

        with patch(
            "workflow.dispatchers.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="sleep 999", timeout=300),
        ):
            result = dispatcher.dispatch(stage, tmp_path)

        assert len(result.errors) > 0
        assert any("timed out" in e.lower() or "timeout" in e.lower() for e in result.errors)


class TestLocalDispatcherInvokeFailure:
    """Invoke mode failure: subprocess returns non-zero → StageResult with error in data."""

    def test_data_has_error_status(self, tmp_path: Path) -> None:
        output = make_output_spec(name="result", mode=OutputMode.invoke)
        spec = make_stage_spec(name="fail-stage", outputs=(output,))
        stage = make_resolved_stage(spec=spec, cli_commands=("exit 1",))
        dispatcher = LocalDispatcher()

        with patch(
            "workflow.dispatchers.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="bad error",
            ),
        ):
            result = dispatcher.dispatch(stage, tmp_path)

        assert result.data["result"]["status"] == "error"

    def test_returncode_captured(self, tmp_path: Path) -> None:
        output = make_output_spec(name="result", mode=OutputMode.invoke)
        spec = make_stage_spec(name="fail-stage", outputs=(output,))
        stage = make_resolved_stage(spec=spec, cli_commands=("exit 2",))
        dispatcher = LocalDispatcher()

        with patch(
            "workflow.dispatchers.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=2, stdout="", stderr="err",
            ),
        ):
            result = dispatcher.dispatch(stage, tmp_path)

        assert result.data["result"]["returncode"] == 2


class TestLocalDispatcherGeneratePassthrough:
    """Generate mode passthrough: stage with generate output → data has requires_agent status."""

    def test_generate_output_has_requires_agent(self, tmp_path: Path) -> None:
        output = make_output_spec(name="report", mode=OutputMode.generate)
        spec = make_stage_spec(name="gen-stage", outputs=(output,))
        stage = make_resolved_stage(spec=spec, cli_commands=())
        dispatcher = LocalDispatcher()

        result = dispatcher.dispatch(stage, tmp_path)

        assert result.data["report"]["status"] == "requires_agent"

    def test_generate_output_mode_value_preserved(self, tmp_path: Path) -> None:
        output = make_output_spec(name="report", mode=OutputMode.generate)
        spec = make_stage_spec(name="gen-stage", outputs=(output,))
        stage = make_resolved_stage(spec=spec, cli_commands=())
        dispatcher = LocalDispatcher()

        result = dispatcher.dispatch(stage, tmp_path)

        assert result.data["report"]["mode"] == OutputMode.generate.value


class TestLocalDispatcherWritesOutputFiles:
    """Stage with writes_to → files created in workspace/outputs/."""

    def test_output_file_created(self, tmp_path: Path) -> None:
        output = make_output_spec(name="data", mode=OutputMode.invoke)
        spec = make_stage_spec(
            name="file-stage",
            outputs=(output,),
            writes_to=("report.json",),
        )
        stage = make_resolved_stage(spec=spec, cli_commands=("echo hi",))
        dispatcher = LocalDispatcher()

        with patch(
            "workflow.dispatchers.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="hi", stderr="",
            ),
        ):
            dispatcher.dispatch(stage, tmp_path)

        assert (tmp_path / "outputs" / "report.json").exists()

    def test_multiple_output_files_all_created(self, tmp_path: Path) -> None:
        output = make_output_spec(name="data", mode=OutputMode.invoke)
        spec = make_stage_spec(
            name="multi-file-stage",
            outputs=(output,),
            writes_to=("a.json", "b.json"),
        )
        stage = make_resolved_stage(spec=spec, cli_commands=("echo hi",))
        dispatcher = LocalDispatcher()

        with patch(
            "workflow.dispatchers.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="hi", stderr="",
            ),
        ):
            dispatcher.dispatch(stage, tmp_path)

        assert (tmp_path / "outputs" / "a.json").exists()
        assert (tmp_path / "outputs" / "b.json").exists()


class TestLocalDispatcherDispatchGroup:
    """dispatch_group sequential: 2 stages → both dispatched, both in results dict."""

    def test_both_stages_in_results(self, tmp_path: Path) -> None:
        spec_a = make_stage_spec(name="stage-alpha")
        spec_b = make_stage_spec(name="stage-beta")
        stage_a = make_resolved_stage(spec=spec_a, index=0)
        stage_b = make_resolved_stage(spec=spec_b, index=1)
        dispatcher = LocalDispatcher()

        results = dispatcher.dispatch_group([stage_a, stage_b], tmp_path)

        assert "stage-alpha" in results
        assert "stage-beta" in results

    def test_results_are_stage_results(self, tmp_path: Path) -> None:
        from workflow.models import StageResult

        spec_a = make_stage_spec(name="stage-alpha")
        spec_b = make_stage_spec(name="stage-beta")
        stage_a = make_resolved_stage(spec=spec_a, index=0)
        stage_b = make_resolved_stage(spec=spec_b, index=1)
        dispatcher = LocalDispatcher()

        results = dispatcher.dispatch_group([stage_a, stage_b], tmp_path)

        assert isinstance(results["stage-alpha"], StageResult)
        assert isinstance(results["stage-beta"], StageResult)


# ---------------------------------------------------------------------------
# SkillDispatcher
# ---------------------------------------------------------------------------


class TestSkillDispatcherWritesDispatchJson:
    """Stage dispatched → dispatch/{index:03d}-{name}.json created."""

    def test_dispatch_file_exists(self, tmp_path: Path) -> None:
        spec = make_stage_spec(name="doc-stage")
        stage = make_resolved_stage(spec=spec, index=2)
        dispatcher = SkillDispatcher("test-workflow")

        dispatcher.dispatch(stage, tmp_path)

        assert (tmp_path / "dispatch" / "002-doc-stage.json").exists()


class TestSkillDispatcherDispatchJsonContent:
    """Dispatch file contains agent_type, prompt, workspace_dir."""

    def test_dispatch_file_has_agent_type(self, tmp_path: Path) -> None:
        spec = make_stage_spec(name="write-stage")
        stage = make_resolved_stage(spec=spec, index=0)
        dispatcher = SkillDispatcher("my-workflow")

        dispatcher.dispatch(stage, tmp_path)

        content = json.loads(
            (tmp_path / "dispatch" / "000-write-stage.json").read_text(encoding="utf-8")
        )
        assert "agent_type" in content

    def test_dispatch_file_has_prompt(self, tmp_path: Path) -> None:
        spec = make_stage_spec(name="write-stage")
        stage = make_resolved_stage(spec=spec, index=0)
        dispatcher = SkillDispatcher("my-workflow")

        dispatcher.dispatch(stage, tmp_path)

        content = json.loads(
            (tmp_path / "dispatch" / "000-write-stage.json").read_text(encoding="utf-8")
        )
        assert "prompt" in content
        assert isinstance(content["prompt"], str)
        assert len(content["prompt"]) > 0

    def test_dispatch_file_has_workspace_dir(self, tmp_path: Path) -> None:
        spec = make_stage_spec(name="write-stage")
        stage = make_resolved_stage(spec=spec, index=0)
        dispatcher = SkillDispatcher("my-workflow")

        dispatcher.dispatch(stage, tmp_path)

        content = json.loads(
            (tmp_path / "dispatch" / "000-write-stage.json").read_text(encoding="utf-8")
        )
        assert "workspace_dir" in content


class TestSkillDispatcherReturnsPendingStatus:
    """Stage without existing result → StageStatus.pending."""

    def test_status_is_pending(self, tmp_path: Path) -> None:
        spec = make_stage_spec(name="pending-stage")
        stage = make_resolved_stage(spec=spec, index=0)
        dispatcher = SkillDispatcher("test-workflow")

        result = dispatcher.dispatch(stage, tmp_path)

        assert result.status == StageStatus.pending

    def test_data_contains_dispatch_file(self, tmp_path: Path) -> None:
        spec = make_stage_spec(name="pending-stage")
        stage = make_resolved_stage(spec=spec, index=0)
        dispatcher = SkillDispatcher("test-workflow")

        result = dispatcher.dispatch(stage, tmp_path)

        assert "dispatch_file" in result.data


class TestSkillDispatcherResumeWithExistingResult:
    """Write a stage result first, then dispatch → returns the existing result."""

    def test_returns_existing_result_not_pending(self, tmp_path: Path) -> None:
        spec = make_stage_spec(name="done-stage")
        stage = make_resolved_stage(spec=spec, index=1)
        existing = make_stage_result(
            stage_name="done-stage",
            stage_index=1,
            status=StageStatus.success,
        )
        write_stage_result(tmp_path, existing)

        dispatcher = SkillDispatcher("test-workflow")
        result = dispatcher.dispatch(stage, tmp_path)

        assert result.status == StageStatus.success
        assert result.stage_name == "done-stage"

    def test_dispatch_file_still_written_on_resume(self, tmp_path: Path) -> None:
        spec = make_stage_spec(name="done-stage")
        stage = make_resolved_stage(spec=spec, index=1)
        existing = make_stage_result(
            stage_name="done-stage",
            stage_index=1,
            status=StageStatus.success,
        )
        write_stage_result(tmp_path, existing)

        dispatcher = SkillDispatcher("test-workflow")
        dispatcher.dispatch(stage, tmp_path)

        assert (tmp_path / "dispatch" / "001-done-stage.json").exists()


class TestSkillDispatcherDispatchGroup:
    """3 stages → 3 dispatch files written."""

    def test_all_dispatch_files_created(self, tmp_path: Path) -> None:
        specs = [make_stage_spec(name=f"stage-{i}") for i in range(3)]
        stages = [make_resolved_stage(spec=specs[i], index=i) for i in range(3)]
        dispatcher = SkillDispatcher("batch-workflow")

        dispatcher.dispatch_group(stages, tmp_path)

        for i in range(3):
            assert (tmp_path / "dispatch" / f"{i:03d}-stage-{i}.json").exists()

    def test_all_stage_names_in_results(self, tmp_path: Path) -> None:
        specs = [make_stage_spec(name=f"stage-{i}") for i in range(3)]
        stages = [make_resolved_stage(spec=specs[i], index=i) for i in range(3)]
        dispatcher = SkillDispatcher("batch-workflow")

        results = dispatcher.dispatch_group(stages, tmp_path)

        for i in range(3):
            assert f"stage-{i}" in results


# ---------------------------------------------------------------------------
# CompositeDispatcher
# ---------------------------------------------------------------------------


class TestCompositeDispatcherRoutesInvokeToLocal:
    """Stage with only invoke outputs → LocalDispatcher handles it."""

    def test_invoke_only_stage_uses_local_dispatcher(self, tmp_path: Path) -> None:
        output = make_output_spec(name="data", mode=OutputMode.invoke)
        spec = make_stage_spec(name="invoke-only", outputs=(output,))
        stage = make_resolved_stage(spec=spec, cli_commands=("echo test",))
        dispatcher = CompositeDispatcher("test-workflow")

        with patch.object(dispatcher._local, "dispatch", wraps=dispatcher._local.dispatch) as mock_local, \
             patch.object(dispatcher._skill, "dispatch", wraps=dispatcher._skill.dispatch) as mock_skill:
            with patch(
                "workflow.dispatchers.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="test", stderr="",
                ),
            ):
                dispatcher.dispatch(stage, tmp_path)

        mock_local.assert_called_once()
        mock_skill.assert_not_called()


class TestCompositeDispatcherRoutesGenerateToSkill:
    """Stage with generate output → SkillDispatcher handles it."""

    def test_generate_stage_uses_skill_dispatcher(self, tmp_path: Path) -> None:
        output = make_output_spec(name="report", mode=OutputMode.generate)
        spec = make_stage_spec(name="gen-stage", outputs=(output,))
        stage = make_resolved_stage(spec=spec)
        dispatcher = CompositeDispatcher("test-workflow")

        with patch.object(dispatcher._skill, "dispatch", wraps=dispatcher._skill.dispatch) as mock_skill, \
             patch.object(dispatcher._local, "dispatch", wraps=dispatcher._local.dispatch) as mock_local:
            dispatcher.dispatch(stage, tmp_path)

        mock_skill.assert_called_once()
        mock_local.assert_not_called()


class TestCompositeDispatcherRoutesValidateToSkill:
    """Stage with kind=validate → SkillDispatcher handles it."""

    def test_validate_kind_uses_skill_dispatcher(self, tmp_path: Path) -> None:
        output = make_output_spec(name="findings", mode=OutputMode.invoke)
        spec = make_stage_spec(name="validate-stage", kind=StageKind.validate, outputs=(output,))
        stage = make_resolved_stage(spec=spec)
        dispatcher = CompositeDispatcher("test-workflow")

        with patch.object(dispatcher._skill, "dispatch", wraps=dispatcher._skill.dispatch) as mock_skill, \
             patch.object(dispatcher._local, "dispatch", wraps=dispatcher._local.dispatch) as mock_local:
            dispatcher.dispatch(stage, tmp_path)

        mock_skill.assert_called_once()
        mock_local.assert_not_called()


class TestCompositeDispatcherRoutesTemplateToSkill:
    """Stage with template output → SkillDispatcher handles it."""

    def test_template_output_uses_skill_dispatcher(self, tmp_path: Path) -> None:
        output = make_output_spec(name="doc", mode=OutputMode.template)
        spec = make_stage_spec(name="template-stage", outputs=(output,))
        stage = make_resolved_stage(spec=spec)
        dispatcher = CompositeDispatcher("test-workflow")

        with patch.object(dispatcher._skill, "dispatch", wraps=dispatcher._skill.dispatch) as mock_skill, \
             patch.object(dispatcher._local, "dispatch", wraps=dispatcher._local.dispatch) as mock_local:
            dispatcher.dispatch(stage, tmp_path)

        mock_skill.assert_called_once()
        mock_local.assert_not_called()


class TestCompositeDispatcherDispatchGroup:
    """dispatch_group routes each stage to the correct sub-dispatcher."""

    def test_mixed_group_routes_correctly(self, tmp_path: Path) -> None:
        """Invoke stage goes to local; generate stage goes to skill."""
        invoke_output = make_output_spec(name="data", mode=OutputMode.invoke)
        invoke_spec = make_stage_spec(name="invoke-stage", outputs=(invoke_output,))
        invoke_stage = make_resolved_stage(spec=invoke_spec, index=0, cli_commands=("echo hi",))

        gen_output = make_output_spec(name="report", mode=OutputMode.generate)
        gen_spec = make_stage_spec(name="gen-stage", outputs=(gen_output,))
        gen_stage = make_resolved_stage(spec=gen_spec, index=1)

        dispatcher = CompositeDispatcher("test-workflow")

        with patch(
            "workflow.dispatchers.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="hi", stderr="",
            ),
        ):
            results = dispatcher.dispatch_group([invoke_stage, gen_stage], tmp_path)

        assert "invoke-stage" in results
        assert "gen-stage" in results
        assert results["invoke-stage"].status == StageStatus.success
        assert results["gen-stage"].status == StageStatus.pending


class TestCompositeDispatcherTriggerParams:
    """trigger_params must reach the _NoOpWorkerQueueDispatcher shim."""

    def test_constructor_threads_trigger_params_into_worker_queue(self) -> None:
        dispatcher = CompositeDispatcher(
            "test-workflow",
            trigger_params={"team": "mail", "env": "prod"},
        )
        assert dispatcher._worker_queue._trigger_params == {
            "team": "mail",
            "env": "prod",
        }

    def test_constructor_defaults_to_empty_trigger_params(self) -> None:
        dispatcher = CompositeDispatcher("test-workflow")
        assert dispatcher._worker_queue._trigger_params == {}
