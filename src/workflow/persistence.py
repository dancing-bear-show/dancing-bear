"""Stage result read/write and workspace management.

File-based persistence for workflow execution state. Each stage result is
written atomically to its own JSON file, enabling safe concurrent access
and easy retry of individual stages.

Architecture:
  - Workspace root: /tmp/{workflow_name}-{run_id}/
  - Stage results: stages/{index:03d}-{name}.json
  - Manifest: manifest.json
  - Subdirs: stages/, outputs/, validation/
"""

from __future__ import annotations

import dataclasses
import glob
import json
import logging
import tempfile
from pathlib import Path

from core.fileutil import atomic_write_json
from workflow.models import ManifestRef, StageResult, StageStatus, WorkflowManifest

logger = logging.getLogger(__name__)

_SUBDIRS = ("stages", "outputs", "validation")


def init_workspace(
    workflow_name: str,
    run_id: str,
    base_dir: str | None = None,
) -> Path:
    """Create workspace directory for a workflow run.

    Default base: /tmp/{workflow_name}-{run_id}/
    Creates subdirs: stages/, outputs/, validation/
    Returns the workspace root path.
    """
    if base_dir is not None:
        root = Path(base_dir) / f"{workflow_name}-{run_id}"
    else:
        root = Path(tempfile.gettempdir()) / f"{workflow_name}-{run_id}"

    root.mkdir(parents=True, exist_ok=True)
    for sub in _SUBDIRS:
        (root / sub).mkdir(exist_ok=True)

    return root


def write_stage_result(
    workspace_dir: str | Path,
    result: StageResult,
) -> Path:
    """Write a StageResult to its own JSON file atomically.

    Path: {workspace_dir}/stages/{stage_index:03d}-{stage_name}.json
    Returns path to written file.
    """
    stages_dir = Path(workspace_dir) / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{result.stage_index:03d}-{result.stage_name}.json"
    target = stages_dir / filename

    data = dataclasses.asdict(result)
    data["status"] = result.status.value

    atomic_write_json(target, data)

    return target


def read_stage_result(
    workspace_dir: str | Path,
    stage_name: str,
) -> StageResult | None:
    """Load a StageResult from workspace by stage name.

    Scans stages/ dir for file matching *-{stage_name}.json.
    Returns None if not found. Handles corrupt JSON gracefully.
    """
    stages_dir = Path(workspace_dir) / "stages"

    # Path.glob() yields nothing for a missing directory rather than raising,
    # so a missing stages/ dir already lands in the `not matches` return below.
    #
    # stage_name comes from user-authored YAML and is interpolated into a glob
    # pattern, so escape it: an unescaped '*' or '[...]' would match a
    # DIFFERENT stage's result file, and max(matches) would then return that
    # stage's status as if it were this one's.
    pattern = f"[0-9][0-9][0-9]-{glob.escape(stage_name)}.json"
    matches = list(stages_dir.glob(pattern))

    if not matches:
        return None

    path = max(matches)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _deserialize_stage_result(data)
    except (json.JSONDecodeError, FileNotFoundError, KeyError, TypeError) as exc:
        logger.warning("Failed to read stage result %s: %s", path, exc)
        return None


def list_stage_results(workspace_dir: str | Path) -> list[StageResult]:
    """Load all stage results from workspace, sorted by stage_index."""
    stages_dir = Path(workspace_dir) / "stages"
    if not stages_dir.exists():
        return []

    results: list[StageResult] = []
    for path in stages_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result = _deserialize_stage_result(data)
            results.append(result)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping corrupt stage result %s: %s", path, exc)
            continue  # nosec B112 - skip malformed entries silently

    results.sort(key=lambda r: r.stage_index)
    return results


def write_manifest(
    workspace_dir: str | Path,
    manifest: WorkflowManifest,
    *,
    yaml_path: str = "",
    run_id: str = "",
    trigger_params: dict[str, str] | None = None,
) -> Path:
    """Write a manifest reference to workspace root as manifest.json."""
    target = Path(workspace_dir) / "manifest.json"
    data = {
        "yaml_path": yaml_path,
        "workspace_dir": str(workspace_dir),
        "run_id": run_id,
        "compiled_at": manifest.compiled_at,
        "trigger_params": trigger_params or {},
        "manifest_version": manifest.manifest_version,
        "workflow_name": manifest.definition.name,
        "total_stages": len(manifest.definition.stages),
        "parallel_groups": [list(g) for g in manifest.parallel_groups],
    }
    atomic_write_json(target, data)
    return target


def read_manifest(workspace_dir: str | Path) -> ManifestRef | None:
    """Load a manifest reference from workspace. Returns None if not found."""
    path = Path(workspace_dir) / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ManifestRef(
            yaml_path=data.get("yaml_path", ""),
            workspace_dir=data.get("workspace_dir", str(workspace_dir)),
            run_id=data.get("run_id", ""),
            compiled_at=data.get("compiled_at", ""),
            trigger_params=data.get("trigger_params", {}),
            manifest_version=data.get("manifest_version", 1),
        )
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        logger.warning("Failed to read manifest %s: %s", path, exc)
        return None


# -- Private helpers ----------------------------------------------------------


_STATUS_ALIASES: dict[str, str] = {
    "complete": "success",
    "completed": "success",
    "done": "success",
    "ok": "success",
    "error": "failed",
    "timeout": "failed",
    "blocked": "failed",
    "in_progress": "running",
    "completed_with_limitations": "success",
}


_FIELD_ALIASES: dict[str, str] = {
    "stage": "stage_name",
    "name": "stage_name",
    "index": "stage_index",
}


def _deserialize_stage_result(data: dict) -> StageResult:
    """Reconstruct a StageResult from a JSON-loaded dict.

    Tolerates agent-written JSON that may use non-standard field names
    or status values. Unknown fields are silently dropped.
    """
    normalized: dict[str, object] = {}
    for k, v in data.items():
        key = _FIELD_ALIASES.get(k, k)
        normalized[key] = v

    raw_status = str(normalized.get("status", "pending"))
    canonical = _STATUS_ALIASES.get(raw_status, raw_status)
    try:
        normalized["status"] = StageStatus(canonical)
    except ValueError:
        logger.warning("Unknown stage status '%s', defaulting to pending", raw_status)
        normalized["status"] = StageStatus.pending

    valid_fields = {f.name for f in dataclasses.fields(StageResult)}
    filtered = {k: v for k, v in normalized.items() if k in valid_fields}

    filtered.setdefault("stage_name", "unknown")
    filtered.setdefault("stage_index", 0)
    filtered.setdefault("started_at", "")
    filtered.setdefault("finished_at", "")
    filtered.setdefault("duration_ms", 0)
    try:
        filtered["duration_ms"] = int(filtered["duration_ms"] or 0)
    except (ValueError, TypeError):
        filtered["duration_ms"] = 0

    return StageResult(**filtered)
