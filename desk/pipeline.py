"""Desk assistant pipeline components (scan/plan/apply)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from core.pipeline import Consumer, Processor, Producer, ResultEnvelope
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
    debug: bool


class ScanRequestConsumer(Consumer[ScanRequest]):
    def __init__(self, request: ScanRequest) -> None:
        self._request = request

    def consume(self) -> ScanRequest:  # pragma: no cover - trivial
        return self._request


class ScanProcessor(Processor[ScanRequest, Dict[str, Any]]):
    def __init__(self, runner: Callable[..., Dict[str, Any]] = run_scan) -> None:
        self._runner = runner

    def process(self, payload: ScanRequest) -> Dict[str, Any]:
        return self._runner(
            paths=payload.paths,
            min_size=payload.min_size,
            older_than=payload.older_than,
            include_duplicates=payload.include_duplicates,
            top_dirs=payload.top_dirs,
            debug=payload.debug,
        )


@dataclass
class PlanRequest:
    config_path: str


class PlanRequestConsumer(Consumer[PlanRequest]):
    def __init__(self, request: PlanRequest) -> None:
        self._request = request

    def consume(self) -> PlanRequest:  # pragma: no cover
        return self._request


class PlanProcessor(Processor[PlanRequest, Dict[str, Any]]):
    def __init__(self, planner: Callable[[str], Dict[str, Any]] = plan_from_config) -> None:
        self._planner = planner

    def process(self, payload: PlanRequest) -> Dict[str, Any]:
        return self._planner(payload.config_path)


@dataclass
class ApplyRequest:
    plan_path: str
    dry_run: bool


class ApplyRequestConsumer(Consumer[ApplyRequest]):
    def __init__(self, request: ApplyRequest) -> None:
        self._request = request

    def consume(self) -> ApplyRequest:  # pragma: no cover
        return self._request


class ApplyProcessor(Processor[ApplyRequest, ResultEnvelope[None]]):
    def __init__(self, applier: Callable[[str, bool], None] = apply_plan_file) -> None:
        self._applier = applier

    def process(self, payload: ApplyRequest) -> ResultEnvelope[None]:
        try:
            self._applier(payload.plan_path, dry_run=payload.dry_run)
            return ResultEnvelope(status="success")
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"error": str(exc)})


class ReportProducer(Producer[Dict[str, Any]]):
    def __init__(self, out_path: Optional[str]) -> None:
        self._out_path = out_path

    def produce(self, result: Dict[str, Any]) -> None:
        dump_output(result, self._out_path)


class ApplyResultProducer(Producer[ResultEnvelope[None]]):
    def produce(self, result: ResultEnvelope[None]) -> None:
        if not result.ok():
            error = (result.diagnostics or {}).get("error", "unknown error")
            print(f"[desk] apply failed: {error}")
