"""Tests for workflow.persistence — workspace management and stage result I/O."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.models import StageStatus
from workflow.persistence import (
    init_workspace,
    list_stage_results,
    read_manifest,
    read_stage_result,
    write_manifest,
    write_stage_result,
)

from tests.workflow_tests.helpers.factories import (
    make_stage_result,
    make_workflow_manifest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUBDIRS = ("stages", "outputs", "validation")


# ---------------------------------------------------------------------------
# 1. init_workspace — subdirs created
# ---------------------------------------------------------------------------


class TestInitWorkspace(unittest.TestCase):
    def test_init_workspace_creates_subdirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = init_workspace("my-workflow", "run-001", base_dir=tmp_dir)
            for subdir in _SUBDIRS:
                self.assertTrue((workspace / subdir).is_dir(), f"Expected subdir '{subdir}' to exist")

    def test_init_workspace_returns_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = init_workspace("my-workflow", "run-001", base_dir=tmp_dir)
            self.assertIsInstance(workspace, Path)
            self.assertTrue(workspace.is_dir())

    def test_init_workspace_uses_provided_base_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = init_workspace("wf", "run-id", base_dir=tmp_dir)
            self.assertTrue(workspace.is_dir())
            self.assertIn(tmp_dir, str(workspace))


# ---------------------------------------------------------------------------
# 2. write_stage_result / read_stage_result round-trip
# ---------------------------------------------------------------------------


class TestStageResultRoundTrip(unittest.TestCase):
    def test_write_and_read_stage_result_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            result = make_stage_result(stage_name="gather-filters", stage_index=0)
            write_stage_result(tmp_path, result)

            loaded = read_stage_result(tmp_path, "gather-filters")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.stage_name, "gather-filters")
            self.assertEqual(loaded.stage_index, 0)

    def test_read_stage_result_missing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = read_stage_result(Path(tmp_dir), "nonexistent-stage")
            self.assertIsNone(result)

    def test_write_stage_result_preserves_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            result = make_stage_result(status=StageStatus.failed)
            write_stage_result(tmp_path, result)

            loaded = read_stage_result(tmp_path, "test-stage")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, StageStatus.failed)

    def test_write_stage_result_preserves_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            result = make_stage_result(errors=["timeout", "rate limit"])
            write_stage_result(tmp_path, result)

            loaded = read_stage_result(tmp_path, "test-stage")

            self.assertIsNotNone(loaded)
            self.assertIn("timeout", loaded.errors)
            self.assertIn("rate limit", loaded.errors)


# ---------------------------------------------------------------------------
# 3. list_stage_results
# ---------------------------------------------------------------------------


class TestListStageResults(unittest.TestCase):
    def test_list_stage_results_empty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = init_workspace("wf", "run-1", base_dir=tmp_dir)
            results = list_stage_results(workspace)
            self.assertEqual(results, [])

    def test_list_stage_results_returns_written_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            result_a = make_stage_result(stage_name="stage-a", stage_index=0)
            result_b = make_stage_result(stage_name="stage-b", stage_index=1)
            write_stage_result(tmp_path, result_a)
            write_stage_result(tmp_path, result_b)

            results = list_stage_results(tmp_path)

            names = {r.stage_name for r in results}
            self.assertIn("stage-a", names)
            self.assertIn("stage-b", names)


# ---------------------------------------------------------------------------
# 4. write_manifest / read_manifest round-trip
# ---------------------------------------------------------------------------


class TestManifestRoundTrip(unittest.TestCase):
    def test_write_and_read_manifest_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest = make_workflow_manifest()
            write_manifest(tmp_path, manifest)

            loaded = read_manifest(tmp_path)

            self.assertIsNotNone(loaded)
            # read_manifest returns a ManifestRef (lightweight reference), not the full manifest
            self.assertEqual(loaded.manifest_version, manifest.manifest_version)

    def test_read_manifest_missing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            loaded = read_manifest(Path(tmp_dir))
            self.assertIsNone(loaded)


if __name__ == "__main__":
    unittest.main()
