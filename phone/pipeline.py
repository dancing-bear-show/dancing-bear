from __future__ import annotations

"""Phone assistant pipeline components (export, plan, checklist)."""

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from core.pipeline import Consumer, Processor, Producer, ResultEnvelope

from .helpers import LayoutLoadError, load_layout, read_yaml, write_yaml
from .layout import checklist_from_plan, scaffold_plan, to_yaml_export


@dataclass
class ExportRequest:
    backup: Optional[str]
    out_path: Path


class ExportRequestConsumer(Consumer[ExportRequest]):
    def __init__(self, request: ExportRequest) -> None:
        self._request = request

    def consume(self) -> ExportRequest:  # pragma: no cover - simple
        return self._request


@dataclass
class ExportResult:
    document: Dict[str, Any]
    out_path: Path


class ExportProcessor(Processor[ExportRequest, ResultEnvelope[ExportResult]]):
    def process(self, payload: ExportRequest) -> ResultEnvelope[ExportResult]:
        try:
            layout = load_layout(None, payload.backup)
        except LayoutLoadError as err:
            return ResultEnvelope(status="error", diagnostics={"message": str(err), "code": err.code})
        except Exception as exc:  # pragma: no cover - unexpected IO errors
            return ResultEnvelope(status="error", diagnostics={"message": f"Error: {exc}", "code": 4})
        export = to_yaml_export(layout)
        return ResultEnvelope(status="success", payload=ExportResult(document=export, out_path=payload.out_path))


class ExportProducer(Producer[ResultEnvelope[ExportResult]]):
    def produce(self, result: ResultEnvelope[ExportResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg, file=sys.stderr)
            return
        assert result.payload is not None  # for type checker
        write_yaml(result.payload.document, result.payload.out_path)
        print(f"Wrote layout export to {result.payload.out_path}")


@dataclass
class PlanRequest:
    layout: Optional[str]
    backup: Optional[str]
    out_path: Path


class PlanRequestConsumer(Consumer[PlanRequest]):
    def __init__(self, request: PlanRequest) -> None:
        self._request = request

    def consume(self) -> PlanRequest:  # pragma: no cover
        return self._request


@dataclass
class PlanResult:
    document: Dict[str, Any]
    out_path: Path


class PlanProcessor(Processor[PlanRequest, ResultEnvelope[PlanResult]]):
    def process(self, payload: PlanRequest) -> ResultEnvelope[PlanResult]:
        try:
            layout = load_layout(payload.layout, payload.backup)
        except LayoutLoadError as err:
            return ResultEnvelope(status="error", diagnostics={"message": str(err), "code": err.code})
        plan = scaffold_plan(layout)
        return ResultEnvelope(status="success", payload=PlanResult(document=plan, out_path=payload.out_path))


class PlanProducer(Producer[ResultEnvelope[PlanResult]]):
    def produce(self, result: ResultEnvelope[PlanResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg, file=sys.stderr)
            return
        assert result.payload is not None
        write_yaml(result.payload.document, result.payload.out_path)
        print(f"Wrote plan scaffold to {result.payload.out_path}")


@dataclass
class ChecklistRequest:
    plan_path: Path
    layout: Optional[str]
    backup: Optional[str]
    out_path: Path


class ChecklistRequestConsumer(Consumer[ChecklistRequest]):
    def __init__(self, request: ChecklistRequest) -> None:
        self._request = request

    def consume(self) -> ChecklistRequest:  # pragma: no cover
        return self._request


@dataclass
class ChecklistResult:
    steps: List[str]
    out_path: Path


class ChecklistProcessor(Processor[ChecklistRequest, ResultEnvelope[ChecklistResult]]):
    def process(self, payload: ChecklistRequest) -> ResultEnvelope[ChecklistResult]:
        try:
            layout = load_layout(payload.layout, payload.backup)
        except LayoutLoadError as err:
            return ResultEnvelope(status="error", diagnostics={"message": str(err), "code": err.code})
        try:
            plan = read_yaml(payload.plan_path)
        except FileNotFoundError:
            return ResultEnvelope(status="error", diagnostics={"message": f"Plan not found: {payload.plan_path}", "code": 2})
        steps = checklist_from_plan(layout, plan)
        return ResultEnvelope(status="success", payload=ChecklistResult(steps=steps, out_path=payload.out_path))


class ChecklistProducer(Producer[ResultEnvelope[ChecklistResult]]):
    def produce(self, result: ResultEnvelope[ChecklistResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg, file=sys.stderr)
            return
        assert result.payload is not None
        out = result.payload.out_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(result.payload.steps) + "\n", encoding="utf-8")
        print(f"Wrote checklist to {out}")
