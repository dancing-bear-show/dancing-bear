"""Tests for workflow.dispatchers — unique behaviors not covered by test_dispatchers.py."""

from __future__ import annotations

import json
import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.dispatchers import (
    CompositeDispatcher,
    SkillDispatcher,
)
from workflow.models import OutputMode

from tests.workflow_tests.helpers.factories import (
    make_output_spec,
    make_resolved_stage,
    make_stage_spec,
)


# ---------------------------------------------------------------------------
# SkillDispatcher
# ---------------------------------------------------------------------------


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


class TestSkillDispatcherSerializesIsolation(unittest.TestCase):
    """isolation must survive serialization to dispatch/*.json.

    The runtime handoff to the workflow skill is the written JSON file, not the
    in-memory dict — a regression in serialization or the field name would make
    `isolation: worktree` a no-op while dispatch-builder tests still pass.
    """

    def _dispatch_and_read(self, isolation: str | None) -> dict:
        from workflow.models import AgentSpec

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec = make_stage_spec(
                name="iso-stage",
                agent=AgentSpec(role="code-writer", isolation=isolation),
            )
            stage = make_resolved_stage(spec=spec, index=3)
            SkillDispatcher("test-workflow").dispatch(stage, tmp_path)
            written = tmp_path / "dispatch" / "003-iso-stage.json"
            return json.loads(written.read_text(encoding="utf-8"))

    def test_worktree_isolation_reaches_dispatch_file(self) -> None:
        payload = self._dispatch_and_read("worktree")
        self.assertEqual(payload["isolation"], "worktree")

    def test_absent_isolation_serializes_as_null(self) -> None:
        payload = self._dispatch_and_read(None)
        self.assertIn("isolation", payload)
        self.assertIsNone(payload["isolation"])


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


# ---------------------------------------------------------------------------
# CompositeDispatcher
# ---------------------------------------------------------------------------


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
