"""Rendering: ANSI stripping, scope-aware empty wording, tier framing."""

from __future__ import annotations

import csv
import io
import json
import unittest

from qlty.models import Location, RuleStrategy, Scope, Tier
from qlty.report import (
    TriageEntry,
    render_rules_csv,
    render_rules_json,
    render_rules_markdown,
    render_rules_text,
    render_scan_csv,
    render_scan_json,
    render_scan_markdown,
    render_scan_text,
    render_triage_csv,
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
        text = render_scan_text(_result([], scope=Scope.CHANGED))
        self.assertIn("0 findings in changed files", text)
        self.assertIn("--all", text)

    def test_all_scope_says_all_files(self):
        text = render_scan_text(_result([], scope=Scope.ALL))
        self.assertIn("0 findings across all files", text)
        self.assertNotIn("run with --all", text)

    def test_markdown_and_triage_use_the_same_wording(self):
        empty = _result([], scope=Scope.CHANGED)
        self.assertIn("run with --all", render_scan_markdown(empty))
        self.assertIn("run with --all", render_triage_text([], empty))


class PathsScopeEmptyWordingTests(unittest.TestCase):
    """A path-scoped empty result must not claim the whole repo is clean.

    Naming paths makes qlty drop --all, so the scan covered neither the repo
    nor the diff. Reporting it as either is the same false clean as F1.
    """

    def test_paths_scope_names_the_scope_and_the_fix(self):
        text = render_scan_text(_result([], scope=Scope.PATHS))
        self.assertIn("0 findings in the requested paths", text)
        self.assertIn("run without paths", text)

    def test_paths_scope_does_not_claim_all_files(self):
        text = render_scan_text(_result([], scope=Scope.PATHS))
        self.assertNotIn("across all files", text)
        self.assertIn("scope: the requested paths", text)

    def test_paths_scope_json_payload_says_paths(self):
        payload = json.loads(render_scan_json(_result([], scope=Scope.PATHS)))
        self.assertEqual(payload["scope"], "paths")

    def test_all_scope_json_payload_says_all(self):
        payload = json.loads(render_scan_json(_result([], scope=Scope.ALL)))
        self.assertEqual(payload["scope"], "all")

    def test_changed_scope_json_payload_says_changed(self):
        payload = json.loads(render_scan_json(_result([], scope=Scope.CHANGED)))
        self.assertEqual(payload["scope"], "changed")

    def test_every_scope_renders_a_distinct_empty_note(self):
        # A missing dict entry would KeyError; a shared one would re-create the
        # two-valued bug this replaced.
        notes = {
            render_scan_text(_result([], scope=scope)) for scope in Scope
        }
        self.assertEqual(len(notes), len(Scope))

    def test_triage_payload_carries_the_scope(self):
        payload = json.loads(
            render_triage_json([], _result([], scope=Scope.PATHS))
        )
        self.assertEqual(payload["scope"], "paths")


class FindingFormattingTests(unittest.TestCase):
    def test_clone_siblings_are_listed_alongside_the_primary(self):
        # similar-code collapses N locations into one finding. The collapsed
        # siblings must still be printed, or dedup would hide where the
        # duplicate code actually lives.
        finding = make_finding(
            rule="similar-code",
            path="src/a.py",
            group_key="h",
            value=None,
            other_locations=(Location(path="src/b.py", line=20),),
        )
        text = render_scan_text(_result([finding]))
        self.assertIn("src/a.py", text)
        self.assertIn("also:", text)
        self.assertIn("src/b.py:20", text)

    def test_absent_value_is_omitted_rather_than_shown_as_zero(self):
        # SARIF carries no numeric value; rendering "value=0" would look like a
        # real measurement of zero.
        text = render_scan_text(_result([make_finding(value=None)]))
        self.assertNotIn("value=", text)


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

    def test_all_drift_candidates_omits_the_remainder_note(self):
        # Complement of test_drift_candidates_are_listed: when every finding is
        # a drift candidate there is no "default LEAVE" remainder to report,
        # and claiming one would be wrong.
        entry = TriageEntry(
            strategy=strategy_for("function-parameters"),
            findings=(make_finding(path="src/0.py"),),
            drift_files=("src/0.py",),
        )
        text = render_triage_text([entry], _result([make_finding()]))
        self.assertIn("pattern drift", text)
        self.assertNotIn("default LEAVE", text)

    def test_tooling_is_named_when_a_workflow_exists(self):
        # A rule with a real remediation workflow must say so; the whole point
        # of the tier table is routing to the tool that fixes it.
        text = render_triage_text(
            [self._entry("file-complexity")], _result([make_finding()])
        )
        self.assertIn("tooling:", text)
        self.assertIn("qlty-complexity-sweep", text)

    def test_json_exposes_proposes_fix_flag(self):
        entries = [self._entry("similar-code"), self._entry("boolean-logic")]
        payload = json.loads(
            render_triage_json(entries, _result([make_finding()]))
        )
        by_rule = {t["rule"]: t for t in payload["tiers"]}
        self.assertFalse(by_rule["similar-code"]["proposes_fix"])
        self.assertTrue(by_rule["boolean-logic"]["proposes_fix"])

    def test_markdown_names_why_no_fix_is_proposed(self):
        # "no fix" is not one posture. Tier D needs a human to read the
        # locations; Tier C wants a suppression with a stated reason. Rendering
        # both as a bare "report-only" would tell the reader to do nothing.
        md = render_triage_markdown(
            [self._entry("similar-code")], _result([make_finding()])
        )
        self.assertIn("| `similar-code` | D |", md)
        self.assertIn("no (read required)", md)

    def test_markdown_distinguishes_the_no_fix_postures(self):
        entries = [
            self._entry("similar-code"),  # Tier D
            TriageEntry(
                strategy=strategy_for("totally-unknown-rule"),
                findings=(make_finding(rule="totally-unknown-rule"),),
            ),
        ]
        md = render_triage_markdown(entries, _result([make_finding()]))
        self.assertIn("no (read required)", md)
        self.assertIn("no (manual review)", md)

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

    def test_text_annotates_rules_with_live_counts(self):
        text = render_rules_text(known_strategies(), {"similar-code": 6})
        self.assertIn("n=6", text)
        # A rule absent from the scan is an explicit zero, not a blank, so
        # "not found" is distinguishable from "not reported".
        self.assertIn("n=0", text)

    def test_text_omits_counts_when_no_scan_ran(self):
        # Without --counts no scan happened; printing n=0 everywhere would
        # falsely claim a clean repo.
        self.assertNotIn("n=", render_rules_text(known_strategies()))


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


class CsvRenderingTests(unittest.TestCase):
    """CSV is a real format, not a flag that silently falls back to text."""

    def test_scan_csv_is_one_row_per_finding(self):
        findings = [make_finding(rule="a"), make_finding(rule="b")]
        rows = list(csv.reader(io.StringIO(render_scan_csv(_result(findings)))))
        self.assertEqual(rows[0][0], "rule")
        self.assertEqual(len(rows), 3)  # header + 2 findings

    def test_scan_csv_differs_from_text(self):
        # A dead --format choice would render identically to the default.
        result = _result([make_finding(rule="a")])
        self.assertNotEqual(render_scan_csv(result), render_scan_text(result))

    def test_scan_csv_strips_ansi_from_messages(self):
        finding = make_finding(rule="a", message="\x1b[31mred\x1b[0m")
        self.assertNotIn("\x1b", render_scan_csv(_result([finding])))

    def test_scan_csv_quotes_embedded_commas(self):
        finding = make_finding(rule="a", message="one, two, three")
        rows = list(csv.reader(io.StringIO(render_scan_csv(_result([finding])))))
        self.assertEqual(rows[1][-1], "one, two, three")

    def test_scan_csv_absent_value_is_blank_not_zero(self):
        # 0 would read as "below every threshold"; unknown must stay empty.
        finding = make_finding(rule="a", value=None)
        rows = list(csv.reader(io.StringIO(render_scan_csv(_result([finding])))))
        self.assertEqual(rows[1][rows[0].index("value")], "")

    def test_scan_csv_header_only_when_no_findings(self):
        rows = list(csv.reader(io.StringIO(render_scan_csv(_result([])))))
        self.assertEqual(len(rows), 1)

    def test_rules_csv_lists_every_known_rule(self):
        strategies = known_strategies()
        rows = list(csv.reader(io.StringIO(render_rules_csv(strategies))))
        self.assertEqual(len(rows), len(strategies) + 1)

    def test_rules_csv_counts_blank_without_a_scan(self):
        rows = list(csv.reader(io.StringIO(render_rules_csv(known_strategies()))))
        self.assertTrue(all(row[2] == "" for row in rows[1:]))

    def test_rules_csv_includes_counts_when_supplied(self):
        strategies = known_strategies()
        text = render_rules_csv(strategies, {strategies[0].rule: 7})
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[1][2], "7")

    def test_triage_csv_is_one_row_per_rule(self):
        entry = TriageEntry(
            strategy=strategy_for("similar-code"),
            findings=(make_finding(rule="similar-code"),),
        )
        rows = list(
            csv.reader(io.StringIO(render_triage_csv([entry], _result())))
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], "similar-code")

    def test_triage_csv_reports_no_fix_for_report_only_tiers(self):
        entry = TriageEntry(
            strategy=strategy_for("similar-code"),
            findings=(make_finding(rule="similar-code"),),
        )
        rows = list(
            csv.reader(io.StringIO(render_triage_csv([entry], _result())))
        )
        self.assertEqual(rows[1][rows[0].index("proposes_fix")], "no")


class NonActionableTierLabelTests(unittest.TestCase):
    """Each non-actionable tier says why it proposes no fix.

    "report-only" is true for D but wrong for C (suppress with a stated
    reason) and UNKNOWN (classify the rule first).
    """

    @staticmethod
    def _markdown_for(tier: Tier) -> str:
        entry = TriageEntry(
            strategy=RuleStrategy("r", tier, "action", "why"),
            findings=(make_finding(rule="r"),),
        )
        return render_triage_markdown([entry], _result([make_finding(rule="r")]))

    def test_tier_c_reads_as_suppress_with_reason(self):
        self.assertIn("suppress with reason", self._markdown_for(Tier.C))

    def test_tier_d_reads_as_read_required(self):
        self.assertIn("read required", self._markdown_for(Tier.D))

    def test_unknown_tier_reads_as_manual_review(self):
        self.assertIn("manual review", self._markdown_for(Tier.UNKNOWN))

    def test_non_actionable_tiers_do_not_share_one_label(self):
        # A blanket label would make these three indistinguishable.
        rows = {
            next(
                line
                for line in self._markdown_for(t).splitlines()
                if line.startswith("| `r`")
            )
            for t in (Tier.C, Tier.D, Tier.UNKNOWN)
        }
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
