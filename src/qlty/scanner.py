"""Scan orchestration: merge check + smells, dedupe, and re-scan for stability.

``qlty check`` (lint/security) and ``qlty smells`` (structure/duplication) are
disjoint finding sets -- neither is a superset of the other -- so a complete
picture requires running both and merging (plan F2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from .models import Finding, Source, WireFormat
from .runner import QltyRunner

# radarlint caps issues per run, so one high-count cluster can crowd out
# findings elsewhere. Re-scan until the finding set stops changing, bounded so a
# genuinely unstable repo cannot loop forever.
_MAX_RESCAN_ITERATIONS = 5


@dataclass(frozen=True)
class ScanResult:
    """Merged, deduplicated finding set from one or more qlty invocations."""

    findings: tuple[Finding, ...]
    degradations: tuple[str, ...] = ()
    wire_formats: tuple[WireFormat, ...] = ()
    iterations: int = 1
    stable: bool = True
    scanned_all: bool = True
    duplicates_collapsed: int = 0

    @property
    def total(self) -> int:
        return len(self.findings)

    @property
    def degraded(self) -> bool:
        return bool(self.degradations)

    def by_rule(self) -> dict[str, list[Finding]]:
        """Findings grouped by rule, ordered by descending count then rule name."""
        grouped: dict[str, list[Finding]] = {}
        for finding in self.findings:
            grouped.setdefault(finding.rule, []).append(finding)
        return dict(
            sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        )

    def identities(self) -> set[tuple[str, str, int]]:
        """Finding identities, for comparing runs without trusting totals."""
        return {f.identity for f in self.findings}


@dataclass(frozen=True)
class ScanRequest:
    """What to scan. Grouped so it can be threaded through the scan stages.

    ``scan_all`` defaults to True: diff-only scanning reports "no issues" on a
    clean branch, which is indistinguishable from a clean repo (plan F1).
    """

    scan_all: bool = True
    paths: tuple[str, ...] = ()
    sources: tuple[Source, ...] = (Source.CHECK, Source.SMELLS)


@dataclass
class _Accumulator:
    """Collects findings and run metadata across one or more invocations.

    Also owns degradation notices and wire formats so the scan stages do not
    have to thread three parallel lists between them.
    """

    seen: dict[tuple[str, ...], Finding] = field(default_factory=dict)
    collapsed: int = 0
    degradations: list[str] = field(default_factory=list)
    wire_formats: list[WireFormat] = field(default_factory=list)

    def add(self, findings: Sequence[Finding]) -> None:
        for finding in findings:
            key = finding.dedup_key()
            if key in self.seen:
                self.collapsed += 1
                continue
            self.seen[key] = finding

    def note_degradation(self, reason: str) -> None:
        if reason and reason not in self.degradations:
            self.degradations.append(reason)

    def note_format(self, wire_format: WireFormat) -> None:
        if wire_format not in self.wire_formats:
            self.wire_formats.append(wire_format)

    def absorb(self, result: ScanResult) -> None:
        """Merge an existing result's findings and metadata."""
        self.add(result.findings)
        for reason in result.degradations:
            self.note_degradation(reason)
        for wire_format in result.wire_formats:
            self.note_format(wire_format)

    def ordered(self) -> tuple[Finding, ...]:
        return tuple(
            sorted(
                self.seen.values(),
                key=lambda f: (f.rule, f.location.path, f.location.line),
            )
        )

    def build(
        self, *, iterations: int, stable: bool, scanned_all: bool
    ) -> ScanResult:
        return ScanResult(
            findings=self.ordered(),
            degradations=tuple(self.degradations),
            wire_formats=tuple(self.wire_formats),
            iterations=iterations,
            stable=stable,
            scanned_all=scanned_all,
            duplicates_collapsed=self.collapsed,
        )


class Scanner:
    """Runs qlty check + smells and merges the results."""

    def __init__(self, runner: Optional[QltyRunner] = None) -> None:
        self._runner = runner or QltyRunner()

    def scan(
        self,
        request: Optional[ScanRequest] = None,
        *,
        rescan_until_stable: bool = False,
        max_iterations: int = _MAX_RESCAN_ITERATIONS,
    ) -> ScanResult:
        """Run the requested qlty sources and merge their findings.

        With ``rescan_until_stable``, repeats the whole scan until two
        consecutive runs report the same finding identities, because qlty's
        per-run issue cap means a single scan can under-report.
        """
        req = request or ScanRequest()
        result = self._scan_once(req)
        if not rescan_until_stable:
            return result
        return self._rescan(req, first=result, max_iterations=max_iterations)

    def _rescan(
        self,
        request: ScanRequest,
        *,
        first: ScanResult,
        max_iterations: int,
    ) -> ScanResult:
        """Re-run until the finding identity set repeats, or the cap is hit.

        Findings are accumulated across iterations rather than replaced: the
        point of re-scanning is that any single run may omit findings the cap
        crowded out, so the union is closer to the truth than the last run.
        """
        accumulated = _Accumulator()
        accumulated.absorb(first)
        accumulated.collapsed = first.duplicates_collapsed

        previous = first.identities()
        iterations = 1

        for _ in range(max(0, max_iterations - 1)):
            iterations += 1
            current = self._scan_once(request)
            accumulated.absorb(current)

            identities = current.identities()
            if identities == previous:
                return accumulated.build(
                    iterations=iterations,
                    stable=True,
                    scanned_all=request.scan_all,
                )
            previous = identities

        return accumulated.build(
            iterations=iterations, stable=False, scanned_all=request.scan_all
        )

    def _scan_once(self, request: ScanRequest) -> ScanResult:
        accumulated = _Accumulator()
        for source in request.sources:
            invocation = self._runner.invoke(
                source, scan_all=request.scan_all, paths=request.paths
            )
            accumulated.add(invocation.findings)
            if invocation.degraded:
                accumulated.note_degradation(invocation.degrade_reason)
            accumulated.note_format(invocation.wire_format)

        return accumulated.build(
            iterations=1, stable=True, scanned_all=request.scan_all
        )


def sibling_uses_params_object(
    module_path: str, root: Optional[Path] = None
) -> bool:
    """Whether a module already contains a params-object style dataclass.

    This is the cross-reference that separates signal from noise for
    ``function-parameters``: a high parameter count is only meaningful when
    sibling functions in the same module already wrap those arguments in a
    named object, making the finding *pattern drift* rather than a bare metric.
    Ranking by raw parameter count surfaced 31 findings of which 29 were noise;
    this check is what isolated the 2.

    Detection is deliberately textual (no import side effects): a module is
    considered to have the pattern when it defines a dataclass whose name ends
    in a params-object suffix.
    """
    suffixes = ("Params", "Request", "Options", "Config", "Patch", "Spec")
    base = root or Path.cwd()
    candidate = base / module_path
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        # Unreadable module: report "no evidence" rather than guessing, so the
        # finding stays in the default-LEAVE bucket.
        return False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("class "):
            continue
        name = stripped[len("class "):].split("(")[0].split(":")[0].strip()
        if name.endswith(suffixes):
            return True
    return False
