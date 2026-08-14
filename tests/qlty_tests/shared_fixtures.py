"""Shared helpers for qlty wrapper tests.

Fixtures are real qlty 0.640.0 output captured from this repo on 2026-08-14
(snippet bodies stripped for size). qlty is an external binary whose output
format is exactly what this wrapper does not control, so unit tests parse
captured payloads and never shell out to qlty.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from qlty.models import Finding, Location, Source, WireFormat
from qlty.runner import CompletedRun, InvocationResult

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> str:
    """Read a captured qlty payload."""
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeRunner:
    """QltyRunner stand-in returning canned InvocationResults per source.

    Records each invoke() call so tests can assert on scan scope without
    running the real binary.
    """

    def __init__(
        self,
        results: Optional[dict[Source, list[InvocationResult]]] = None,
    ) -> None:
        self._results = results or {}
        self.calls: list[tuple[Source, bool, tuple[str, ...], bool]] = []

    def invoke(
        self,
        source: Source,
        *,
        scan_all: bool = True,
        include_tests: bool = True,
        paths: Sequence[str] = (),
    ) -> InvocationResult:
        self.calls.append((source, scan_all, tuple(paths), include_tests))
        queued = self._results.get(source)
        if not queued:
            return InvocationResult(
                findings=(),
                wire_format=WireFormat.JSON,
                source=source,
                command=("qlty", source.value),
            )
        # Pop until one remains so repeated re-scans keep returning the last
        # queued result (models a repo that has settled).
        return queued.pop(0) if len(queued) > 1 else queued[0]


def make_finding(
    rule: str = "function-parameters",
    path: str = "src/example.py",
    line: int = 10,
    *,
    source: Source = Source.SMELLS,
    value: Optional[int] = 6,
    group_key: Optional[str] = None,
    message: str = "Function with many parameters (count = 6): example",
    level: str = "medium",
    other_locations: Sequence[Location] = (),
) -> Finding:
    """Build a Finding without going through a parser."""
    return Finding(
        rule=rule,
        location=Location(path=path, line=line),
        level=level,
        message=message,
        source=source,
        wire_format=WireFormat.JSON,
        value=value,
        group_key=group_key,
        other_locations=tuple(other_locations),
    )


def result_of(
    findings: Sequence[Finding],
    *,
    source: Source = Source.SMELLS,
    wire_format: WireFormat = WireFormat.JSON,
    degraded: bool = False,
    degrade_reason: str = "",
) -> InvocationResult:
    return InvocationResult(
        findings=tuple(findings),
        wire_format=wire_format,
        source=source,
        command=("qlty", source.value),
        degraded=degraded,
        degrade_reason=degrade_reason,
    )


def completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> CompletedRun:
    return CompletedRun(
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        command=("qlty", "smells"),
    )
