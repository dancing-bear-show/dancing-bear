"""Gap-filling tests for workflow.persistence — status aliases, field aliases, corrupt data."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workflow.models import StageStatus
from workflow.persistence import (
    init_workspace,
    list_stage_results,
    read_stage_result,
    write_stage_result,
)

from tests.workflow_tests.helpers.factories import make_stage_result


# ---------------------------------------------------------------------------
# init_workspace — no base_dir (tempdir default)
# ---------------------------------------------------------------------------


class TestInitWorkspaceNoBaseDir(unittest.TestCase):
    def test_creates_workspace_in_tempdir_when_no_base_dir(self) -> None:
        workspace = init_workspace("wf-test", "run-default")
        try:
            self.assertTrue(workspace.is_dir())
            self.assertIn("wf-test-run-default", str(workspace))
        finally:
            import shutil
            shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# _deserialize_stage_result — status aliases
# ---------------------------------------------------------------------------


class TestStatusAliases(unittest.TestCase):
    """Persistence tolerates non-canonical status strings from agents."""

    def _write_and_read(self, tmp_path: Path, status_str: str) -> object:
        stage_dir = tmp_path / "stages"
        stage_dir.mkdir()
        data = {
            "stage_name": "alias-stage",
            "stage_index": 0,
            "status": status_str,
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:01:00Z",
            "duration_ms": 60000,
        }
        (stage_dir / "000-alias-stage.json").write_text(json.dumps(data), encoding="utf-8")
        return read_stage_result(tmp_path, "alias-stage")

    def test_complete_maps_to_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self._write_and_read(Path(tmp_dir), "complete")
            self.assertEqual(result.status, StageStatus.success)

    def test_completed_maps_to_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self._write_and_read(Path(tmp_dir), "completed")
            self.assertEqual(result.status, StageStatus.success)

    def test_done_maps_to_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self._write_and_read(Path(tmp_dir), "done")
            self.assertEqual(result.status, StageStatus.success)

    def test_ok_maps_to_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self._write_and_read(Path(tmp_dir), "ok")
            self.assertEqual(result.status, StageStatus.success)

    def test_error_maps_to_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self._write_and_read(Path(tmp_dir), "error")
            self.assertEqual(result.status, StageStatus.failed)

    def test_timeout_maps_to_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self._write_and_read(Path(tmp_dir), "timeout")
            self.assertEqual(result.status, StageStatus.failed)

    def test_unknown_status_defaults_to_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self._write_and_read(Path(tmp_dir), "unrecognised_status_xyz")
            self.assertEqual(result.status, StageStatus.pending)

    def test_completed_with_limitations_maps_to_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self._write_and_read(Path(tmp_dir), "completed_with_limitations")
            self.assertEqual(result.status, StageStatus.success)


# ---------------------------------------------------------------------------
# _deserialize_stage_result — field aliases
# ---------------------------------------------------------------------------


class TestFieldAliases(unittest.TestCase):
    """Non-standard field names from agents are mapped to canonical names."""

    def _write_and_read(self, tmp_path: Path, data: dict) -> object:
        stage_dir = tmp_path / "stages"
        stage_dir.mkdir()
        (stage_dir / "000-aliased.json").write_text(json.dumps(data), encoding="utf-8")
        return read_stage_result(tmp_path, "aliased")

    def test_stage_field_alias_for_stage_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data = {
                "stage": "aliased",
                "index": 0,
                "status": "success",
                "started_at": "",
                "finished_at": "",
                "duration_ms": 0,
            }
            result = self._write_and_read(Path(tmp_dir), data)
            self.assertEqual(result.stage_name, "aliased")

    def test_index_field_alias_for_stage_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data = {
                "stage": "aliased",
                "index": 7,
                "status": "success",
                "started_at": "",
                "finished_at": "",
                "duration_ms": 0,
            }
            result = self._write_and_read(Path(tmp_dir), data)
            self.assertEqual(result.stage_index, 7)

    def test_name_field_alias_for_stage_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data = {
                "name": "aliased",
                "index": 0,
                "status": "pending",
                "started_at": "",
                "finished_at": "",
                "duration_ms": 0,
            }
            result = self._write_and_read(Path(tmp_dir), data)
            self.assertEqual(result.stage_name, "aliased")


# ---------------------------------------------------------------------------
# _deserialize_stage_result — duration_ms tolerance
# ---------------------------------------------------------------------------


class TestDurationMsTolerance(unittest.TestCase):
    def _write_and_read(self, tmp_path: Path, duration_ms) -> object:
        stage_dir = tmp_path / "stages"
        stage_dir.mkdir()
        data = {
            "stage_name": "dur-stage",
            "stage_index": 0,
            "status": "success",
            "started_at": "",
            "finished_at": "",
            "duration_ms": duration_ms,
        }
        (stage_dir / "000-dur-stage.json").write_text(json.dumps(data), encoding="utf-8")
        return read_stage_result(tmp_path, "dur-stage")

    def test_string_duration_coerced_to_int(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self._write_and_read(Path(tmp_dir), "5000")
            self.assertEqual(result.duration_ms, 5000)

    def test_null_duration_defaults_to_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self._write_and_read(Path(tmp_dir), None)
            self.assertEqual(result.duration_ms, 0)

    def test_invalid_duration_defaults_to_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self._write_and_read(Path(tmp_dir), "not-a-number")
            self.assertEqual(result.duration_ms, 0)


# ---------------------------------------------------------------------------
# list_stage_results — corrupt file skipped
# ---------------------------------------------------------------------------


class TestListStageResultsCorruptFile(unittest.TestCase):
    def test_corrupt_json_skipped_other_results_returned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            stage_dir = tmp_path / "stages"
            stage_dir.mkdir()
            # Write one valid result
            good = make_stage_result(stage_name="good-stage", stage_index=0)
            write_stage_result(tmp_path, good)
            # Write one corrupt JSON file
            (stage_dir / "001-bad-stage.json").write_text("{corrupt json", encoding="utf-8")
            results = list_stage_results(tmp_path)
            names = {r.stage_name for r in results}
            self.assertIn("good-stage", names)

    def test_missing_stages_dir_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            # No stages/ subdir at all
            results = list_stage_results(Path(tmp_dir))
            self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# read_stage_result — corrupt JSON returns None
# ---------------------------------------------------------------------------


class TestReadStageResultCorrupt(unittest.TestCase):
    def test_corrupt_json_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            stage_dir = tmp_path / "stages"
            stage_dir.mkdir()
            (stage_dir / "000-corrupt.json").write_text("{bad json", encoding="utf-8")
            result = read_stage_result(tmp_path, "corrupt")
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
