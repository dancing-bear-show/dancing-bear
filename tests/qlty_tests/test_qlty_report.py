"""Rendering: ANSI stripping, scope-aware empty wording, tier framing."""

from __future__ import annotations

import json
import unittest

from qlty.models import RuleStrategy, Tier
from qlty.report import (
    TriageEntry,
    render_rules_json,
    render_rules_markdown,
    render_rules_text,
    render_scan_json,
    render_scan_markdown,
    render_scan_text,
    render_triage_json,
    render_triage_markdown,
    render_triage_text,
    strip_ansi,
)
from qlty.scanner import ScanResult
from qlty.strategies import known_strategies, strategy_for
from tests.qlty_tests.shared_fixtures import make_finding


def _result(findings=(), **kwargs) -> ScanResult:
    return ScanResult(findings=tuple(findings), **kwargs)


class StripAnsiTests(unittest.TestCase):
    def test_strips_colour_codes(self):
        # qlty emits heavy ANSI even when piped (plan F3).
        self.assertEqual(strip_ansi("\x1b[31merror\x1b[0m"), "error")

    def test_strips_osc8_hyperlinks(self):
        raw = "\x1b]8;;https://example.com\x07link\x1b]8;;\x07"
        self.assertEqual(strip_ansi(raw), "link")

    def test_plain_text_is_unchanged(self):
        self.assertEqual(strip_ansi("plain"), "plain")

    def test_message_is_stripped_in_rendered_output(self):
        finding = make_finding(message="\x1b[1mbold finding\x1b[0m")
        text = render_scan_text(_result([finding]))
        self.assertIn("bold finding", text)
        self.assertNotIn("\x1b", text)

    def test_message_is_stripped_in_json_payload(self):
        finding = make_finding(message="\x1b[1mbold\x1b[0m")
        payload = json.loads(render_scan_json(_result([finding])))
        self.assertEqual(payload["findings"][0]["message"], "bold")


class EmptyResultWordingTests(unittest.TestCase):
    """A bare "no issues" after a diff-only scan is the F1 failure mode."""

    def test_changed_scope_names_the_scope_and_the_fix(self):
        text = render_scan_text(_result([], scanned_all=False))
        self.assertIn("0 findings in changed files", text)
        self.assertIn("--all", text)

    def test_all_scope_says_all_files(self):
        text = render_scan_text(_result([], scanned_all=True))
        self.assertIn("0 findings across all files", text)
        self.assertNotIn("run with --all", text)

    def test_markdown_and_triage_use_the_same_wording(self):
        empty = _result([], scanned_all=False)
        self.assertIn("run with --all", render_scan_markdown(empty))
        self.assertIn("run with --all", render_triage_text([], empty))


class RunScopedFramingTests(unittest.TestCase):
    """Counts are per-run, never a completeness claim (plan F5)."""

    def test_header_disclaims_completeness(self):
        text = render_scan_text(_result([make_finding()]))
        self.assertIn("visible in this run", text)
        self.assertNotIn("all remaining issues", text)

    def test_json_payload_carries_the_note(self):
        payload = json.loads(render_scan_json(_result([make_finding()])))
        self.assertIn("visible in this run", payload["note"])

    def test_unstable_rescan_is_surfaced(self):
        text = render_scan_text(
            _result([make_finding()], iterations=3, stable=False)
        )
        self.assertIn("UNSTABLE", text)

    def test_dedup_count_is_disclosed(self):
        text = render_scan_text(
            _result([make_finding()], duplicates_collapsed=7)
        )
        self.assertIn("7 duplicate reports collapsed", text)

    def test_degradation_is_surfaced_as_a_warning(self):
        text = render_scan_text(
            _result([make_finding()], degradations=("--json gone",))
        )
        self.assertIn("WARNING", text)
        self.assertIn("--json gone", text)


class TriageRenderingTests(unittest.TestCase):
    def _entry(self, rule: str, drift=()) -> TriageEntry:
        return TriageEntry(
            strategy=strategy_for(rule),
            findings=(make_finding(rule=rule),),
            drift_files=tuple(drift),
        )

    def test_tier_d_requires_a_human_read_instead_of_a_proposal(self):
        entry = self._entry("similar-code")
        text = render_triage_text([entry], _result([make_finding()]))
        # No auto-proposed fix...
        self.assertFalse(entry.proposes_fix)
        # ...but it escalates to a person rather than being discarded, so real
        # duplication added later still surfaces as actionable debt.
        self.assertTrue(entry.strategy.needs_human_read)
        self.assertIn("READ REQUIRED", text)
        self.assertIn("still worth fixing", text)

    def test_tier_d_is_not_treated_as_informational(self):
        # "no auto-proposal" must not collapse into "not a real problem".
        self.assertFalse(strategy_for("similar-code").reportable_only)

    def test_return_statements_is_also_report_only(self):
        self.assertFalse(self._entry("return-statements").proposes_fix)

    def test_tier_a_proposes_a_fix(self):
        self.assertTrue(self._entry("boolean-logic").proposes_fix)

    def test_drift_candidates_are_listed(self):
        entry = TriageEntry(
            strategy=strategy_for("function-parameters"),
            findings=tuple(
                make_finding(path=f"src/{i}.py") for i in range(5)
            ),
            drift_files=("src/0.py",),
        )
        text = render_triage_text([entry], _result([make_finding()]))
        self.assertIn("pattern drift", text)
        self.assertIn("src/0.py", text)
        # The remaining findings must be explicitly framed as LEAVE.
        self.assertIn("default LEAVE", text)

    def test_json_exposes_proposes_fix_flag(self):
        entries = [self._entry("similar-code"), self._entry("boolean-logic")]
        payload = json.loads(
            render_triage_json(entries, _result([make_finding()]))
        )
        by_rule = {t["rule"]: t for t in payload["tiers"]}
        self.assertFalse(by_rule["similar-code"]["proposes_fix"])
        self.assertTrue(by_rule["boolean-logic"]["proposes_fix"])

    def test_markdown_marks_report_only(self):
        md = render_triage_markdown(
            [self._entry("similar-code")], _result([make_finding()])
        )
        self.assertIn("report-only", md)

    def test_unknown_rule_still_renders_with_a_posture(self):
        entry = TriageEntry(
            strategy=strategy_for("totally-unknown-rule"),
            findings=(make_finding(rule="totally-unknown-rule"),),
        )
        text = render_triage_text([entry], _result([make_finding()]))
        self.assertIn("totally-unknown-rule", text)
        self.assertIn("read before acting", text)


class RulesRenderingTests(unittest.TestCase):
    def test_text_lists_every_known_rule(self):
        text = render_rules_text(known_strategies())
        for strategy in known_strategies():
            self.assertIn(strategy.rule, text)

    def test_tooling_is_reported_for_file_complexity(self):
        text = render_rules_text(known_strategies())
        self.assertIn("qlty-complexity-sweep.yaml", text)

    def test_counts_are_included_when_supplied(self):
        payload = json.loads(
            render_rules_json(known_strategies(), {"similar-code": 6})
        )
        by_rule = {r["rule"]: r for r in payload["rules"]}
        self.assertEqual(by_rule["similar-code"]["count"], 6)
        self.assertEqual(by_rule["boolean-logic"]["count"], 0)

    def test_counts_omitted_when_not_supplied(self):
        payload = json.loads(render_rules_json(known_strategies()))
        self.assertNotIn("count", payload["rules"][0])

    def test_markdown_renders_a_table(self):
        md = render_rules_markdown(known_strategies())
        self.assertIn("| rule | tier | tooling |", md)

    def test_markdown_with_counts_adds_a_column(self):
        md = render_rules_markdown(known_strategies(), {"similar-code": 6})
        self.assertIn("| rule | tier | count | tooling |", md)


class StrategyTableTests(unittest.TestCase):
    def test_tier_d_rules_are_never_actionable(self):
        for rule in ("return-statements", "similar-code"):
            self.assertIs(strategy_for(rule).tier, Tier.D)
            self.assertFalse(strategy_for(rule).actionable)

    def test_function_parameters_defaults_to_leave(self):
        strategy = strategy_for("function-parameters")
        self.assertIs(strategy.tier, Tier.B)
        self.assertIn("LEAVE", strategy.action)

    def test_unknown_rule_gets_explicit_unknown_tier(self):
        strategy = strategy_for("no-such-rule")
        self.assertIs(strategy.tier, Tier.UNKNOWN)
        self.assertFalse(strategy.actionable)

    def test_scanner_notices_are_informational_not_unknown(self):
        # ripgrep's comment-marker rules are notices, not defects. They must
        # not land in UNKNOWN, which means "the strategy table has a gap".
        strategy = strategy_for("NO" + "TE")
        self.assertIs(strategy.tier, Tier.INFO)
        self.assertTrue(strategy.reportable_only)
        self.assertFalse(strategy.needs_human_read)

    def test_informational_is_distinguishable_from_a_lookup_miss(self):
        self.assertNotEqual(
            strategy_for("NO" + "TE").tier, strategy_for("python:S9999").tier
        )

    def test_only_tier_d_requires_a_human_read(self):
        for rule in ("boolean-logic", "function-parameters", "NO" + "TE"):
            self.assertFalse(
                strategy_for(rule).needs_human_read, msg=rule
            )
        self.assertTrue(strategy_for("return-statements").needs_human_read)

    def test_known_radarlint_false_positives_are_tier_c(self):
        self.assertIs(strategy_for("python:S5655").tier, Tier.C)

    def test_actionable_only_for_tiers_a_and_b(self):
        self.assertTrue(
            RuleStrategy("r", Tier.A, "a", "why").actionable
        )
        self.assertTrue(RuleStrategy("r", Tier.B, "a", "why").actionable)
        self.assertFalse(RuleStrategy("r", Tier.C, "a", "why").actionable)


if __name__ == "__main__":
    unittest.main()
