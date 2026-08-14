"""Renderers for scan and triage output (text / json / markdown).

All rendering strips ANSI escapes (plan F3): qlty emits heavy colour even when
its output is piped, which makes captured output unreadable for both humans and
LLM consumers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional, Sequence

from .models import Finding, RuleStrategy, Tier
from .scanner import ScanResult
from .strategies import strategy_for, tooling_for

# CSI sequences (colour, cursor moves) plus the OSC-8 hyperlink form qlty uses.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")

# Framing required by F5: qlty's per-run issue cap means a count is never
# provably complete, so output must never claim to show everything.
_RUN_SCOPED_NOTE = "issues visible in this run (qlty caps issues per run; not a completeness signal)"

_CHANGED_EMPTY_NOTE = (
    "0 findings in changed files; run with --all to scan the repo"
)

_ALL_EMPTY_NOTE = "0 findings across all files."


def _empty_note(result: ScanResult) -> str:
    """Empty-result wording, which must state the scope that was scanned.

    A bare "no issues" after a diff-only scan is the F1 failure mode: it reads
    identically to a clean repo.
    """
    return _ALL_EMPTY_NOTE if result.scanned_all else _CHANGED_EMPTY_NOTE


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from qlty output."""
    return _ANSI_RE.sub("", text)


@dataclass(frozen=True)
class TriageEntry:
    """One rule's findings plus the strategy that governs them."""

    strategy: RuleStrategy
    findings: tuple[Finding, ...]
    #: Findings whose module already uses a params object -- i.e. pattern drift
    #: rather than a bare high metric. Only meaningful for function-parameters.
    drift_files: tuple[str, ...] = ()

    @property
    def rule(self) -> str:
        return self.strategy.rule

    @property
    def count(self) -> int:
        return len(self.findings)

    @property
    def proposes_fix(self) -> bool:
        """Whether triage auto-proposes a fix for this rule.

        False for Tier D, which escalates to a human read instead of
        proposing a fix from an untrustworthy metric.
        """
        return self.strategy.actionable


def _fmt_finding(finding: Finding) -> str:
    location = str(finding.location)
    extra = ""
    if finding.other_locations:
        joined = ", ".join(str(loc) for loc in finding.other_locations)
        extra = f"  [also: {joined}]"
    value = f" (value={finding.value})" if finding.value is not None else ""
    return f"{location}{value}  {strip_ansi(finding.message)}{extra}"


def _scan_header(result: ScanResult) -> list[str]:
    scope = "all files" if result.scanned_all else "changed files"
    lines = [f"qlty scan: {result.total} {_RUN_SCOPED_NOTE}", f"scope: {scope}"]

    formats = ", ".join(w.value for w in result.wire_formats) or "none"
    lines.append(f"format: {formats}")

    if result.iterations > 1:
        state = "stable" if result.stable else "UNSTABLE (cap not reached)"
        lines.append(f"rescan: {result.iterations} iterations, {state}")
    if result.duplicates_collapsed:
        lines.append(
            f"deduped: {result.duplicates_collapsed} duplicate reports collapsed "
            "(qlty reports each clone once per location)"
        )
    for degradation in result.degradations:
        lines.append(f"WARNING: {degradation}")
    return lines


def render_scan_text(result: ScanResult) -> str:
    """Human/LLM-readable scan summary."""
    lines = _scan_header(result)

    if not result.findings:
        lines.append("")
        lines.append(_empty_note(result))
        return "\n".join(lines)

    for rule, findings in result.by_rule().items():
        strategy = strategy_for(rule)
        lines.append("")
        lines.append(f"{rule}  ({len(findings)})  tier {strategy.tier.value}")
        for finding in findings:
            lines.append(f"  {_fmt_finding(finding)}")

    return "\n".join(lines)


def _finding_payload(finding: Finding) -> dict:
    return {
        "rule": finding.rule,
        "file": finding.file,
        "line": finding.line,
        "level": finding.level,
        "message": strip_ansi(finding.message),
        "value": finding.value,
        "source": finding.source.value,
        "wire_format": finding.wire_format.value,
        "tool": finding.tool,
        "other_locations": [
            {"file": loc.path, "line": loc.line} for loc in finding.other_locations
        ],
        "group_key": finding.group_key,
    }


def scan_payload(result: ScanResult) -> dict:
    """JSON-serializable form of a scan result."""
    return {
        "total": result.total,
        "note": _RUN_SCOPED_NOTE,
        "scope": "all" if result.scanned_all else "changed",
        "wire_formats": [w.value for w in result.wire_formats],
        "iterations": result.iterations,
        "stable": result.stable,
        "degraded": result.degraded,
        "degradations": list(result.degradations),
        "duplicates_collapsed": result.duplicates_collapsed,
        "counts_by_rule": {
            rule: len(items) for rule, items in result.by_rule().items()
        },
        "findings": [_finding_payload(f) for f in result.findings],
    }


def render_scan_json(result: ScanResult) -> str:
    return json.dumps(scan_payload(result), indent=2, sort_keys=False)


def render_scan_markdown(result: ScanResult) -> str:
    lines = ["# qlty scan", ""]
    lines.extend(f"- {line}" for line in _scan_header(result))
    lines.append("")

    if not result.findings:
        lines.append(_empty_note(result))
        return "\n".join(lines)

    lines.extend(["| rule | tier | count |", "|---|---|---|"])
    for rule, findings in result.by_rule().items():
        lines.append(
            f"| `{rule}` | {strategy_for(rule).tier.value} | {len(findings)} |"
        )
    return "\n".join(lines)


def render_triage_text(entries: Sequence[TriageEntry], result: ScanResult) -> str:
    """Triage grouped by tier, with Tier D marked as requiring a human read."""
    lines = _scan_header(result)
    lines.append("")

    if not entries:
        lines.append(_empty_note(result))
        return "\n".join(lines)

    for tier in (Tier.A, Tier.B, Tier.C, Tier.D, Tier.UNKNOWN, Tier.INFO):
        tier_entries = [e for e in entries if e.strategy.tier is tier]
        if not tier_entries:
            continue
        lines.append(f"== Tier {tier.value}: {_TIER_HEADERS[tier]} ==")
        for entry in tier_entries:
            lines.extend(_render_triage_entry(entry))
        lines.append("")

    return "\n".join(lines).rstrip()


_TIER_HEADERS: dict[Tier, str] = {
    Tier.A: "mechanical, safe to fan out",
    Tier.B: "judgment required, triage before acting",
    Tier.C: "false positive, suppress with a stated reason",
    Tier.D: "READ REQUIRED -- surfaced for a human; no auto-proposed fix",
    Tier.INFO: "informational -- scanner notice, not a defect",
    Tier.UNKNOWN: "no recorded strategy -- read before acting",
}


def _render_triage_entry(entry: TriageEntry) -> list[str]:
    lines = [f"  {entry.rule}  ({entry.count})"]
    lines.append(f"    action: {entry.strategy.action}")
    lines.append(f"    why:    {entry.strategy.rationale}")

    tooling = tooling_for(entry.rule)
    if tooling:
        lines.append(f"    tooling: {tooling}")

    if entry.strategy.needs_human_read:
        lines.append(
            "    read required: no auto-proposed fix; a human must read the "
            "locations above and decide. Real duplication found this way is "
            "still worth fixing."
        )
    elif not entry.proposes_fix and not entry.strategy.reportable_only:
        lines.append("    no fix proposed: read the finding before acting.")

    if entry.drift_files:
        lines.append(
            "    candidates (module already uses a params object -- pattern drift):"
        )
        lines.extend(f"      {path}" for path in entry.drift_files)
        remaining = entry.count - len(entry.drift_files)
        if remaining > 0:
            lines.append(
                f"      ({remaining} other finding(s) show no sibling params "
                "object -- default LEAVE)"
            )
    return lines


def triage_payload(
    entries: Sequence[TriageEntry], result: ScanResult
) -> dict:
    return {
        "note": _RUN_SCOPED_NOTE,
        "scope": "all" if result.scanned_all else "changed",
        "total": result.total,
        "degraded": result.degraded,
        "degradations": list(result.degradations),
        "tiers": [
            {
                "rule": entry.rule,
                "tier": entry.strategy.tier.value,
                "count": entry.count,
                "action": entry.strategy.action,
                "rationale": entry.strategy.rationale,
                "proposes_fix": entry.proposes_fix,
                "needs_human_read": entry.strategy.needs_human_read,
                "informational": entry.strategy.reportable_only,
                "tooling": tooling_for(entry.rule),
                "drift_candidates": list(entry.drift_files),
                "findings": [_finding_payload(f) for f in entry.findings],
            }
            for entry in entries
        ],
    }


def render_triage_json(
    entries: Sequence[TriageEntry], result: ScanResult
) -> str:
    return json.dumps(triage_payload(entries, result), indent=2, sort_keys=False)


def render_triage_markdown(
    entries: Sequence[TriageEntry], result: ScanResult
) -> str:
    lines = ["# qlty triage", ""]
    lines.extend(f"- {line}" for line in _scan_header(result))
    lines.append("")
    lines.extend(["| rule | tier | count | proposes fix |", "|---|---|---|---|"])
    for entry in entries:
        fix = "yes" if entry.proposes_fix else "no (report-only)"
        lines.append(
            f"| `{entry.rule}` | {entry.strategy.tier.value} | {entry.count} | {fix} |"
        )
    return "\n".join(lines)


def render_rules_text(
    strategies: Sequence[RuleStrategy], counts: Optional[dict[str, int]] = None
) -> str:
    """List known rules, their tier, tooling, and optionally live counts."""
    lines = ["known qlty rules (Phase 1 strategy table):", ""]
    for strategy in strategies:
        count = ""
        if counts is not None:
            count = f"  n={counts.get(strategy.rule, 0)}"
        tooling = tooling_for(strategy.rule)
        lines.append(f"{strategy.rule}  tier {strategy.tier.value}{count}")
        lines.append(f"  action:  {strategy.action}")
        lines.append(f"  tooling: {tooling or 'none'}")
        lines.append("")
    return "\n".join(lines).rstrip()


def rules_payload(
    strategies: Sequence[RuleStrategy], counts: Optional[dict[str, int]] = None
) -> dict:
    return {
        "rules": [
            {
                "rule": s.rule,
                "tier": s.tier.value,
                "action": s.action,
                "rationale": s.rationale,
                "tooling": tooling_for(s.rule),
                "proposes_fix": s.actionable,
                "needs_human_read": s.needs_human_read,
                **({"count": counts.get(s.rule, 0)} if counts is not None else {}),
            }
            for s in strategies
        ]
    }


def render_rules_json(
    strategies: Sequence[RuleStrategy], counts: Optional[dict[str, int]] = None
) -> str:
    return json.dumps(rules_payload(strategies, counts), indent=2, sort_keys=False)


def render_rules_markdown(
    strategies: Sequence[RuleStrategy], counts: Optional[dict[str, int]] = None
) -> str:
    header = "| rule | tier | tooling |"
    sep = "|---|---|---|"
    if counts is not None:
        header = "| rule | tier | count | tooling |"
        sep = "|---|---|---|---|"
    lines = ["# qlty rules", "", header, sep]
    for s in strategies:
        tooling = tooling_for(s.rule) or "none"
        if counts is not None:
            lines.append(
                f"| `{s.rule}` | {s.tier.value} | {counts.get(s.rule, 0)} | {tooling} |"
            )
        else:
            lines.append(f"| `{s.rule}` | {s.tier.value} | {tooling} |")
    return "\n".join(lines)
