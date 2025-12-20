from __future__ import annotations

"""Wi-Fi diagnostics pipeline components."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from core.pipeline import Consumer, Processor, Producer, ResultEnvelope

from .diagnostics import (
    CommandRunner,
    DiagnoseConfig,
    DnsResult,
    HttpResult,
    Report,
    render_report,
    report_to_dict,
    run_diagnosis,
)


@dataclass
class DiagnoseRequest:
    config: DiagnoseConfig
    emit_json: bool = False
    out_path: Optional[Path] = None


class DiagnoseRequestConsumer(Consumer[DiagnoseRequest]):
    def __init__(self, request: DiagnoseRequest) -> None:
        self._request = request

    def consume(self) -> DiagnoseRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class DiagnoseResult:
    report: Report
    emit_json: bool
    out_path: Optional[Path]


class DiagnoseProcessor(Processor[DiagnoseRequest, ResultEnvelope[DiagnoseResult]]):
    def __init__(
        self,
        runner: Optional[CommandRunner] = None,
        resolver: Optional[Callable[[str], DnsResult]] = None,
        http_probe_fn: Optional[Callable[[str], HttpResult]] = None,
        run_fn: Optional[Callable[..., Report]] = None,
    ) -> None:
        self._runner = runner
        self._resolver = resolver
        self._http_probe_fn = http_probe_fn
        self._run_fn = run_fn

    def process(self, payload: DiagnoseRequest) -> ResultEnvelope[DiagnoseResult]:
        try:
            run = self._run_fn or run_diagnosis
            report = run(
                payload.config,
                runner=self._runner,
                resolver=self._resolver,
                http_probe_fn=self._http_probe_fn,
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                diagnostics={"message": f"Diagnostics failed: {exc}", "code": 2},
            )
        return ResultEnvelope(
            status="success",
            payload=DiagnoseResult(
                report=report,
                emit_json=payload.emit_json,
                out_path=payload.out_path,
            ),
        )


class DiagnoseProducer(Producer[ResultEnvelope[DiagnoseResult]]):
    def produce(self, result: ResultEnvelope[DiagnoseResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        if result.payload.emit_json:
            content = json.dumps(report_to_dict(result.payload.report), indent=2)
        else:
            content = render_report(result.payload.report)
        if result.payload.out_path:
            out_path = result.payload.out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
        print(content, end="")
