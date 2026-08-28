"""Scan orchestration: merge check + smells, dedupe, and re-scan for stability.

``qlty check`` (lint/security) and ``qlty smells`` (structure/duplication) are
disjoint finding sets -- neither is a superset of the other -- so a complete
picture requires running both and merging (plan F2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from .models import Finding, Scope, Source, WireFormat
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
    scope: Scope = Scope.ALL
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

    def filter_by_rules(self, rules: tuple[str, ...]) -> "ScanResult":
        """Return a copy restricted to findings matching any of the named rules.

        An unknown rule name yields zero findings for that rule rather than an
        error: callers should not need to validate rule names before filtering.
        Returns self unchanged when rules is empty so callers can skip the check.
        """
        if not rules:
            return self
        kept = tuple(f for f in self.findings if f.rule in rules)
        return ScanResult(
            findings=kept,
            degradations=self.degradations,
            wire_formats=self.wire_formats,
            iterations=self.iterations,
            stable=self.stable,
            scope=self.scope,
            duplicates_collapsed=self.duplicates_collapsed,
        )


@dataclass(frozen=True)
class ScanRequest:
    """What to scan. Grouped so it can be threaded through the scan stages.

    ``scan_all`` defaults to True: diff-only scanning reports "no issues" on a
    clean branch, which is indistinguishable from a clean repo (plan F1).

    ``include_tests`` defaults to True for the same reason: ``qlty smells``
    excludes anything matching ``.qlty/qlty.toml``'s ``test_patterns`` unless
    told otherwise, so scanning a test file silently analyzes zero files and
    reports a confident "clean" -- a false clean is worse than an error.

    That hazard is specific to PATH-scoped scans, so ``include_tests`` only
    takes effect there; see ``effective_include_tests``.
    """

    scan_all: bool = True
    include_tests: bool = True
    paths: tuple[str, ...] = ()
    sources: tuple[Source, ...] = (Source.CHECK, Source.SMELLS)
    # Set by `--include-tests` to force test smells on for a repo-wide scan.
    force_include_tests: bool = False

    @property
    def effective_include_tests(self) -> bool:
        """Whether to pass ``--include-tests`` to ``qlty smells`` for this scan.

        ``include_tests`` exists to stop a path-scoped scan of a test file from
        analysing zero files and reporting a confident "clean". A repo-wide scan
        cannot hit that: it always analyses hundreds of files. There, the flag
        does nothing but override ``qlty.toml``'s ``test_patterns`` and surface
        smells CI never sees -- 43 fixture-factory ``function-parameters``
        findings against a rule the config itself documents as over-reporting
        keyword-only signatures, drowning the real findings.

        So: on by default for path scans, off for repo-wide scans unless
        ``--include-tests`` explicitly asks for it.
        """
        if not self.include_tests:
            return False
        if self.paths:
            return True
        return self.force_include_tests

    @property
    def scope(self) -> Scope:
        """The scope this request actually scans.

        ``paths`` wins over ``scan_all`` because the runner drops ``--all``
        whenever paths are given -- qlty rejects the combination -- so a
        path-scoped scan covered neither the repo nor the diff, and reporting
        it as either would be a false clean.
        """
        if self.paths:
            return Scope.PATHS
        return Scope.ALL if self.scan_all else Scope.CHANGED


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
        self, *, iterations: int, stable: bool, scope: Scope
    ) -> ScanResult:
        return ScanResult(
            findings=self.ordered(),
            degradations=tuple(self.degradations),
            wire_formats=tuple(self.wire_formats),
            iterations=iterations,
            stable=stable,
            scope=scope,
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
                    scope=request.scope,
                )
            previous = identities

        return accumulated.build(
            iterations=iterations, stable=False, scope=request.scope
        )

    def _scan_once(self, request: ScanRequest) -> ScanResult:
        accumulated = _Accumulator()
        for source in request.sources:
            invocation = self._runner.invoke(
                source,
                scan_all=request.scan_all,
                include_tests=request.effective_include_tests,
                paths=request.paths,
            )
            accumulated.add(invocation.findings)
            if invocation.degraded:
                accumulated.note_degradation(invocation.degrade_reason)
            accumulated.note_format(invocation.wire_format)

        return accumulated.build(
            iterations=1, stable=True, scope=request.scope
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
    except OSError:  # nosec B110 - unreadable module is a no-evidence answer, not an error
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
