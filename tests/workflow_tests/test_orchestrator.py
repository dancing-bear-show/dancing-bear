"""Tests for workflow.orchestrator — WorkflowOrchestrator execution engine."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tests.workflow_tests.helpers.factories import (
    make_resolved_stage,
    make_stage_result,
    make_stage_spec,
    make_workflow_definition,
    make_workflow_manifest,
)
from workflow.models import (
    StageStatus,
    WorkflowRun,
)
from workflow.orchestrator import OrchestratorConfig, WorkflowExecutionError, WorkflowOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(stage_names: tuple[str, ...], depends: dict | None = None):
    """Create a workflow manifest from a flat list of stage names (all in one group)."""
    stage_specs = [make_stage_spec(name=n) for n in stage_names]
    wf = make_workflow_definition(stages=tuple(stage_specs))
    resolved = {
        n: make_resolved_stage(spec=make_stage_spec(name=n), index=i)
        for i, n in enumerate(stage_names)
    }
    return make_workflow_manifest(
        definition=wf,
        parallel_groups=(stage_names,),
        resolved_stages=resolved,
    )


def _make_success_dispatcher(stage_names: tuple[str, ...]) -> MagicMock:
    """Return a dispatcher mock that always returns success for any stage."""
    dispatcher = MagicMock()

    def _dispatch(stage, workspace_dir):
        return make_stage_result(
            stage_name=stage.spec.name,
            stage_index=stage.index,
            status=StageStatus.success,
        )

    def _dispatch_group(stages, workspace_dir):
        return {
            stage.spec.name: make_stage_result(
                stage_name=stage.spec.name,
                stage_index=stage.index,
                status=StageStatus.success,
            )
            for stage in stages
        }

    dispatcher.dispatch.side_effect = _dispatch
    dispatcher.dispatch_group.side_effect = _dispatch_group
    return dispatcher


def _make_failing_dispatcher(fail_name: str) -> MagicMock:
    """Return a dispatcher mock that fails for *fail_name* and succeeds for others."""
    dispatcher = MagicMock()

    def _dispatch_group(stages, workspace_dir):
        results = {}
        for stage in stages:
            if stage.spec.name == fail_name:
                results[stage.spec.name] = make_stage_result(
                    stage_name=stage.spec.name,
                    stage_index=stage.index,
                    status=StageStatus.failed,
                    errors=[f"Stage {fail_name} failed"],
                )
            else:
                results[stage.spec.name] = make_stage_result(
                    stage_name=stage.spec.name,
                    stage_index=stage.index,
                    status=StageStatus.success,
                )
        return results

    dispatcher.dispatch_group.side_effect = _dispatch_group
    return dispatcher


def _make_orch(
    manifest,
    tmp_dir: str,
    *,
    run_id: str | None = None,
    dry_run: bool = True,
    trigger_params: dict[str, str] | None = None,
    dispatcher=None,
) -> WorkflowOrchestrator:
    """Construct a WorkflowOrchestrator from individual params via OrchestratorConfig."""
    config = OrchestratorConfig(
        manifest=manifest,
        workspace_dir=tmp_dir,
        run_id=run_id,
        dry_run=dry_run,
        trigger_params=trigger_params or {},
    )
    return WorkflowOrchestrator(config, dispatcher=dispatcher)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestWorkflowOrchestratorInit(unittest.TestCase):
    def test_creates_workspace_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            orch = _make_orch(manifest, tmp_dir, run_id="run-001", dry_run=True)
            self.assertTrue(orch._workspace_dir.is_dir())

    def test_run_id_auto_generated_when_not_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            orch = _make_orch(manifest, tmp_dir, dry_run=True)
            self.assertIsInstance(orch._run_id, str)
            self.assertGreater(len(orch._run_id), 0)

    def test_trigger_params_stored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            orch = _make_orch(manifest, tmp_dir, dry_run=True, trigger_params={"env": "prod"})
            self.assertEqual(orch._trigger_params, {"env": "prod"})

    def test_trigger_params_default_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            orch = _make_orch(manifest, tmp_dir, dry_run=True)
            self.assertEqual(orch._trigger_params, {})


# ---------------------------------------------------------------------------
# dry_run mode
# ---------------------------------------------------------------------------


class TestWorkflowOrchestratorDryRun(unittest.TestCase):
    def test_dry_run_returns_workflow_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            orch = _make_orch(manifest, tmp_dir, run_id="dry-001", dry_run=True)
            result = orch.run()
            self.assertIsInstance(result, WorkflowRun)

    def test_dry_run_status_is_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            orch = _make_orch(manifest, tmp_dir, run_id="dry-002", dry_run=True)
            result = orch.run()
            self.assertEqual(result.status, StageStatus.success)

    def test_dry_run_stage_results_have_skipped_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather", "propose"))
            orch = _make_orch(manifest, tmp_dir, run_id="dry-003", dry_run=True)
            result = orch.run()
            for sr in result.stage_results.values():
                self.assertEqual(sr.status, StageStatus.skipped)

    def test_dry_run_run_stage_returns_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            orch = _make_orch(manifest, tmp_dir, dry_run=True)
            sr = orch.run_stage("gather")
            self.assertEqual(sr.status, StageStatus.skipped)
            self.assertTrue(sr.data.get("dry_run"))


# ---------------------------------------------------------------------------
# run_stage — unknown stage
# ---------------------------------------------------------------------------


class TestRunStageUnknown(unittest.TestCase):
    def test_unknown_stage_raises_execution_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            orch = _make_orch(
                manifest, tmp_dir, dry_run=False,
                dispatcher=_make_success_dispatcher(("gather",)),
            )
            with self.assertRaises(WorkflowExecutionError):
                orch.run_stage("nonexistent-stage")

    def test_error_message_mentions_stage_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            orch = _make_orch(
                manifest, tmp_dir, dry_run=False,
                dispatcher=_make_success_dispatcher(("gather",)),
            )
            with self.assertRaises(WorkflowExecutionError) as ctx:
                orch.run_stage("missing-stage")
            self.assertIn("missing-stage", str(ctx.exception))


# ---------------------------------------------------------------------------
# run_stage — dispatcher success
# ---------------------------------------------------------------------------


class TestRunStageSuccess(unittest.TestCase):
    def test_successful_dispatch_returns_success_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            dispatcher = _make_success_dispatcher(("gather",))
            orch = _make_orch(manifest, tmp_dir, dry_run=False, dispatcher=dispatcher)
            sr = orch.run_stage("gather")
            self.assertEqual(sr.status, StageStatus.success)

    def test_result_stored_in_results_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            dispatcher = _make_success_dispatcher(("gather",))
            orch = _make_orch(manifest, tmp_dir, dry_run=False, dispatcher=dispatcher)
            orch.run_stage("gather")
            self.assertIn("gather", orch.results)


# ---------------------------------------------------------------------------
# run_stage — dispatcher failure
# ---------------------------------------------------------------------------


class TestRunStageFailure(unittest.TestCase):
    def test_dispatcher_exception_returns_failed_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            dispatcher = MagicMock()
            dispatcher.dispatch.side_effect = RuntimeError("network error")
            orch = _make_orch(manifest, tmp_dir, dry_run=False, dispatcher=dispatcher)
            sr = orch.run_stage("gather")
            self.assertEqual(sr.status, StageStatus.failed)

    def test_failed_result_has_error_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            dispatcher = MagicMock()
            dispatcher.dispatch.side_effect = OSError("disk full")
            orch = _make_orch(manifest, tmp_dir, dry_run=False, dispatcher=dispatcher)
            sr = orch.run_stage("gather")
            self.assertGreater(len(sr.errors), 0)
            self.assertTrue(any("disk full" in e for e in sr.errors))


# ---------------------------------------------------------------------------
# run — full orchestration
# ---------------------------------------------------------------------------


class TestOrchestratorRun(unittest.TestCase):
    def test_single_stage_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            dispatcher = _make_success_dispatcher(("gather",))
            orch = _make_orch(manifest, tmp_dir, run_id="r-001", dry_run=False, dispatcher=dispatcher)
            result = orch.run()
            self.assertEqual(result.status, StageStatus.success)

    def test_result_includes_stage_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            dispatcher = _make_success_dispatcher(("gather",))
            orch = _make_orch(manifest, tmp_dir, run_id="r-002", dry_run=False, dispatcher=dispatcher)
            result = orch.run()
            self.assertIn("gather", result.stage_results)

    def test_run_id_propagated_to_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            dispatcher = _make_success_dispatcher(("gather",))
            orch = _make_orch(manifest, tmp_dir, run_id="my-run", dry_run=False, dispatcher=dispatcher)
            result = orch.run()
            self.assertEqual(result.run_id, "my-run")

    def test_required_failure_stops_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a manifest where gather is required (default) and fails
            stage_spec = make_stage_spec(name="gather", required=True)
            resolved = {
                "gather": make_resolved_stage(spec=stage_spec, index=0)
            }
            wf = make_workflow_definition(stages=(stage_spec,))
            manifest = make_workflow_manifest(
                definition=wf,
                parallel_groups=(("gather",),),
                resolved_stages=resolved,
            )
            dispatcher = MagicMock()
            dispatcher.dispatch_group.return_value = {
                "gather": make_stage_result(
                    stage_name="gather", stage_index=0, status=StageStatus.failed,
                    errors=["gather failed"],
                )
            }
            orch = _make_orch(manifest, tmp_dir, run_id="r-fail", dry_run=False, dispatcher=dispatcher)
            result = orch.run()
            self.assertEqual(result.status, StageStatus.failed)

    def test_non_required_failure_does_not_stop_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            stage_spec = make_stage_spec(name="optional", required=False)
            resolved = {
                "optional": make_resolved_stage(spec=stage_spec, index=0)
            }
            wf = make_workflow_definition(stages=(stage_spec,))
            manifest = make_workflow_manifest(
                definition=wf,
                parallel_groups=(("optional",),),
                resolved_stages=resolved,
            )
            dispatcher = MagicMock()
            dispatcher.dispatch_group.return_value = {
                "optional": make_stage_result(
                    stage_name="optional", stage_index=0, status=StageStatus.failed,
                    errors=["optional failed"],
                )
            }
            orch = _make_orch(manifest, tmp_dir, run_id="r-opt", dry_run=False, dispatcher=dispatcher)
            result = orch.run()
            self.assertEqual(result.status, StageStatus.success)

    def test_human_gate_pauses_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            gated_spec = make_stage_spec(name="review", human_gate=True)
            resolved = {
                "review": make_resolved_stage(spec=gated_spec, index=0)
            }
            wf = make_workflow_definition(stages=(gated_spec,))
            manifest = make_workflow_manifest(
                definition=wf,
                parallel_groups=(("review",),),
                resolved_stages=resolved,
            )
            dispatcher = MagicMock()
            dispatcher.dispatch_group.return_value = {
                "review": make_stage_result(
                    stage_name="review", stage_index=0, status=StageStatus.success,
                )
            }
            orch = _make_orch(manifest, tmp_dir, run_id="r-gate", dry_run=False, dispatcher=dispatcher)
            result = orch.run()
            self.assertEqual(result.status, StageStatus.awaiting_human)


# ---------------------------------------------------------------------------
# _eval_when
# ---------------------------------------------------------------------------


class TestEvalWhen(unittest.TestCase):
    def _make_orch(self, tmp_dir: str) -> WorkflowOrchestrator:
        manifest = _make_manifest(("gather",))
        return _make_orch(manifest, tmp_dir, dry_run=True)

    def test_none_condition_returns_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            orch = self._make_orch(tmp_dir)
            self.assertTrue(orch._eval_when(None, {}))

    def test_contains_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            orch = self._make_orch(tmp_dir)
            result = orch._eval_when('"hello world" contains "hello"', {})
            self.assertTrue(result)

    def test_contains_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            orch = self._make_orch(tmp_dir)
            result = orch._eval_when('"hello world" contains "goodbye"', {})
            self.assertFalse(result)

    def test_does_not_contain_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            orch = self._make_orch(tmp_dir)
            result = orch._eval_when('"hello world" does not contain "goodbye"', {})
            self.assertTrue(result)

    def test_does_not_contain_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            orch = self._make_orch(tmp_dir)
            result = orch._eval_when('"hello world" does not contain "hello"', {})
            self.assertFalse(result)

    def test_param_substitution_in_when(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            orch = self._make_orch(tmp_dir)
            result = orch._eval_when(
                '"{{env}}" contains "prod"', {"env": "production"}
            )
            # After param resolution "production" contains "prod"
            self.assertTrue(result)

    def test_unrecognised_expression_raises_execution_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            orch = self._make_orch(tmp_dir)
            with self.assertRaises(WorkflowExecutionError):
                orch._eval_when('"something" equals "other"', {})


# ---------------------------------------------------------------------------
# resume classmethod
# ---------------------------------------------------------------------------


class TestWorkflowOrchestratorResume(unittest.TestCase):
    def test_resume_loads_existing_results(self) -> None:
        from workflow.persistence import write_stage_result
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest = _make_manifest(("gather", "propose"))
            workspace = tmp_path / "test-wf-run-001"
            workspace.mkdir()
            (workspace / "stages").mkdir()
            # Write a success result for gather
            sr = make_stage_result(stage_name="gather", stage_index=0, status=StageStatus.success)
            write_stage_result(workspace, sr)

            orch = WorkflowOrchestrator.resume(
                manifest=manifest,
                workspace_dir=workspace,
            )
            self.assertIn("gather", orch._results)

    def test_resume_skips_failed_results(self) -> None:
        from workflow.persistence import write_stage_result
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest = _make_manifest(("gather",))
            workspace = tmp_path / "test-wf-run-002"
            workspace.mkdir()
            (workspace / "stages").mkdir()
            sr = make_stage_result(stage_name="gather", stage_index=0, status=StageStatus.failed)
            write_stage_result(workspace, sr)

            orch = WorkflowOrchestrator.resume(
                manifest=manifest,
                workspace_dir=workspace,
            )
            # Failed result should NOT be in the pre-loaded results
            self.assertNotIn("gather", orch._results)

    def test_resume_run_id_contains_resumed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest = _make_manifest(("gather",))
            workspace = tmp_path / "test-wf-run-003"
            workspace.mkdir()
            (workspace / "stages").mkdir()

            orch = WorkflowOrchestrator.resume(
                manifest=manifest,
                workspace_dir=workspace,
            )
            self.assertIn("resumed", orch._run_id)


# ---------------------------------------------------------------------------
# properties
# ---------------------------------------------------------------------------


class TestOrchestratorProperties(unittest.TestCase):
    def test_results_property_returns_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            orch = _make_orch(manifest, tmp_dir, dry_run=True)
            results = orch.results
            self.assertIsInstance(results, dict)
            # Modifying the returned dict should not affect internal state
            results["new-key"] = MagicMock()
            self.assertNotIn("new-key", orch.results)

    def test_status_property_initial_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            orch = _make_orch(manifest, tmp_dir, dry_run=True)
            self.assertEqual(orch.status, StageStatus.pending)


# ---------------------------------------------------------------------------
# _skip_stage — when condition false
# ---------------------------------------------------------------------------


class TestSkipStage(unittest.TestCase):
    def test_when_false_stage_is_skipped_in_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Stage with when condition that will evaluate to False
            stage_spec = make_stage_spec(
                name="conditional",
                when='"never" contains "yes"',
            )
            resolved = {
                "conditional": make_resolved_stage(spec=stage_spec, index=0)
            }
            wf = make_workflow_definition(stages=(stage_spec,))
            manifest = make_workflow_manifest(
                definition=wf,
                parallel_groups=(("conditional",),),
                resolved_stages=resolved,
            )
            dispatcher = _make_success_dispatcher(("conditional",))
            orch = _make_orch(manifest, tmp_dir, run_id="r-skip", dry_run=False, dispatcher=dispatcher)
            result = orch.run()
            # The stage should be skipped, overall run still succeeds
            self.assertEqual(result.status, StageStatus.success)
            self.assertIn("conditional", result.stage_results)
            self.assertEqual(
                result.stage_results["conditional"].status, StageStatus.skipped
            )


# ---------------------------------------------------------------------------
# dispatcher exception fallback
# ---------------------------------------------------------------------------


class TestDispatcherExceptionFallback(unittest.TestCase):
    def test_dispatch_group_exception_falls_back_to_individual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = _make_manifest(("gather",))
            dispatcher = MagicMock()
            # dispatch_group raises, individual dispatch succeeds
            dispatcher.dispatch_group.side_effect = RuntimeError("group dispatch failed")
            dispatcher.dispatch.return_value = make_stage_result(
                stage_name="gather", stage_index=0, status=StageStatus.success,
            )
            orch = _make_orch(manifest, tmp_dir, run_id="r-fallback", dry_run=False, dispatcher=dispatcher)
            result = orch.run()
            self.assertEqual(result.status, StageStatus.success)


if __name__ == "__main__":
    unittest.main()
