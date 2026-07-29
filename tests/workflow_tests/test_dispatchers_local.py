"""Tests for workflow.dispatchers — LocalDispatcher."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.dispatchers import LocalDispatcher
from workflow.models import OutputMode, StageResult, StageStatus

from tests.workflow_tests.helpers.factories import (
    make_output_spec,
    make_resolved_stage,
    make_stage_spec,
)


class TestLocalDispatcherInvokeSuccess(unittest.TestCase):
    """Invoke mode success: subprocess called, returns success StageResult."""

    def test_status_is_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
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

            self.assertEqual(result.status, StageStatus.success)

    def test_output_data_contains_status_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
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

            self.assertEqual(result.data["metrics"]["status"], "ok")

    def test_stage_name_and_index_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
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

            self.assertEqual(result.stage_name, "my-stage")
            self.assertEqual(result.stage_index, 3)


class TestLocalDispatcherInvokeTimeout(unittest.TestCase):
    """Invoke mode timeout: subprocess.TimeoutExpired → StageResult with errors."""

    def test_status_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output = make_output_spec(name="data", mode=OutputMode.invoke)
            spec = make_stage_spec(name="slow-stage", outputs=(output,))
            stage = make_resolved_stage(spec=spec, cli_commands=("sleep 999",))
            dispatcher = LocalDispatcher()

            with patch(
                "workflow.dispatchers.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="sleep 999", timeout=300),
            ):
                result = dispatcher.dispatch(stage, tmp_path)

            self.assertEqual(result.status, StageStatus.failed)

    def test_errors_list_populated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output = make_output_spec(name="data", mode=OutputMode.invoke)
            spec = make_stage_spec(name="slow-stage", outputs=(output,))
            stage = make_resolved_stage(spec=spec, cli_commands=("sleep 999",))
            dispatcher = LocalDispatcher()

            with patch(
                "workflow.dispatchers.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="sleep 999", timeout=300),
            ):
                result = dispatcher.dispatch(stage, tmp_path)

            self.assertGreater(len(result.errors), 0)
            self.assertTrue(any("timed out" in e.lower() or "timeout" in e.lower() for e in result.errors))


class TestLocalDispatcherInvokeFailure(unittest.TestCase):
    """Invoke mode failure: subprocess returns non-zero → StageResult with error in data."""

    def test_data_has_error_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
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

            self.assertEqual(result.data["result"]["status"], "error")

    def test_returncode_captured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
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

            self.assertEqual(result.data["result"]["returncode"], 2)


class TestLocalDispatcherGeneratePassthrough(unittest.TestCase):
    """Generate mode passthrough: stage with generate output → data has requires_agent status."""

    def test_generate_output_has_requires_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output = make_output_spec(name="report", mode=OutputMode.generate)
            spec = make_stage_spec(name="gen-stage", outputs=(output,))
            stage = make_resolved_stage(spec=spec, cli_commands=())
            dispatcher = LocalDispatcher()

            result = dispatcher.dispatch(stage, tmp_path)

            self.assertEqual(result.data["report"]["status"], "requires_agent")

    def test_generate_output_mode_value_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output = make_output_spec(name="report", mode=OutputMode.generate)
            spec = make_stage_spec(name="gen-stage", outputs=(output,))
            stage = make_resolved_stage(spec=spec, cli_commands=())
            dispatcher = LocalDispatcher()

            result = dispatcher.dispatch(stage, tmp_path)

            self.assertEqual(result.data["report"]["mode"], OutputMode.generate.value)


class TestLocalDispatcherWritesOutputFiles(unittest.TestCase):
    """Stage with writes_to → files created in workspace/outputs/."""

    def test_output_file_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
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

            self.assertTrue((tmp_path / "outputs" / "report.json").exists())

    def test_multiple_output_files_all_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
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

            self.assertTrue((tmp_path / "outputs" / "a.json").exists())
            self.assertTrue((tmp_path / "outputs" / "b.json").exists())


class TestLocalDispatcherDispatchGroup(unittest.TestCase):
    """dispatch_group sequential: 2 stages → both dispatched, both in results dict."""

    def test_both_stages_in_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec_a = make_stage_spec(name="stage-alpha")
            spec_b = make_stage_spec(name="stage-beta")
            stage_a = make_resolved_stage(spec=spec_a, index=0)
            stage_b = make_resolved_stage(spec=spec_b, index=1)
            dispatcher = LocalDispatcher()

            results = dispatcher.dispatch_group([stage_a, stage_b], tmp_path)

            self.assertIn("stage-alpha", results)
            self.assertIn("stage-beta", results)

    def test_results_are_stage_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec_a = make_stage_spec(name="stage-alpha")
            spec_b = make_stage_spec(name="stage-beta")
            stage_a = make_resolved_stage(spec=spec_a, index=0)
            stage_b = make_resolved_stage(spec=spec_b, index=1)
            dispatcher = LocalDispatcher()

            results = dispatcher.dispatch_group([stage_a, stage_b], tmp_path)

            self.assertIsInstance(results["stage-alpha"], StageResult)
            self.assertIsInstance(results["stage-beta"], StageResult)


if __name__ == "__main__":
    unittest.main()
