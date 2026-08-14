"""Wi-Fi diagnostics pipeline components."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.cli_output import OutputFormat
from core.pipeline import BaseProducer, SafeProcessor, RequestConsumer

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
    output_format: OutputFormat = OutputFormat.TEXT
    out_path: Path | None = None


# Type alias for backward compatibility
DiagnoseRequestConsumer = RequestConsumer[DiagnoseRequest]


@dataclass
class DiagnoseResult:
    report: Report
    output_format: OutputFormat
    out_path: Path | None


class DiagnoseProcessor(SafeProcessor[DiagnoseRequest, DiagnoseResult]):
    def __init__(
        self,
        runner: CommandRunner | None = None,
        resolver: Callable[[str], DnsResult] | None = None,
        http_probe_fn: Callable[[str], HttpResult] | None = None,
        run_fn: Callable[..., Report] | None = None,
    ) -> None:
        self._runner = runner
        self._resolver = resolver
        self._http_probe_fn = http_probe_fn
        self._run_fn = run_fn

    def _process_safe(self, payload: DiagnoseRequest) -> DiagnoseResult:
        run = self._run_fn or run_diagnosis
        report = run(
            payload.config,
            runner=self._runner,
            resolver=self._resolver,
            http_probe_fn=self._http_probe_fn,
        )
        return DiagnoseResult(
            report=report,
            output_format=payload.output_format,
            out_path=payload.out_path,
        )


class DiagnoseProducer(BaseProducer):
    def _produce_success(self, payload: DiagnoseResult, diagnostics: dict[str, Any] | None) -> None:
        if payload.output_format == OutputFormat.JSON:
            content = json.dumps(report_to_dict(payload.report), indent=2)
        else:
            content = render_report(payload.report)
        if payload.out_path:
            out_path = payload.out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
        self._writer.print(content, end="")
