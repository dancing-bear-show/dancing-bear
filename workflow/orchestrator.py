"""Workflow execution engine with pluggable dispatch.

Walks the compiled WorkflowManifest's parallel groups, dispatches stages
via a StageDispatcher, tracks results via persistence, and pauses on
human gates.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from workflow._fileutil import atomic_write_json
from workflow._timeutil import iso_now
from workflow.dispatchers import (
    CompositeDispatcher,
    StageDispatcher,
)
from workflow.models import (
    ResolvedStage,
    StageResult,
    StageStatus,
    WorkflowManifest,
    WorkflowRun,
    make_stage_result,
)
from workflow.compiler import resolve_params
from workflow.persistence import (
    init_workspace,
    list_stage_results,
    write_stage_result,
)

__all__ = [
    "WorkflowExecutionError",
    "WorkflowOrchestrator",
]

logger = logging.getLogger(__name__)


class WorkflowExecutionError(Exception):
    """Raised when workflow execution fails."""


class WorkflowOrchestrator:
    """Executes a compiled workflow manifest via pluggable dispatch."""

    def __init__(
        self,
        manifest: WorkflowManifest,
        workspace_dir: str | Path,
        *,
        run_id: str | None = None,
        dry_run: bool = False,
        dispatcher: StageDispatcher | None = None,
        trigger_params: dict[str, str] | None = None,
    ) -> None:
        """Initialize orchestrator.

        Args:
            manifest: Compiled workflow manifest.
            workspace_dir: Directory for stage results and outputs.
            run_id: Unique run identifier. Generated if not provided.
            dry_run: If True, log what would happen without executing.
            dispatcher: Stage execution strategy. Defaults to CompositeDispatcher.
            trigger_params: Parameters from the workflow trigger.
        """
        self._manifest = manifest
        self._dry_run = dry_run
        self._results: dict[str, StageResult] = {}
        self._status = StageStatus.pending
        self._trigger_params = trigger_params or {}

        name = manifest.definition.name
        self._run_id = run_id or f"{name}-{iso_now()}-{uuid.uuid4().hex[:8]}"

        self._workspace_dir = init_workspace(
            workflow_name=name,
            run_id=self._run_id,
            base_dir=str(workspace_dir),
        )

        self._dispatcher: StageDispatcher = dispatcher or CompositeDispatcher(
            name, trigger_params=self._trigger_params,
        )

        self._stages_by_name: dict[str, ResolvedStage] = manifest.resolved_stages

    # -- Public API -----------------------------------------------------------

    @classmethod
    def resume(
        cls,
        manifest: WorkflowManifest,
        workspace_dir: str | Path,
        *,
        dispatcher: StageDispatcher | None = None,
        trigger_params: dict[str, str] | None = None,
    ) -> WorkflowOrchestrator:
        """Resume a workflow from existing workspace state.

        Reads existing stage results and skips completed groups.
        """
        orch = cls.__new__(cls)
        orch._manifest = manifest
        orch._dry_run = False
        orch._trigger_params = trigger_params or {}
        orch._status = StageStatus.running

        name = manifest.definition.name
        orch._run_id = f"{name}-resumed-{uuid.uuid4().hex[:8]}"
        orch._workspace_dir = Path(workspace_dir)
        orch._dispatcher = dispatcher or CompositeDispatcher(
            name, trigger_params=orch._trigger_params,
        )
        orch._stages_by_name = manifest.resolved_stages

        existing = list_stage_results(Path(workspace_dir))
        orch._results = {
            r.stage_name: r for r in existing if r.status == StageStatus.success
        }
        return orch

    def run(self) -> WorkflowRun:
        """Execute the workflow end-to-end.

        Walks parallel groups sequentially. Within each group, stages
        execute via the configured dispatcher. Human gates pause execution.

        Returns:
            WorkflowRun with all stage results.
        """
        self._status = StageStatus.running
        started_at = iso_now()

        for group in self._manifest.parallel_groups:
            group_results = self._run_group(group)
            self._results.update(group_results)

            early_exit = self._process_group_results(group, group_results, started_at)
            if early_exit is not None:
                return early_exit

        self._status = StageStatus.success
        return self._build_run(started_at)

    def run_stage(self, stage_name: str) -> StageResult:
        """Execute a single stage by name.

        Raises:
            WorkflowExecutionError: If the stage name is not in the manifest.
        """
        if stage_name not in self._stages_by_name:
            raise WorkflowExecutionError(
                f"Unknown stage '{stage_name}' — "
                f"known stages: {sorted(self._stages_by_name)}"
            )

        resolved = self._stages_by_name[stage_name]
        started_at = iso_now()

        if self._dry_run:
            return make_stage_result(
                resolved, started_at, StageStatus.skipped,
                data={"dry_run": True},
                metadata={"run_id": self._run_id, "dry_run": self._dry_run},
            )

        try:
            result = self._dispatcher.dispatch(
                resolved, self._workspace_dir,
            )
        except (OSError, ValueError, KeyError, RuntimeError, WorkflowExecutionError) as exc:
            logger.warning("Stage '%s' failed: %s", stage_name, exc)
            result = make_stage_result(
                resolved, started_at, StageStatus.failed,
                errors=[f"Stage execution failed: {exc}"],
                metadata={"run_id": self._run_id, "dry_run": self._dry_run},
            )

        self._results[stage_name] = result
        return result

    @property
    def results(self) -> dict[str, StageResult]:
        """Current stage results."""
        return dict(self._results)

    @property
    def status(self) -> StageStatus:
        """Overall workflow status based on stage results."""
        return self._status

    # -- Private helpers ------------------------------------------------------

    def _process_group_results(
        self,
        group: tuple[str, ...],
        group_results: dict[str, StageResult],
        started_at: str,
    ) -> WorkflowRun | None:
        """Persist results, check failures and gates. Returns WorkflowRun if halting."""
        for result in group_results.values():
            write_stage_result(self._workspace_dir, result)

        if self._any_required_failed(group_results):
            self._status = StageStatus.failed
            return self._build_run(started_at)

        for name in group:
            stage = self._stages_by_name.get(name)
            if stage is None:
                continue
            if (
                stage.spec.human_gate
                and group_results[name].status == StageStatus.success
            ):
                self._status = StageStatus.awaiting_human
                return self._build_run(started_at)

        if any(
            group_results[name].status == StageStatus.pending
            for name in group
        ):
            self._status = StageStatus.pending
            return self._build_run(started_at)

        return None

    def _any_required_failed(
        self,
        group_results: dict[str, StageResult],
    ) -> bool:
        """Return True if any required stage in the group failed."""
        for name, result in group_results.items():
            if result.status != StageStatus.failed:
                continue
            stage = self._stages_by_name.get(name)
            if stage is None:
                logger.warning("Stage '%s' not in manifest, skipping failure check", name)
                continue
            if stage.spec.required:
                return True
        return False

    def _eval_when(self, when: str | None, params: dict[str, str]) -> bool:
        """Evaluate a stage's when condition against resolved trigger params.

        Returns True (run the stage) when:
        - when is None — no condition, always run
        - the expression evaluates to True

        Supported expression forms:
        - '"{param}" does not contain "value"' → value not in resolved_param
        - '"{param}" contains "value"'          → value in resolved_param
        """
        if when is None:
            return True

        expr = resolve_params(when, params)

        m = re.fullmatch(r'"(.*?)"\s+does not contain\s+"(.*?)"', expr)
        if m:
            return m.group(2) not in m.group(1)

        m = re.fullmatch(r'"(.*?)"\s+contains\s+"(.*?)"', expr)
        if m:
            return m.group(2) in m.group(1)

        raise WorkflowExecutionError(
            f"Unrecognised 'when' expression at runtime"
            f" (should have been caught at compile time): {when!r}"
        )

    def _skip_stage(self, stage: ResolvedStage) -> StageResult:
        """Record a when-condition skip and write sentinel output files."""
        started_at = iso_now()
        if not self._dry_run:
            for rel_path in stage.spec.writes_to:
                # Mirror the same prefix logic as dispatchers._write_output_files.
                if any(rel_path.startswith(p) for p in ("outputs/", "validation/", "stages/")):
                    dest = self._workspace_dir / rel_path
                else:
                    dest = self._workspace_dir / "outputs" / rel_path
                atomic_write_json(dest, {})
        logger.info("Stage '%s' skipped — when condition false: %r", stage.spec.name, stage.spec.when)
        return make_stage_result(
            stage, started_at, StageStatus.skipped,
            data={"skipped_by_when": stage.spec.when},
        )

    def _run_group(self, group: tuple[str, ...]) -> dict[str, StageResult]:
        """Execute all stages in a parallel group via the dispatcher."""
        params = dict(self._manifest.definition.trigger.params)
        params.update(self._trigger_params)

        results: dict[str, StageResult] = {}
        to_dispatch: list[ResolvedStage] = []

        for name in group:
            stage = self._stages_by_name[name]
            if name in self._results:
                results[name] = self._results[name]
            elif not self._eval_when(stage.spec.when, params):
                results[name] = self._skip_stage(stage)
            else:
                to_dispatch.append(stage)

        if self._dry_run:
            results.update({stage.spec.name: self.run_stage(stage.spec.name) for stage in to_dispatch})
            return results

        if not to_dispatch:
            return results

        try:
            dispatched = self._dispatcher.dispatch_group(
                to_dispatch, self._workspace_dir,
            )
        except (OSError, ValueError, KeyError, RuntimeError, WorkflowExecutionError):
            dispatched = {stage.spec.name: self.run_stage(stage.spec.name) for stage in to_dispatch}

        results.update(dispatched)
        return results

    def _build_run(self, started_at: str) -> WorkflowRun:
        """Construct a WorkflowRun from current state."""
        return WorkflowRun(
            manifest=self._manifest,
            workspace_dir=str(self._workspace_dir),
            run_id=self._run_id,
            started_at=started_at,
            status=self._status,
            stage_results=dict(self._results),
        )
