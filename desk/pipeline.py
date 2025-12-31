"""Desk assistant pipeline components (scan/plan/apply)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from core.pipeline import SafeProcessor, BaseProducer, RequestConsumer
from .apply_ops import apply_plan_file
from .planner import plan_from_config
from .scan import run_scan
from .utils import dump_output


@dataclass
class ScanRequest:
    paths: List[str]
    min_size: str
    older_than: Optional[str]
    include_duplicates: bool
    top_dirs: int


# Type alias using generic RequestConsumer from core.pipeline
ScanRequestConsumer = RequestConsumer[ScanRequest]


class ScanProcessor(SafeProcessor[ScanRequest, Dict[str, Any]]):
    """Scan for large, stale, and duplicate files with automatic error handling."""

    def __init__(self, runner: Callable[..., Dict[str, Any]] = run_scan) -> None:
        self._runner = runner

    def _process_safe(self, payload: ScanRequest) -> Dict[str, Any]:
        return self._runner(
            paths=payload.paths,
            min_size=payload.min_size,
            older_than=payload.older_than,
            include_duplicates=payload.include_duplicates,
            top_dirs=payload.top_dirs,
        )


@dataclass
class PlanRequest:
    config_path: str


# Type alias using generic RequestConsumer from core.pipeline
PlanRequestConsumer = RequestConsumer[PlanRequest]


class PlanProcessor(SafeProcessor[PlanRequest, Dict[str, Any]]):
    """Create a plan from config rules with automatic error handling."""

    def __init__(self, planner: Callable[[str], Dict[str, Any]] = plan_from_config) -> None:
        self._planner = planner

    def _process_safe(self, payload: PlanRequest) -> Dict[str, Any]:
        return self._planner(payload.config_path)


@dataclass
class ApplyRequest:
    plan_path: str
    dry_run: bool


# Type alias using generic RequestConsumer from core.pipeline
ApplyRequestConsumer = RequestConsumer[ApplyRequest]


class ApplyProcessor(SafeProcessor[ApplyRequest, None]):
    """Apply operations from a plan file with automatic error handling."""

    def __init__(self, applier: Callable[[str, bool], None] = apply_plan_file) -> None:
        self._applier = applier

    def _process_safe(self, payload: ApplyRequest) -> None:
        self._applier(payload.plan_path, dry_run=payload.dry_run)


class ReportProducer(BaseProducer):
    """Produce output for scan/plan results with automatic error handling."""

    def __init__(self, out_path: Optional[str]) -> None:
        self._out_path = out_path

    def _produce_success(self, payload: Dict[str, Any], diagnostics: Optional[Dict[str, Any]]) -> None:
        dump_output(payload, self._out_path)


class ApplyResultProducer(BaseProducer):
    """Produce output for apply operations with automatic error handling."""

    def _produce_success(self, payload: None, diagnostics: Optional[Dict[str, Any]]) -> None:
        # Success is silent - no output needed
        pass
