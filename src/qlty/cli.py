"""qlty wrapper CLI using the CLIApp framework."""

from __future__ import annotations

import sys
from functools import lru_cache
from typing import Optional, Sequence

from core.assistant import BaseAssistant
from core.cli_errors import ExitCode, UsageError
from core.cli_framework import CLIApp

from . import report
from .meta import META
from .models import Finding, Source, Tier
from .report import TriageEntry
from .runner import QltyRunner
from .scanner import ScanRequest, ScanResult, Scanner, sibling_uses_params_object
from .strategies import known_strategies, strategy_for

assistant = BaseAssistant(META.app_id, META.agentic_fallback)

app = CLIApp(
    "qlty-assistant",
    "qlty scanning and triage wrapper",
    add_common_args=False,  # own --format flag; avoids --output collision
)

_FORMATS = ("text", "json", "md", "csv")


def _format_argument(func):
    """Attach the shared --format flag."""
    return app.argument(
        "--format", choices=_FORMATS, default="text", dest="format",
        help="Output format",
    )(func)


def _scan_arguments(func):
    """Attach the flags every scanning command shares.

    scan and triage take the same inputs -- they differ only in how the result
    is rendered -- so the flag set is declared once. Decorators apply
    bottom-up, matching the original per-command ordering.
    """
    for add in (
        _format_argument,
        app.argument("--expect-min", type=int, help="Exit nonzero if fewer than N findings (env guard)"),
        app.argument("--rescan-until-stable", action="store_true", help="Re-scan until findings stop changing"),
        app.argument("--smells-only", action="store_true", help="Run only qlty smells"),
        app.argument("--check-only", action="store_true", help="Run only qlty check"),
        app.argument("--changed", action="store_true", help="Scan only changed files (default: all)"),
        app.argument("--no-include-tests", action="store_true", help="Exclude test files from smells on path-scoped scans"),
        app.argument("--include-tests", action="store_true", help="Include test files in smells on repo-wide scans"),
        app.argument("--rule", action="append", dest="rules", metavar="RULE",
                     help="Limit output to this rule (repeatable; unknown rule yields empty)"),
        app.argument("paths", nargs="*", help="Limit scan to these paths"),
    ):
        func = add(func)
    return func

# Rule whose triage requires the sibling-params-object cross-reference.
_PARAMS_RULE = "function-parameters"


@lru_cache(maxsize=1)
def _lazy_agentic():
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


def _build_scanner() -> Scanner:
    return Scanner(QltyRunner())


def _sources(args) -> tuple[Source, ...]:
    """Which qlty subcommands to run.

    Defaults to both: `check` and `smells` are disjoint sets, so running only
    one silently hides an entire class of findings.
    """
    if getattr(args, "smells_only", False):
        return (Source.SMELLS,)
    if getattr(args, "check_only", False):
        return (Source.CHECK,)
    return (Source.CHECK, Source.SMELLS)


def _rule_filter(args) -> tuple[str, ...]:
    """Normalized rule filter from --rule flags; empty means no filtering."""
    rules = getattr(args, "rules", None)
    return tuple(rules) if rules else ()


def _run_scan(args) -> tuple[ScanResult, ScanResult]:
    """Run a scan and return (raw_result, filtered_result).

    The raw result is used for --expect-min: the worktree-exclusion guard
    must fire on the actual scan total, not the post-filter total. Filtering
    to a rule with zero matches would otherwise trip the guard in a healthy
    environment, turning a valid usage of --rule into a false alarm.
    """
    if getattr(args, "changed", False) and getattr(args, "paths", None):
        raise UsageError(
            "--changed cannot be combined with explicit paths: naming paths already "
            "scopes the scan. Drop --changed, or drop the paths to scan changed "
            "files repo-wide."
        )

    if getattr(args, "include_tests", False) and getattr(args, "no_include_tests", False):
        # Direct opposites of one setting. Resolving them by precedence would
        # silently discard one of the two flags the caller explicitly passed.
        raise UsageError(
            "--include-tests and --no-include-tests are opposites; pass at most one."
        )

    request = ScanRequest(
        # F1: default to --all. Diff-only is opt-in, because `qlty check`
        # defaulting to changed-files-only reports "No issues" on a clean
        # branch, which is indistinguishable from a genuinely clean repo.
        scan_all=not getattr(args, "changed", False),
        include_tests=not getattr(args, "no_include_tests", False),
        force_include_tests=getattr(args, "include_tests", False),
        paths=tuple(getattr(args, "paths", ()) or ()),
        sources=_sources(args),
    )
    raw = _build_scanner().scan(
        request,
        rescan_until_stable=getattr(args, "rescan_until_stable", False),
    )
    return raw, raw.filter_by_rules(_rule_filter(args))


def _expect_min_failure(result: ScanResult, expect_min: Optional[int]) -> Optional[str]:
    """Message when a scan returned implausibly few findings.

    An empty scan is shaped exactly like success, so it needs an explicit
    guard. Common causes: the scan path is covered by ``exclude_patterns``,
    ``qlty check`` defaulted to changed-files-only on a clean branch, or the
    path simply does not exist. Treat a suspiciously clean scan as a broken
    environment rather than a clean repo.

    (The historical ``**/.claude/**`` worktree trap is fixed -- the exclusion
    was narrowed to ``**/.claude/worktrees/**`` -- but the guard still earns
    its place for the other causes.)
    """
    if expect_min is None or result.total >= expect_min:
        return None
    return (
        f"expected at least {expect_min} findings, got {result.total}. "
        "A near-empty scan usually means the scan path was excluded by "
        ".qlty/qlty.toml, or that `qlty check` fell back to changed-files-only "
        "-- treat this as a broken environment, not a clean repo."
    )


def _emit(text: str) -> None:
    print(text)


def _render_scan(result: ScanResult, fmt: str) -> str:
    if fmt == "json":
        return report.render_scan_json(result)
    if fmt == "md":
        return report.render_scan_markdown(result)
    if fmt == "csv":
        return report.render_scan_csv(result)
    return report.render_scan_text(result)


@app.command("scan", help="Scan repo (check + smells merged) and list findings")
@_scan_arguments
def cmd_scan(args) -> int:
    """Run a merged qlty scan.

    ``QltyError`` is deliberately not caught: it is a ``CLIError``, so CLIApp's
    handler renders its message and hint on stderr and maps its exit code. The
    same holds for the ``UsageError`` ``_run_scan`` raises on ``--changed``
    combined with explicit paths.
    """
    raw, result = _run_scan(args)
    _emit(_render_scan(result, args.format))

    # --expect-min guards against an implausibly empty scan (zero findings from
    # an excluded or nonexistent path look identical to a clean repo). Apply it
    # to the raw scan total, not the post-filter total, so --rule never causes a
    # false alarm.
    failure = _expect_min_failure(raw, args.expect_min)
    if failure:
        print(f"error: {failure}", file=sys.stderr)
        return ExitCode.ERROR
    return ExitCode.SUCCESS


def _drift_candidates(findings: Sequence[Finding]) -> tuple[str, ...]:
    """Findings whose module already uses a params object.

    Ranking `function-parameters` by count is near-useless -- most findings are
    fixture factories or framework-injected handlers that are correct as-is.
    The real signal is drift from a pattern the module already established.
    """
    seen: list[str] = []
    for finding in findings:
        if not finding.file or finding.file in seen:
            continue
        if sibling_uses_params_object(finding.file):
            seen.append(finding.file)
    return tuple(seen)


def _build_triage(result: ScanResult) -> list[TriageEntry]:
    entries: list[TriageEntry] = []
    for rule, findings in result.by_rule().items():
        strategy = strategy_for(rule)
        drift: tuple[str, ...] = ()
        # Only compute the cross-reference where it carries signal, and never
        # for Tier D, which is report-only by construction.
        if rule == _PARAMS_RULE and strategy.tier is not Tier.D:
            drift = _drift_candidates(findings)
        entries.append(
            TriageEntry(
                strategy=strategy,
                findings=tuple(findings),
                drift_files=drift,
            )
        )
    return entries


@app.command("triage", help="Group findings by rule, attach tier + strategy")
@_scan_arguments
def cmd_triage(args) -> int:
    """Triage findings into tiers with remediation strategy.

    ``QltyError`` propagates to CLIApp's handler; see ``cmd_scan``.
    """
    raw, result = _run_scan(args)
    entries = _build_triage(result)

    if args.format == "json":
        _emit(report.render_triage_json(entries, result))
    elif args.format == "md":
        _emit(report.render_triage_markdown(entries, result))
    elif args.format == "csv":
        _emit(report.render_triage_csv(entries, result))
    else:
        _emit(report.render_triage_text(entries, result))

    # --expect-min: apply to raw total, same reasoning as cmd_scan.
    failure = _expect_min_failure(raw, args.expect_min)
    if failure:
        print(f"error: {failure}", file=sys.stderr)
        return ExitCode.ERROR
    return ExitCode.SUCCESS


@app.command("rules", help="List known rules, tiers, and whether tooling exists")
@app.argument("--counts", action="store_true", help="Include live finding counts (runs a scan)")
@_format_argument
def cmd_rules(args) -> int:
    """List the rule strategy table.

    ``QltyError`` from the optional --counts scan propagates to CLIApp's
    handler; see ``cmd_scan``.
    """
    strategies = known_strategies()
    counts: Optional[dict[str, int]] = None

    if args.counts:
        result = _build_scanner().scan()
        counts = {rule: len(items) for rule, items in result.by_rule().items()}

    if args.format == "json":
        _emit(report.render_rules_json(strategies, counts))
    elif args.format == "md":
        _emit(report.render_rules_markdown(strategies, counts))
    elif args.format == "csv":
        _emit(report.render_rules_csv(strategies, counts))
    else:
        _emit(report.render_rules_text(strategies, counts))
    return ExitCode.SUCCESS


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for the qlty CLI."""
    return app.run_with_assistant(
        assistant,
        emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact),
        argv=argv,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
