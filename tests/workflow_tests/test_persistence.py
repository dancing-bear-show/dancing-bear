"""Tests for workflow.persistence — workspace management and stage result I/O."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_init_workspace_creates_subdirs(tmp_path: Path) -> None:
    workspace = init_workspace("my-workflow", "run-001", base_dir=str(tmp_path))

    for subdir in _SUBDIRS:
        assert (workspace / subdir).is_dir(), f"Expected subdir '{subdir}' to exist"


def test_init_workspace_returns_path(tmp_path: Path) -> None:
    workspace = init_workspace("my-workflow", "run-001", base_dir=str(tmp_path))

    assert isinstance(workspace, Path)
    assert workspace.is_dir()


def test_init_workspace_uses_provided_base_dir(tmp_path: Path) -> None:
    workspace = init_workspace("wf", "run-id", base_dir=str(tmp_path))

    assert workspace.is_dir()
    assert str(tmp_path) in str(workspace)


# ---------------------------------------------------------------------------
# 2. write_stage_result / read_stage_result round-trip
# ---------------------------------------------------------------------------


def test_write_and_read_stage_result_round_trip(tmp_path: Path) -> None:
    result = make_stage_result(stage_name="gather-filters", stage_index=0)
    write_stage_result(tmp_path, result)

    loaded = read_stage_result(tmp_path, "gather-filters")

    assert loaded is not None
    assert loaded.stage_name == "gather-filters"
    assert loaded.stage_index == 0


def test_read_stage_result_missing_returns_none(tmp_path: Path) -> None:
    result = read_stage_result(tmp_path, "nonexistent-stage")
    assert result is None


def test_write_stage_result_preserves_status(tmp_path: Path) -> None:
    result = make_stage_result(status=StageStatus.failed)
    write_stage_result(tmp_path, result)

    loaded = read_stage_result(tmp_path, "test-stage")

    assert loaded is not None
    assert loaded.status == StageStatus.failed


def test_write_stage_result_preserves_errors(tmp_path: Path) -> None:
    result = make_stage_result(errors=["timeout", "rate limit"])
    write_stage_result(tmp_path, result)

    loaded = read_stage_result(tmp_path, "test-stage")

    assert loaded is not None
    assert "timeout" in loaded.errors
    assert "rate limit" in loaded.errors


# ---------------------------------------------------------------------------
# 3. list_stage_results
# ---------------------------------------------------------------------------


def test_list_stage_results_empty_workspace(tmp_path: Path) -> None:
    init_workspace("wf", "run-1", base_dir=str(tmp_path))
    workspace = tmp_path / "wf" / "run-1"
    results = list_stage_results(workspace)
    assert results == []


def test_list_stage_results_returns_written_results(tmp_path: Path) -> None:
    result_a = make_stage_result(stage_name="stage-a", stage_index=0)
    result_b = make_stage_result(stage_name="stage-b", stage_index=1)
    write_stage_result(tmp_path, result_a)
    write_stage_result(tmp_path, result_b)

    results = list_stage_results(tmp_path)

    names = {r.stage_name for r in results}
    assert "stage-a" in names
    assert "stage-b" in names


# ---------------------------------------------------------------------------
# 4. write_manifest / read_manifest round-trip
# ---------------------------------------------------------------------------


def test_write_and_read_manifest_round_trip(tmp_path: Path) -> None:
    manifest = make_workflow_manifest()
    write_manifest(tmp_path, manifest)

    loaded = read_manifest(tmp_path)

    assert loaded is not None
    # read_manifest returns a ManifestRef (lightweight reference), not the full manifest
    assert loaded.manifest_version == manifest.manifest_version


def test_read_manifest_missing_returns_none(tmp_path: Path) -> None:
    loaded = read_manifest(tmp_path)
    assert loaded is None
