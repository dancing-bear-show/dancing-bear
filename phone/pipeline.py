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


# -----------------------------------------------------------------------------
# Unused apps pipeline
# -----------------------------------------------------------------------------


@dataclass
class UnusedRequest:
    layout: Optional[str]
    backup: Optional[str]
    recent_path: Optional[str]
    keep_path: Optional[str]
    limit: int = 50
    threshold: float = 0.8
    format: str = "text"  # "text" or "csv"


class UnusedRequestConsumer(Consumer[UnusedRequest]):
    def __init__(self, request: UnusedRequest) -> None:
        self._request = request

    def consume(self) -> UnusedRequest:
        return self._request


@dataclass
class UnusedResult:
    rows: List[tuple]  # (app_id, score, location)
    format: str


class UnusedProcessor(Processor[UnusedRequest, ResultEnvelope[UnusedResult]]):
    def process(self, payload: UnusedRequest) -> ResultEnvelope[UnusedResult]:
        from .layout import rank_unused_candidates

        try:
            layout = load_layout(payload.layout, payload.backup)
        except LayoutLoadError as err:
            return ResultEnvelope(status="error", diagnostics={"message": str(err), "code": err.code})

        recent = _read_lines_file(payload.recent_path)
        keep = _read_lines_file(payload.keep_path)
        rows = rank_unused_candidates(layout, recent_ids=recent, keep_ids=keep)
        rows = [r for r in rows if r[1] >= payload.threshold][: payload.limit]

        return ResultEnvelope(status="success", payload=UnusedResult(rows=rows, format=payload.format))


class UnusedProducer(Producer[ResultEnvelope[UnusedResult]]):
    def produce(self, result: ResultEnvelope[UnusedResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg, file=sys.stderr)
            return
        assert result.payload is not None
        rows = result.payload.rows
        if result.payload.format == "csv":
            print("app,score,location")
            for app, score, loc in rows:
                print(f"{app},{score:.2f},{loc}")
        else:
            print("Likely unused app candidates (heuristic):")
            print("score  app                                   location")
            for app, score, loc in rows:
                print(f"{score:4.1f}  {app:36}  {loc}")


# -----------------------------------------------------------------------------
# Prune checklist pipeline
# -----------------------------------------------------------------------------


@dataclass
class PruneRequest:
    layout: Optional[str]
    backup: Optional[str]
    recent_path: Optional[str]
    keep_path: Optional[str]
    limit: int = 50
    threshold: float = 1.0
    mode: str = "offload"  # "offload" or "delete"
    out_path: Path = Path("out/ios.unused.prune_checklist.txt")


class PruneRequestConsumer(Consumer[PruneRequest]):
    def __init__(self, request: PruneRequest) -> None:
        self._request = request

    def consume(self) -> PruneRequest:
        return self._request


@dataclass
class PruneResult:
    lines: List[str]
    out_path: Path


class PruneProcessor(Processor[PruneRequest, ResultEnvelope[PruneResult]]):
    def process(self, payload: PruneRequest) -> ResultEnvelope[PruneResult]:
        from .layout import rank_unused_candidates

        try:
            layout = load_layout(payload.layout, payload.backup)
        except LayoutLoadError as err:
            return ResultEnvelope(status="error", diagnostics={"message": str(err), "code": err.code})

        recent = _read_lines_file(payload.recent_path)
        keep = _read_lines_file(payload.keep_path)
        rows = rank_unused_candidates(layout, recent_ids=recent, keep_ids=keep)
        rows = [r for r in rows if r[1] >= payload.threshold][: payload.limit]

        lines = []
        lines.append(f"Unused apps checklist — mode: {payload.mode.upper()}")
        lines.append("")
        lines.append("Instructions:")
        if payload.mode == "offload":
            lines.append("1) Settings → General → iPhone Storage → search for app → Offload App")
            lines.append("   or long‑press app icon → Remove App → Offload App")
        else:
            lines.append("1) Long‑press app icon → Remove App → Delete App")
            lines.append("   or Settings → General → iPhone Storage → Delete App")
        lines.append("")
        lines.append("Candidates:")
        for app, score, loc in rows:
            lines.append(f"- {app}  (score {score:.1f}; location: {loc})")

        return ResultEnvelope(status="success", payload=PruneResult(lines=lines, out_path=payload.out_path))


class PruneProducer(Producer[ResultEnvelope[PruneResult]]):
    def produce(self, result: ResultEnvelope[PruneResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg, file=sys.stderr)
            return
        assert result.payload is not None
        out = result.payload.out_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(result.payload.lines) + "\n", encoding="utf-8")
        print(f"Wrote {out}")


# -----------------------------------------------------------------------------
# Analyze layout pipeline
# -----------------------------------------------------------------------------


@dataclass
class AnalyzeRequest:
    layout: Optional[str]
    backup: Optional[str]
    plan_path: Optional[str]
    format: str = "text"  # "text" or "json"


class AnalyzeRequestConsumer(Consumer[AnalyzeRequest]):
    def __init__(self, request: AnalyzeRequest) -> None:
        self._request = request

    def consume(self) -> AnalyzeRequest:
        return self._request


@dataclass
class AnalyzeResult:
    metrics: Dict[str, Any]
    format: str


class AnalyzeProcessor(Processor[AnalyzeRequest, ResultEnvelope[AnalyzeResult]]):
    def process(self, payload: AnalyzeRequest) -> ResultEnvelope[AnalyzeResult]:
        from .layout import analyze_layout

        try:
            layout = load_layout(payload.layout, payload.backup)
        except LayoutLoadError as err:
            return ResultEnvelope(status="error", diagnostics={"message": str(err), "code": err.code})

        plan = None
        if payload.plan_path:
            try:
                plan = read_yaml(Path(payload.plan_path))
            except FileNotFoundError:
                return ResultEnvelope(
                    status="error",
                    diagnostics={"message": f"Plan not found: {payload.plan_path}", "code": 2},
                )

        metrics = analyze_layout(layout, plan)
        return ResultEnvelope(status="success", payload=AnalyzeResult(metrics=metrics, format=payload.format))


class AnalyzeProducer(Producer[ResultEnvelope[AnalyzeResult]]):
    def produce(self, result: ResultEnvelope[AnalyzeResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg, file=sys.stderr)
            return
        assert result.payload is not None
        metrics = result.payload.metrics

        if result.payload.format == "json":
            import json
            print(json.dumps(metrics, indent=2))
            return

        # Text output
        print("Layout Summary")
        print(f"Dock: {metrics['dock_count']} apps")
        if metrics.get("dock"):
            print("  - " + ", ".join(metrics["dock"]))
        print(f"Pages: {metrics['pages_count']}")
        for p in metrics.get("pages", []):
            print(f"  Page {p['page']}: {p['root_apps']} apps, {p['folders']} folders (items {p['items_total']})")
        print(f"Folders: {metrics['totals']['folders']}")
        if metrics.get("folders"):
            top = sorted(metrics["folders"], key=lambda x: x.get("app_count", 0), reverse=True)[:5]
            for f in top:
                print(f"  - {f['name']} (page {f['page']}, {f['app_count']} apps)")
        if metrics.get("duplicates"):
            print("Duplicates:")
            for a in metrics["duplicates"]:
                print(f"  - {a}")
        if metrics.get("observations"):
            print("Observations:")
            for o in metrics["observations"]:
                print(f"- {o}")


# -----------------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------------


def _read_lines_file(path: Optional[str]) -> List[str]:
    """Read non-empty, non-comment lines from a file."""
    if not path:
        return []
    p = Path(path).expanduser()
    if not p.exists():
        return []
    try:
        return [
            ln.strip()
            for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    except Exception:
        return []
