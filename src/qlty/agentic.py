from __future__ import annotations


def build_agentic_capsule() -> str:
    lines: list[str] = []
    lines.append("agentic: qlty")
    lines.append(
        "purpose: Merged qlty check+smells scanning with per-rule triage strategy"
    )
    lines.append("commands:")
    lines.append("  - full scan: ./bin/qlty-assistant scan")
    lines.append("  - JSON scan: ./bin/qlty-assistant scan --format json")
    lines.append("  - triage by tier: ./bin/qlty-assistant triage")
    lines.append("  - rule table: ./bin/qlty-assistant rules")
    lines.append("notes:")
    lines.append("  - scan defaults to --all; --changed is opt-in (diff-only under-reports)")
    lines.append("  - scan merges `qlty check` and `qlty smells`; neither is a superset")
    lines.append("  - counts are per-run only; qlty caps issues, so totals are not completeness")
    lines.append("  - cap is nondeterministic: one clean run is NOT evidence of a clean repo")
    lines.append("  - use --rescan-until-stable; a dry streak of 2 runs required before stable=True")
    lines.append("  - do NOT use --filter to verify a finding is gone; --filter is unreliable")
    lines.append("  - tier D rules (return-statements, similar-code) are report-only")
    lines.append("  - --expect-min N exits nonzero on an implausibly small scan")
    return "\n".join(lines)


def build_domain_map() -> str:
    return (
        "Top-Level\n"
        "- bin/qlty-assistant — CLI wrapper (never bin/qlty; would shadow the real binary)\n"
        "- qlty/cli.py — argparse entry\n"
        "- qlty/runner.py — qlty subprocess choke point; --json with --sarif fallback\n"
        "- qlty/scanner.py — merge check+smells, dedupe, rescan-until-stable\n"
        "- qlty/strategies.py — rule → tier/action table\n"
        "- qlty/report.py — text/json/markdown renderers (ANSI stripped)\n"
        "- qlty/models.py — Finding, Location, Tier, RuleStrategy"
    )


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
