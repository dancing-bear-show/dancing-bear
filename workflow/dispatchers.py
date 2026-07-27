"""Pluggable dispatch strategies for workflow stage execution.

Defines the StageDispatcher protocol and four implementations:
- LocalDispatcher: runs invoke-mode CLI commands via subprocess
- SkillDispatcher: writes dispatch JSON for Claude Code skill agents
- WorkerQueueDispatcher: enqueues stages as background jobs via worker/queue.py
- CompositeDispatcher: routes invoke-only stages locally, worker_queue stages to
  WorkerQueueDispatcher, and all others to SkillDispatcher
"""

from __future__ import annotations

import enum
import json
import logging
import subprocess
import uuid
from pathlib import Path
from typing import Any, Protocol

from workflow._timeutil import iso_now
from workflow.dispatch import build_dispatch_instruction
from workflow.models import (
    OutputMode,
    ResolvedStage,
    StageKind,
    StageResult,
    StageStatus,
    make_stage_result,
)
from workflow.persistence import read_stage_result

__all__ = [
    "CompositeDispatcher",
    "LocalDispatcher",
    "SkillDispatcher",
    "StageDispatcher",
    "WorkerQueueDispatcher",
]

logger = logging.getLogger(__name__)


def _json_default(obj: object) -> object:
    """JSON serializer that renders enums as their value."""
    if isinstance(obj, enum.Enum):
        return obj.value
    return str(obj)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class StageDispatcher(Protocol):
    """Interface for stage execution strategies."""

    def dispatch(
        self,
        stage: ResolvedStage,
        workspace_dir: Path,
    ) -> StageResult:
        pass  # pragma: no cover

    def dispatch_group(
        self,
        stages: list[ResolvedStage],
        workspace_dir: Path,
    ) -> dict[str, StageResult]:
        pass  # pragma: no cover


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _dispatch_group_serial(
    dispatcher: StageDispatcher,
    stages: list[ResolvedStage],
    workspace_dir: Path,
) -> dict[str, StageResult]:
    """Serial group dispatch — shared by all dispatcher implementations."""
    return {
        stage.spec.name: dispatcher.dispatch(stage, workspace_dir)
        for stage in stages
    }


def _run_cli_command(cmd: str, *, timeout: int = 300) -> dict[str, Any]:
    """Run a shell command and return a structured result dict."""
    try:
        proc = subprocess.run(  # nosec B602 - shell=True required for CLI pipes; commands from trusted workflow YAML
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,  # noqa: S602
        )
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired:
        logger.warning("Command timed out after %ds: %s", timeout, cmd)
        return {"status": "timeout", "command": cmd}
    except OSError as exc:
        logger.warning("Command failed: %s — %s", cmd, exc)
        return {"status": "error", "command": cmd, "error": str(exc)}


# ---------------------------------------------------------------------------
# LocalDispatcher
# ---------------------------------------------------------------------------


class LocalDispatcher:
    """Runs invoke-mode CLI commands directly via subprocess."""

    def dispatch(
        self,
        stage: ResolvedStage,
        workspace_dir: Path,
    ) -> StageResult:
        started_at = iso_now()
        data, errors = self._run_outputs(stage)
        self._write_output_files(stage, data, workspace_dir)
        status = StageStatus.failed if errors else StageStatus.success
        return make_stage_result(stage, started_at, status, data, errors)

    def _run_outputs(
        self,
        stage: ResolvedStage,
    ) -> tuple[dict[str, Any], list[str]]:
        """Execute CLI commands for each output and collect results."""
        data: dict[str, Any] = {}
        errors: list[str] = []
        cmd_idx = 0
        for output in stage.spec.outputs:
            if output.mode == OutputMode.invoke and cmd_idx < len(stage.cli_commands):
                cmd = stage.cli_commands[cmd_idx]
                cmd_idx += 1
                result = _run_cli_command(cmd)
                data[output.name] = result
                if result.get("status") == "timeout":
                    errors.append(f"Command timed out: {cmd}")
                elif result.get("status") == "error":
                    errors.append(f"Command failed: {cmd}")
            elif output.mode == OutputMode.invoke:
                logger.warning(
                    "Stage '%s' output '%s' is invoke but no CLI command available (cmd_idx=%d, commands=%d)",
                    stage.spec.name, output.name, cmd_idx, len(stage.cli_commands),
                )
                data[output.name] = {"status": "error", "reason": "no_cli_command"}
            else:
                data[output.name] = {"status": "requires_agent", "mode": output.mode.value}
        return data, errors

    def _write_output_files(
        self,
        stage: ResolvedStage,
        data: dict[str, Any],
        workspace_dir: Path,
    ) -> None:
        """Write per-output files, mapping outputs to writes_to by position."""
        output_dir = workspace_dir / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs_list = stage.spec.outputs
        for i, filename in enumerate(stage.spec.writes_to):
            # Honor explicit prefixes (outputs/, validation/); bare names go under outputs/.
            if any(filename.startswith(p) for p in ("outputs/", "validation/", "stages/")):
                dest = workspace_dir / filename
            else:
                dest = output_dir / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            file_data = data.get(outputs_list[i].name, data) if i < len(outputs_list) else data
            content = file_data if isinstance(file_data, str) else json.dumps(file_data, indent=2, default=str)
            dest.write_text(content, encoding="utf-8")

    def dispatch_group(
        self,
        stages: list[ResolvedStage],
        workspace_dir: Path,
    ) -> dict[str, StageResult]:
        return _dispatch_group_serial(self, stages, workspace_dir)


# ---------------------------------------------------------------------------
# SkillDispatcher
# ---------------------------------------------------------------------------


class SkillDispatcher:
    """Writes dispatch JSON for skill-based agent execution.

    The Claude Code /workflow skill reads these files and spawns agents.
    Agents write stage result JSON when done. This dispatcher writes
    the dispatch instruction and returns a 'pending' result — the
    orchestrator or skill handles the actual wait.
    """

    def __init__(self, workflow_name: str) -> None:
        self._workflow_name = workflow_name

    def dispatch(
        self,
        stage: ResolvedStage,
        workspace_dir: Path,
    ) -> StageResult:
        started_at = iso_now()

        instruction = build_dispatch_instruction(
            stage, self._workflow_name, workspace_dir,
        )
        dispatch_dir = workspace_dir / "dispatch"
        dispatch_dir.mkdir(parents=True, exist_ok=True)
        path = dispatch_dir / f"{stage.index:03d}-{stage.spec.name}.json"
        path.write_text(json.dumps(instruction, indent=2, default=_json_default), encoding="utf-8")

        existing = read_stage_result(workspace_dir, stage.spec.name)
        if existing is not None:
            return existing

        return make_stage_result(
            stage, started_at, StageStatus.pending,
            {"dispatch_file": str(path)}, [],
        )

    def dispatch_group(
        self,
        stages: list[ResolvedStage],
        workspace_dir: Path,
    ) -> dict[str, StageResult]:
        return _dispatch_group_serial(self, stages, workspace_dir)


# ---------------------------------------------------------------------------
# WorkerQueueDispatcher
# ---------------------------------------------------------------------------


class WorkerQueueDispatcher:
    """Enqueues stages as background jobs via the worker file-based queue.

    Each stage becomes a Job with type="workflow_stage" and a payload carrying
    the workflow name, stage name, stage index, CLI commands, and any trigger
    params. The dispatcher returns a 'pending' StageResult immediately — the
    worker daemon processes the job asynchronously.
    """

    JOB_TYPE = "workflow_stage"

    def __init__(
        self,
        workflow_name: str,
        trigger_params: dict[str, str] | None = None,
    ) -> None:
        self._workflow_name = workflow_name
        self._trigger_params = dict(trigger_params or {})

    def _make_job_id(self, stage: ResolvedStage) -> str:
        # UUID suffix prevents collisions on workflow re-runs and avoids
        # path-unsafe characters from workflow/stage names reaching the queue dir.
        safe_wf = self._workflow_name.replace("/", "-").replace("..", "")
        safe_stage = stage.spec.name.replace("/", "-").replace("..", "")
        return f"{safe_wf}-{safe_stage}-{stage.index}-{uuid.uuid4().hex[:8]}"

    def dispatch(
        self,
        stage: ResolvedStage,
        workspace_dir: Path,
    ) -> StageResult:
        from worker.queue import Job, enqueue  # lazy import — worker is optional

        started_at = iso_now()
        job_id = self._make_job_id(stage)
        job = Job(
            id=job_id,
            type=self.JOB_TYPE,
            payload={
                "workflow_name": self._workflow_name,
                "stage_name": stage.spec.name,
                "stage_index": stage.index,
                "script": stage.spec.script,
                "cli_commands": list(stage.cli_commands),
                "workspace_dir": str(workspace_dir),
                "trigger_params": self._trigger_params,
            },
        )
        enqueue(job)
        logger.debug("Enqueued stage '%s' as job '%s'", stage.spec.name, job_id)

        return make_stage_result(
            stage, started_at, StageStatus.pending,
            {"job_id": job_id, "job_type": self.JOB_TYPE}, [],
        )

    def dispatch_group(
        self,
        stages: list[ResolvedStage],
        workspace_dir: Path,
    ) -> dict[str, StageResult]:
        return _dispatch_group_serial(self, stages, workspace_dir)


# ---------------------------------------------------------------------------
# CompositeDispatcher
# ---------------------------------------------------------------------------


class CompositeDispatcher:
    """Routes stages to the appropriate sub-dispatcher.

    Routing precedence (first match wins):

    1. Stage requires an agent (``kind=validate`` or any ``generate``/``template``
       output) → :class:`SkillDispatcher`
    2. ``stage.spec.executor == "inline"`` → raises NotImplementedError
    3. Otherwise (invoke-only outputs) → :class:`LocalDispatcher`
    """

    def __init__(
        self,
        workflow_name: str,
        trigger_params: dict[str, str] | None = None,
    ) -> None:
        self._local = LocalDispatcher()
        self._skill = SkillDispatcher(workflow_name)
        self._worker_queue = WorkerQueueDispatcher(workflow_name, trigger_params or {})

    def _needs_agent(self, stage: ResolvedStage) -> bool:
        """True if any output requires agent work (generate/template) or stage is validate/sub-workflow."""
        if stage.spec.kind in (StageKind.validate, StageKind.sub_workflow):
            return True
        return any(
            o.mode in (OutputMode.generate, OutputMode.template)
            for o in stage.spec.outputs
        )

    def dispatch(
        self,
        stage: ResolvedStage,
        workspace_dir: Path,
    ) -> StageResult:
        if stage.spec.executor == "worker_queue":
            return self._worker_queue.dispatch(stage, workspace_dir)
        if stage.spec.executor == "inline":
            raise NotImplementedError(
                f"stage '{stage.spec.name}' has executor='inline', which is only "
                "supported by the Claude /workflow skill orchestrator. "
                "The Python dispatcher (./bin/workflow run) does not implement inline "
                "execution. Use executor='agent' for stages run via the Python orchestrator."
            )
        if self._needs_agent(stage):
            return self._skill.dispatch(stage, workspace_dir)
        return self._local.dispatch(stage, workspace_dir)

    def dispatch_group(
        self,
        stages: list[ResolvedStage],
        workspace_dir: Path,
    ) -> dict[str, StageResult]:
        return _dispatch_group_serial(self, stages, workspace_dir)
