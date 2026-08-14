"""Tests for workflow.dispatchers — SkillDispatcher, WorkerQueueDispatcher, CompositeDispatcher."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.dispatchers import (
    CompositeDispatcher,
    SkillDispatcher,
    WorkerQueueDispatcher,
)
from workflow.models import OutputMode, StageKind, StageStatus
from workflow.persistence import write_stage_result

from tests.workflow_tests.helpers.factories import (
    make_output_spec,
    make_resolved_stage,
    make_stage_result,
    make_stage_spec,
)


# ---------------------------------------------------------------------------
# SkillDispatcher
# ---------------------------------------------------------------------------


class TestSkillDispatcherWritesDispatchJson(unittest.TestCase):
    """Stage dispatched → dispatch/{index:03d}-{name}.json created."""

    def test_dispatch_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="doc-stage")
            stage = make_resolved_stage(spec=spec, index=2)
            dispatcher = SkillDispatcher("test-workflow")

            dispatcher.dispatch(stage, tmp_path)

            self.assertTrue((tmp_path / "dispatch" / "002-doc-stage.json").exists())


class TestSkillDispatcherDispatchJsonContent(unittest.TestCase):
    """Dispatch file contains agent_type, prompt, workspace_dir."""

    def test_dispatch_file_has_agent_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="write-stage")
            stage = make_resolved_stage(spec=spec, index=0)
            dispatcher = SkillDispatcher("my-workflow")

            dispatcher.dispatch(stage, tmp_path)

            content = json.loads(
                (tmp_path / "dispatch" / "000-write-stage.json").read_text(encoding="utf-8")
            )
            self.assertIn("agent_type", content)

    def test_dispatch_file_has_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="write-stage")
            stage = make_resolved_stage(spec=spec, index=0)
            dispatcher = SkillDispatcher("my-workflow")

            dispatcher.dispatch(stage, tmp_path)

            content = json.loads(
                (tmp_path / "dispatch" / "000-write-stage.json").read_text(encoding="utf-8")
            )
            self.assertIn("prompt", content)
            self.assertIsInstance(content["prompt"], str)
            self.assertGreater(len(content["prompt"]), 0)

    def test_dispatch_file_has_workspace_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="write-stage")
            stage = make_resolved_stage(spec=spec, index=0)
            dispatcher = SkillDispatcher("my-workflow")

            dispatcher.dispatch(stage, tmp_path)

            content = json.loads(
                (tmp_path / "dispatch" / "000-write-stage.json").read_text(encoding="utf-8")
            )
            self.assertIn("workspace_dir", content)


class TestSkillDispatcherReturnsPendingStatus(unittest.TestCase):
    """Stage without existing result → StageStatus.pending."""

    def test_status_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="pending-stage")
            stage = make_resolved_stage(spec=spec, index=0)
            dispatcher = SkillDispatcher("test-workflow")

            result = dispatcher.dispatch(stage, tmp_path)

            self.assertEqual(result.status, StageStatus.pending)

    def test_data_contains_dispatch_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="pending-stage")
            stage = make_resolved_stage(spec=spec, index=0)
            dispatcher = SkillDispatcher("test-workflow")

            result = dispatcher.dispatch(stage, tmp_path)

            self.assertIn("dispatch_file", result.data)


class TestSkillDispatcherResumeWithExistingResult(unittest.TestCase):
    """Write a stage result first, then dispatch → returns the existing result."""

    def test_returns_existing_result_not_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
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

            self.assertEqual(result.status, StageStatus.success)
            self.assertEqual(result.stage_name, "done-stage")

    def test_dispatch_file_still_written_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
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

            self.assertTrue((tmp_path / "dispatch" / "001-done-stage.json").exists())


class TestSkillDispatcherDispatchFileBlockedByExistingFile(unittest.TestCase):
    """If 'dispatch' exists as a file (not a dir), mkdir raises FileExistsError."""

    def test_dispatch_raises_file_exists_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "dispatch").write_text("not a directory", encoding="utf-8")
            spec = make_stage_spec(name="blocked-stage")
            stage = make_resolved_stage(spec=spec, index=0)
            dispatcher = SkillDispatcher("test-workflow")

            with self.assertRaises(FileExistsError):
                dispatcher.dispatch(stage, tmp_path)


class TestSkillDispatcherDispatchGroupPropagatesFailure(unittest.TestCase):
    """dispatch_group aborts and propagates if any stage's dispatch raises."""

    def test_one_bad_stage_raises_and_stops_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "dispatch").write_text("not a directory", encoding="utf-8")
            good_spec = make_stage_spec(name="good-stage")
            bad_spec = make_stage_spec(name="bad-stage")
            good_stage = make_resolved_stage(spec=good_spec, index=0)
            bad_stage = make_resolved_stage(spec=bad_spec, index=1)
            dispatcher = SkillDispatcher("test-workflow")

            with self.assertRaises(FileExistsError):
                dispatcher.dispatch_group([good_stage, bad_stage], tmp_path)


class TestSkillDispatcherDispatchGroup(unittest.TestCase):
    """3 stages → 3 dispatch files written."""

    def test_all_dispatch_files_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            specs = [make_stage_spec(name=f"stage-{i}") for i in range(3)]
            stages = [make_resolved_stage(spec=specs[i], index=i) for i in range(3)]
            dispatcher = SkillDispatcher("batch-workflow")

            dispatcher.dispatch_group(stages, tmp_path)

            for i in range(3):
                self.assertTrue((tmp_path / "dispatch" / f"{i:03d}-stage-{i}.json").exists())

    def test_all_stage_names_in_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            specs = [make_stage_spec(name=f"stage-{i}") for i in range(3)]
            stages = [make_resolved_stage(spec=specs[i], index=i) for i in range(3)]
            dispatcher = SkillDispatcher("batch-workflow")

            results = dispatcher.dispatch_group(stages, tmp_path)

            for i in range(3):
                self.assertIn(f"stage-{i}", results)


# ---------------------------------------------------------------------------
# WorkerQueueDispatcher
# ---------------------------------------------------------------------------


class TestWorkerQueueDispatcherEnqueuesJob(unittest.TestCase):
    """dispatch() calls worker.queue_ops.enqueue with a Job of the right type and payload."""

    def test_enqueue_called_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="queue-stage")
            stage = make_resolved_stage(spec=spec, index=0, cli_commands=("./bin/worker enqueue",))
            dispatcher = WorkerQueueDispatcher("my-workflow")

            with patch("worker.queue_ops.enqueue") as mock_enqueue:
                dispatcher.dispatch(stage, tmp_path)

            mock_enqueue.assert_called_once()

    def test_job_type_is_workflow_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="queue-stage")
            stage = make_resolved_stage(spec=spec, index=0)
            dispatcher = WorkerQueueDispatcher("my-workflow")

            with patch("worker.queue_ops.enqueue") as mock_enqueue:
                dispatcher.dispatch(stage, tmp_path)

            mock_enqueue.assert_called_once()
            job = mock_enqueue.call_args[0][0]
            self.assertEqual(job.type, WorkerQueueDispatcher.JOB_TYPE)

    def test_job_payload_has_stage_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="queue-stage")
            stage = make_resolved_stage(spec=spec, index=2)
            dispatcher = WorkerQueueDispatcher("my-workflow")

            with patch("worker.queue_ops.enqueue") as mock_enqueue:
                dispatcher.dispatch(stage, tmp_path)

            mock_enqueue.assert_called_once()
            job = mock_enqueue.call_args[0][0]
            self.assertEqual(job.payload["stage_name"], "queue-stage")
            self.assertEqual(job.payload["stage_index"], 2)
            self.assertEqual(job.payload["workflow_name"], "my-workflow")
            self.assertIn("script", job.payload)


class TestWorkerQueueDispatcherReturnsPending(unittest.TestCase):
    """dispatch() returns a StageStatus.pending result."""

    def test_status_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="queue-stage")
            stage = make_resolved_stage(spec=spec, index=0)
            dispatcher = WorkerQueueDispatcher("my-workflow")

            with patch("worker.queue_ops.enqueue"):
                result = dispatcher.dispatch(stage, tmp_path)

            self.assertEqual(result.status, StageStatus.pending)

    def test_data_contains_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="queue-stage")
            stage = make_resolved_stage(spec=spec, index=0)
            dispatcher = WorkerQueueDispatcher("my-workflow")

            with patch("worker.queue_ops.enqueue"):
                result = dispatcher.dispatch(stage, tmp_path)

            self.assertIn("job_id", result.data)
            self.assertIn("queue-stage", result.data["job_id"])

    def test_job_id_contains_only_safe_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="stage/with:unsafe chars")
            stage = make_resolved_stage(spec=spec, index=0)
            dispatcher = WorkerQueueDispatcher("wf/with:unsafe")

            with patch("worker.queue_ops.enqueue") as mock_enqueue:
                dispatcher.dispatch(stage, tmp_path)

            mock_enqueue.assert_called_once()
            job_id = mock_enqueue.call_args[0][0].id
            self.assertRegex(job_id, r'^[A-Za-z0-9_\-]+$')


class TestWorkerQueueDispatcherTriggerParams(unittest.TestCase):
    """trigger_params are stored and threaded into the job payload."""

    def test_trigger_params_stored(self) -> None:
        dispatcher = WorkerQueueDispatcher("wf", {"env": "prod", "team": "mail"})
        self.assertEqual(dispatcher._trigger_params, {"env": "prod", "team": "mail"})

    def test_trigger_params_default_empty(self) -> None:
        dispatcher = WorkerQueueDispatcher("wf")
        self.assertEqual(dispatcher._trigger_params, {})

    def test_trigger_params_in_job_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="tp-stage")
            stage = make_resolved_stage(spec=spec, index=0)
            dispatcher = WorkerQueueDispatcher("wf", {"env": "staging"})

            with patch("worker.queue_ops.enqueue") as mock_enqueue:
                dispatcher.dispatch(stage, tmp_path)

            mock_enqueue.assert_called_once()
            job = mock_enqueue.call_args[0][0]
            self.assertEqual(job.payload["trigger_params"], {"env": "staging"})


class TestWorkerQueueDispatcherDispatchGroup(unittest.TestCase):
    """dispatch_group enqueues all stages and returns results for each."""

    def test_all_stage_names_in_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            specs = [make_stage_spec(name=f"q-stage-{i}") for i in range(3)]
            stages = [make_resolved_stage(spec=specs[i], index=i) for i in range(3)]
            dispatcher = WorkerQueueDispatcher("batch-wf")

            with patch("worker.queue_ops.enqueue"):
                results = dispatcher.dispatch_group(stages, tmp_path)

            for i in range(3):
                self.assertIn(f"q-stage-{i}", results)

    def test_all_results_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            specs = [make_stage_spec(name=f"q-stage-{i}") for i in range(2)]
            stages = [make_resolved_stage(spec=specs[i], index=i) for i in range(2)]
            dispatcher = WorkerQueueDispatcher("batch-wf")

            with patch("worker.queue_ops.enqueue"):
                results = dispatcher.dispatch_group(stages, tmp_path)

            for result in results.values():
                self.assertEqual(result.status, StageStatus.pending)


class TestWorkerQueueDispatcherHandlerRegistered(unittest.TestCase):
    """workflow_stage handler must be present in worker.handlers.REGISTRY."""

    def test_workflow_stage_in_registry(self) -> None:
        from worker.handlers import REGISTRY
        self.assertIn(WorkerQueueDispatcher.JOB_TYPE, REGISTRY)

    def test_registry_handler_is_callable(self) -> None:
        from worker.handlers import REGISTRY
        self.assertTrue(callable(REGISTRY[WorkerQueueDispatcher.JOB_TYPE]))


# ---------------------------------------------------------------------------
# CompositeDispatcher
# ---------------------------------------------------------------------------


class TestCompositeDispatcherRoutesInvokeToLocal(unittest.TestCase):
    """Stage with only invoke outputs → LocalDispatcher handles it."""

    def test_invoke_only_stage_uses_local_dispatcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
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


class TestCompositeDispatcherRoutesGenerateToSkill(unittest.TestCase):
    """Stage with generate output → SkillDispatcher handles it."""

    def test_generate_stage_uses_skill_dispatcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output = make_output_spec(name="report", mode=OutputMode.generate)
            spec = make_stage_spec(name="gen-stage", outputs=(output,))
            stage = make_resolved_stage(spec=spec)
            dispatcher = CompositeDispatcher("test-workflow")

            with patch.object(dispatcher._skill, "dispatch", wraps=dispatcher._skill.dispatch) as mock_skill, \
                 patch.object(dispatcher._local, "dispatch", wraps=dispatcher._local.dispatch) as mock_local:
                dispatcher.dispatch(stage, tmp_path)

            mock_skill.assert_called_once()
            mock_local.assert_not_called()


class TestCompositeDispatcherRoutesValidateToSkill(unittest.TestCase):
    """Stage with kind=validate → SkillDispatcher handles it."""

    def test_validate_kind_uses_skill_dispatcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output = make_output_spec(name="findings", mode=OutputMode.invoke)
            spec = make_stage_spec(name="validate-stage", kind=StageKind.validate, outputs=(output,))
            stage = make_resolved_stage(spec=spec)
            dispatcher = CompositeDispatcher("test-workflow")

            with patch.object(dispatcher._skill, "dispatch", wraps=dispatcher._skill.dispatch) as mock_skill, \
                 patch.object(dispatcher._local, "dispatch", wraps=dispatcher._local.dispatch) as mock_local:
                dispatcher.dispatch(stage, tmp_path)

            mock_skill.assert_called_once()
            mock_local.assert_not_called()


class TestCompositeDispatcherRoutesTemplateToSkill(unittest.TestCase):
    """Stage with template output → SkillDispatcher handles it."""

    def test_template_output_uses_skill_dispatcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output = make_output_spec(name="doc", mode=OutputMode.template)
            spec = make_stage_spec(name="template-stage", outputs=(output,))
            stage = make_resolved_stage(spec=spec)
            dispatcher = CompositeDispatcher("test-workflow")

            with patch.object(dispatcher._skill, "dispatch", wraps=dispatcher._skill.dispatch) as mock_skill, \
                 patch.object(dispatcher._local, "dispatch", wraps=dispatcher._local.dispatch) as mock_local:
                dispatcher.dispatch(stage, tmp_path)

            mock_skill.assert_called_once()
            mock_local.assert_not_called()


class TestCompositeDispatcherDispatchGroup(unittest.TestCase):
    """dispatch_group routes each stage to the correct sub-dispatcher."""

    def test_mixed_group_routes_correctly(self) -> None:
        """Invoke stage goes to local; generate stage goes to skill."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
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

            self.assertIn("invoke-stage", results)
            self.assertIn("gen-stage", results)
            self.assertEqual(results["invoke-stage"].status, StageStatus.success)
            self.assertEqual(results["gen-stage"].status, StageStatus.pending)


class TestCompositeDispatcherRoutesWorkerQueueExecutor(unittest.TestCase):
    """Stage with executor='worker_queue' → WorkerQueueDispatcher handles it."""

    def test_worker_queue_executor_uses_worker_queue_dispatcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output = make_output_spec(name="result", mode=OutputMode.invoke)
            spec = make_stage_spec(name="bg-stage", outputs=(output,), executor="worker_queue")
            stage = make_resolved_stage(spec=spec)
            dispatcher = CompositeDispatcher("test-workflow")

            with patch.object(dispatcher._worker_queue, "dispatch", wraps=dispatcher._worker_queue.dispatch) as mock_wq, \
                 patch.object(dispatcher._skill, "dispatch", wraps=dispatcher._skill.dispatch) as mock_skill, \
                 patch.object(dispatcher._local, "dispatch", wraps=dispatcher._local.dispatch) as mock_local, \
                 patch("worker.queue_ops.enqueue"):
                dispatcher.dispatch(stage, tmp_path)

            mock_wq.assert_called_once()
            mock_skill.assert_not_called()
            mock_local.assert_not_called()


class TestCompositeDispatcherTriggerParams(unittest.TestCase):
    """trigger_params must reach the WorkerQueueDispatcher."""

    def test_constructor_threads_trigger_params_into_worker_queue(self) -> None:
        dispatcher = CompositeDispatcher(
            "test-workflow",
            trigger_params={"team": "mail", "env": "prod"},
        )
        self.assertEqual(dispatcher._worker_queue._trigger_params, {
            "team": "mail",
            "env": "prod",
        })

    def test_constructor_defaults_to_empty_trigger_params(self) -> None:
        dispatcher = CompositeDispatcher("test-workflow")
        self.assertEqual(dispatcher._worker_queue._trigger_params, {})


class TestCompositeDispatcherRaisesOnInlineExecutor(unittest.TestCase):
    """executor='inline' is not supported by the Python dispatcher → NotImplementedError."""

    def test_inline_executor_raises_not_implemented(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="inline-stage", executor="inline")
            stage = make_resolved_stage(spec=spec)
            dispatcher = CompositeDispatcher("test-workflow")

            with self.assertRaisesRegex(NotImplementedError, "inline-stage"):
                dispatcher.dispatch(stage, tmp_path)

    def test_inline_executor_error_mentions_agent_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(name="inline-stage-2", executor="inline")
            stage = make_resolved_stage(spec=spec)
            dispatcher = CompositeDispatcher("test-workflow")

            with self.assertRaisesRegex(NotImplementedError, "executor='agent'"):
                dispatcher.dispatch(stage, tmp_path)


class TestCompositeDispatcherPropagatesSkillDispatchFailure(unittest.TestCase):
    """A sub-dispatcher failure (SkillDispatcher) propagates out of dispatch()."""

    def test_skill_dispatch_error_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output = make_output_spec(name="report", mode=OutputMode.generate)
            spec = make_stage_spec(name="gen-stage", outputs=(output,))
            stage = make_resolved_stage(spec=spec)
            dispatcher = CompositeDispatcher("test-workflow")

            with patch.object(
                dispatcher._skill, "dispatch", side_effect=OSError("disk full"),
            ):
                with self.assertRaisesRegex(OSError, "disk full"):
                    dispatcher.dispatch(stage, tmp_path)


class TestCompositeDispatcherPropagatesLocalDispatchFailure(unittest.TestCase):
    """A sub-dispatcher failure (LocalDispatcher) propagates out of dispatch()."""

    def test_local_dispatch_error_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output = make_output_spec(name="data", mode=OutputMode.invoke)
            spec = make_stage_spec(name="invoke-only", outputs=(output,))
            stage = make_resolved_stage(spec=spec, cli_commands=("echo test",))
            dispatcher = CompositeDispatcher("test-workflow")

            with patch.object(
                dispatcher._local, "dispatch", side_effect=RuntimeError("boom"),
            ):
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    dispatcher.dispatch(stage, tmp_path)


class TestCompositeDispatcherDispatchGroupPropagatesFailure(unittest.TestCase):
    """dispatch_group aborts and propagates if any routed stage raises (e.g. inline executor)."""

    def test_inline_stage_in_group_raises_and_stops_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            good_output = make_output_spec(name="data", mode=OutputMode.invoke)
            good_spec = make_stage_spec(name="good-stage", outputs=(good_output,))
            good_stage = make_resolved_stage(
                spec=good_spec, index=0, cli_commands=("echo hi",),
            )

            inline_spec = make_stage_spec(name="inline-stage", executor="inline")
            inline_stage = make_resolved_stage(spec=inline_spec, index=1)

            dispatcher = CompositeDispatcher("test-workflow")

            with patch(
                "workflow.dispatchers.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="hi", stderr="",
                ),
            ):
                with self.assertRaises(NotImplementedError):
                    dispatcher.dispatch_group([good_stage, inline_stage], tmp_path)


if __name__ == "__main__":
    unittest.main()
