from __future__ import annotations

"""Schedule assistant pipeline components."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.pipeline import Consumer, Processor, Producer, ResultEnvelope
from personal_core.yamlio import dump_config as _dump_yaml


def _events_from_source(source: str, kind: Optional[str]) -> List[Dict[str, dict]]:
    from calendar_assistant.importer import load_schedule
    from calendar_assistant.model import normalize_event

    items = load_schedule(source, kind)
    events: List[Dict[str, dict]] = []
    for it in items:
        ev: Dict[str, dict] = {
            "subject": getattr(it, "subject", None),
            "start": getattr(it, "start_iso", None),
            "end": getattr(it, "end_iso", None),
            "repeat": getattr(it, "recurrence", None),
            "byday": getattr(it, "byday", None),
            "start_time": getattr(it, "start_time", None),
            "end_time": getattr(it, "end_time", None),
            "range": {
                "start_date": getattr(it, "range_start", None),
                "until": getattr(it, "range_until", None),
            },
            "count": getattr(it, "count", None),
            "location": getattr(it, "location", None),
            "body_html": getattr(it, "notes", None),
        }
        rng = ev.get("range") or {}
        if not rng.get("start_date") and not rng.get("until"):
            ev.pop("range", None)
        events.append(normalize_event(ev))
    return events


@dataclass
class PlanRequest:
    sources: List[str]
    kind: Optional[str]
    out_path: Path


class PlanRequestConsumer(Consumer[PlanRequest]):
    def __init__(self, request: PlanRequest) -> None:
        self._request = request

    def consume(self) -> PlanRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class PlanResult:
    document: Dict[str, dict]
    out_path: Path


class PlanProcessor(Processor[PlanRequest, ResultEnvelope[PlanResult]]):
    def __init__(self, loader: Callable[[str, Optional[str]], List[Dict[str, dict]]] = _events_from_source) -> None:
        self._loader = loader

    def process(self, payload: PlanRequest) -> ResultEnvelope[PlanResult]:
        all_events: List[Dict[str, dict]] = []
        for src in payload.sources:
            try:
                all_events.extend(self._loader(src, payload.kind))
            except Exception as exc:
                return ResultEnvelope(
                    status="error",
                    diagnostics={"message": f"Error loading source {src}: {exc}", "code": 2},
                )
        if not all_events:
            plan = {
                "#": "Add events under the 'events' key. Use subject, repeat/byday or start/end.",
                "events": [],
            }
        else:
            plan = {"events": all_events}
        return ResultEnvelope(status="success", payload=PlanResult(document=plan, out_path=payload.out_path))


class PlanProducer(Producer[ResultEnvelope[PlanResult]]):
    def produce(self, result: ResultEnvelope[PlanResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        _dump_yaml(str(result.payload.out_path), result.payload.document)
        events = result.payload.document.get("events", [])
        print(f"Wrote plan with {len(events)} events to {result.payload.out_path}")
