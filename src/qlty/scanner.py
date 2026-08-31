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
#
# Stability requires a "dry streak" of consecutive identical iterations, not just
# one match. A single pair of matching runs can be a coincidental double-cap --
# empirically, qlty returned the same empty set on two consecutive runs while 22
# real findings existed. The default streak of 2 means at least 3 iterations
# must agree before stability is declared.
_MAX_RESCAN_ITERATIONS = 8
_DEFAULT_DRY_STREAK = 2


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

    That hazard is specific to PATH-scoped scans. ``include_tests`` is
    therefore not read directly: ``effective_include_tests`` resolves it
    against the scan's scope and ``force_include_tests``, and is what the
    scanner passes to the runner.
    """

    scan_all: bool = True
    include_tests: bool = True
    paths: tuple[str, ...] = ()
    sources: tuple[Source, ...] = (Source.CHECK, Source.SMELLS)
    # Set by `--include-tests` to force test smells on when no paths are named.
    force_include_tests: bool = False

    @property
    def effective_include_tests(self) -> bool:
        """Whether to pass ``--include-tests`` to ``qlty smells`` for this scan.

        Three inputs, resolved in this order:

        1. ``include_tests`` False (``--no-include-tests``) -- off, always. It
           is an explicit opt-out and overrides everything below. The CLI
           rejects combining it with ``--include-tests``, but ScanRequest is
           constructible directly, so the precedence is defined here too.
        2. ``paths`` non-empty -- on. This is the case the whole setting exists
           for: ``qlty smells`` honours ``qlty.toml``'s ``test_patterns``, so
           naming a test file explicitly would otherwise analyse zero files and
           report a confident "clean" -- a false clean is worse than an error.
        3. Otherwise (repo-wide ``--all`` *or* diff-only ``--changed``, both of
           which name no paths) -- off unless ``force_include_tests``. Neither
           can hit the false-clean case, so the flag would only override
           ``test_patterns`` and surface smells CI never reports. In practice
           that is dominated by test fixture factories tripping
           ``function-parameters`` -- a rule ``qlty.toml`` itself documents as
           over-reporting keyword-only signatures -- which drown the findings
           that matter.
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
        dry_streak: int = _DEFAULT_DRY_STREAK,
    ) -> ScanResult:
        """Run the requested qlty sources and merge their findings.

        With ``rescan_until_stable``, repeats the whole scan until the finding
        identity set has been identical for ``dry_streak`` consecutive runs,
        because qlty's per-run issue cap means a single scan can under-report
        and even two consecutive matching runs can be a coincidental double-cap.

        ``dry_streak`` defaults to 2, meaning at least 3 iterations must agree
        before stability is declared. Raise it for thorough sweeps; lower to 1
        to restore the old (faster but less reliable) behaviour.
        """
        if rescan_until_stable:
            # Fail fast rather than silently weakening the guarantee. dry_streak
            # <= 0 satisfies `consecutive >= dry_streak` on the first comparison,
            # which reinstates the exact false-stable bug the streak exists to
            # prevent -- and does so invisibly, reporting stable=True.
            if dry_streak < 1:
                raise ValueError(f"dry_streak must be >= 1, got {dry_streak}")
            if max_iterations < 1:
                raise ValueError(
                    f"max_iterations must be >= 1, got {max_iterations}"
                )
        req = request or ScanRequest()
        result = self._scan_once(req)
        if not rescan_until_stable:
            return result
        return self._rescan(
            req,
            first=result,
            max_iterations=max_iterations,
            dry_streak=dry_streak,
        )

    def _rescan(
        self,
        request: ScanRequest,
        *,
        first: ScanResult,
        max_iterations: int,
        dry_streak: int,
    ) -> ScanResult:
        """Re-run until the identity set repeats ``dry_streak`` times, or iterations run out.

        Findings are accumulated across iterations rather than replaced: the
        point of re-scanning is that any single run may omit findings the cap
        crowded out, so the union is closer to the truth than the last run.

        Two consecutive matching runs are not enough to declare stability because
        qlty's cap is nondeterministic: the same capped subset can appear on two
        consecutive runs while many findings remain hidden. ``dry_streak``
        consecutive matching iterations are required before ``stable=True`` is
        returned. The default of 2 means at least 3 iterations must agree.

        Stability here is a statement about REPEATED IDENTITY SETS, not about
        the cap: nothing in qlty's output says a run was capped, so this code
        cannot detect that. ``stable=True`` means the identity set repeated
        ``dry_streak`` times; findings may still be missing. ``stable=False``
        means only that ``max_iterations`` was exhausted before that happened.
        Neither value proves the result is complete.
        """
        accumulated = _Accumulator()
        accumulated.absorb(first)
        accumulated.collapsed = first.duplicates_collapsed

        previous = first.identities()
        iterations = 1
        consecutive = 0  # how many consecutive runs matched ``previous``

        for _ in range(max(0, max_iterations - 1)):
            iterations += 1
            current = self._scan_once(request)
            accumulated.absorb(current)

            identities = current.identities()
            if identities == previous:
                consecutive += 1
                if consecutive >= dry_streak:
                    return accumulated.build(
                        iterations=iterations,
                        stable=True,
                        scope=request.scope,
                    )
            else:
                consecutive = 0
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
