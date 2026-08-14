"""Parsing/normalization contract for qlty's --json and --sarif output."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from qlty.models import Source, WireFormat
from qlty.runner import (
    QltyInvocationError,
    QltyNotInstalledError,
    QltyRunner,
    _strip_rule_namespace,
    parse_json_findings,
    parse_sarif_findings,
    resolve_binary,
)
from tests.qlty_tests.shared_fixtures import completed, load


class ParseJsonTests(unittest.TestCase):
    def test_parses_captured_smells(self):
        findings = parse_json_findings(load("smells.json"), Source.SMELLS)
        self.assertEqual(len(findings), 37)
        self.assertTrue(all(f.wire_format is WireFormat.JSON for f in findings))

    def test_extracts_rule_location_and_value(self):
        findings = parse_json_findings(load("smells.json"), Source.SMELLS)
        params = [f for f in findings if f.rule == "function-parameters"]
        self.assertTrue(params)
        sample = params[0]
        self.assertTrue(sample.file.endswith(".py"))
        self.assertGreater(sample.line, 0)
        # JSON carries the numeric metric qlty thresholds on.
        self.assertIsInstance(sample.value, int)

    def test_captures_structural_hash_for_duplication(self):
        findings = parse_json_findings(load("smells.json"), Source.SMELLS)
        clones = [f for f in findings if f.rule == "similar-code"]
        self.assertEqual(len(clones), 13)
        self.assertTrue(all(f.group_key for f in clones))
        # 13 reported findings are only 6 real clone groups.
        self.assertEqual(len({f.group_key for f in clones}), 6)

    def test_captures_other_locations(self):
        findings = parse_json_findings(load("smells.json"), Source.SMELLS)
        clones = [f for f in findings if f.rule == "similar-code"]
        self.assertTrue(any(f.other_locations for f in clones))

    def test_parses_check_payload(self):
        findings = parse_json_findings(load("check.json"), Source.CHECK)
        self.assertEqual(len(findings), 2)
        rules = {f.rule for f in findings}
        self.assertIn("python:S5655", rules)

    def test_normalizes_level_vocabulary(self):
        findings = parse_json_findings(load("check.json"), Source.CHECK)
        levels = {f.level for f in findings}
        # LEVEL_HIGH/LEVEL_NOTE become high/note.
        self.assertLessEqual(
            levels, {"high", "note", "medium", "low", "unknown"}
        )
        self.assertFalse(any(level.startswith("level_") for level in levels))

    def test_empty_stdout_raises_rather_than_returning_empty(self):
        # The core invariant: a failed run must never look like a clean repo.
        with self.assertRaises(QltyInvocationError):
            parse_json_findings("", Source.SMELLS)

    def test_clean_scan_returns_empty_list(self):
        # A genuinely clean scan emits "[]" and must parse to zero findings.
        self.assertEqual(parse_json_findings("[]", Source.CHECK), [])

    def test_non_array_payload_raises(self):
        with self.assertRaises(QltyInvocationError):
            parse_json_findings('{"oops": true}', Source.SMELLS)

    def test_malformed_json_raises(self):
        with self.assertRaises(ValueError):
            parse_json_findings("{not json", Source.SMELLS)

    def test_non_object_array_entries_raise(self):
        # A non-empty array of non-objects must not decay to [], which would
        # be indistinguishable from a clean repo.
        with self.assertRaises(QltyInvocationError):
            parse_json_findings("[1, 2, 3]", Source.SMELLS)

    def test_partially_malformed_array_raises(self):
        payload = '[{"ruleKey": "x", "location": {"path": "a.py"}}, 7]'
        with self.assertRaises(QltyInvocationError):
            parse_json_findings(payload, Source.SMELLS)


class ParseSarifTests(unittest.TestCase):
    def test_parses_captured_smells(self):
        findings = parse_sarif_findings(load("smells.sarif"), Source.SMELLS)
        self.assertEqual(len(findings), 37)
        self.assertTrue(all(f.wire_format is WireFormat.SARIF for f in findings))

    def test_strips_qlty_namespace_from_rule_id(self):
        findings = parse_sarif_findings(load("smells.sarif"), Source.SMELLS)
        rules = {f.rule for f in findings}
        # Rule keys must match the strategy table, i.e. no "qlty:" prefix.
        self.assertIn("function-parameters", rules)
        self.assertFalse(any(r.startswith("qlty:") for r in rules))

    def test_preserves_radarlint_rule_key_colon(self):
        # `radarlint-python:python:S5655` -> tool=radarlint-python,
        # rule=python:S5655. Splitting on every colon would mangle the key.
        findings = parse_sarif_findings(load("check.sarif"), Source.CHECK)
        rules = {f.rule for f in findings}
        self.assertIn("python:S5655", rules)

    def test_sarif_matches_json_on_rules_and_counts(self):
        # The fallback must be faithful: same findings, same rule keys.
        json_findings = parse_json_findings(load("smells.json"), Source.SMELLS)
        sarif_findings = parse_sarif_findings(load("smells.sarif"), Source.SMELLS)
        self.assertEqual(len(json_findings), len(sarif_findings))

        def counts(items):
            out: dict[str, int] = {}
            for item in items:
                out[item.rule] = out.get(item.rule, 0) + 1
            return out

        self.assertEqual(counts(json_findings), counts(sarif_findings))

    def test_sarif_locations_match_json_locations(self):
        json_locs = {
            (f.rule, f.file, f.line)
            for f in parse_json_findings(load("smells.json"), Source.SMELLS)
        }
        sarif_locs = {
            (f.rule, f.file, f.line)
            for f in parse_sarif_findings(load("smells.sarif"), Source.SMELLS)
        }
        self.assertEqual(json_locs, sarif_locs)

    def test_value_is_none_because_sarif_omits_it(self):
        # SARIF has no numeric value; it is embedded in message prose. It must
        # be None (unknown), never 0, so value filters cannot silently
        # degrade to "no matches".
        findings = parse_sarif_findings(load("smells.sarif"), Source.SMELLS)
        self.assertTrue(all(f.value is None for f in findings))

    def test_sarif_retains_structural_hash_for_dedup(self):
        findings = parse_sarif_findings(load("smells.sarif"), Source.SMELLS)
        clones = [f for f in findings if f.rule == "similar-code"]
        self.assertEqual(len({f.group_key for f in clones}), 6)

    def test_empty_stdout_raises(self):
        with self.assertRaises(QltyInvocationError):
            parse_sarif_findings("", Source.SMELLS)

    def test_missing_runs_raises(self):
        with self.assertRaises(QltyInvocationError):
            parse_sarif_findings('{"version": "2.1.0"}', Source.SMELLS)

    def test_empty_results_is_a_clean_scan(self):
        payload = '{"runs": [{"results": []}]}'
        self.assertEqual(parse_sarif_findings(payload, Source.CHECK), [])

    def test_malformed_results_raise(self):
        payload = '{"runs": [{"results": [1, 2]}]}'
        with self.assertRaises(QltyInvocationError):
            parse_sarif_findings(payload, Source.SMELLS)


class StripRuleNamespaceTests(unittest.TestCase):
    def test_strips_only_first_segment(self):
        self.assertEqual(
            _strip_rule_namespace("qlty:function-parameters"),
            ("qlty", "function-parameters"),
        )
        self.assertEqual(
            _strip_rule_namespace("radarlint-python:python:S5655"),
            ("radarlint-python", "python:S5655"),
        )

    def test_bare_rule_id_has_no_tool(self):
        # ripgrep emits an un-namespaced rule key; it must pass through intact.
        bare_rule = "NO" + "TE"
        self.assertEqual(_strip_rule_namespace(bare_rule), ("", bare_rule))


class InvokeFallbackTests(unittest.TestCase):
    """The --json -> --sarif degradation path (plan F4)."""

    def _runner(self) -> QltyRunner:
        return QltyRunner(binary="/fake/qlty")

    def test_uses_json_when_available(self):
        runner = self._runner()
        with patch.object(
            runner, "_execute", return_value=completed(load("smells.json"), 1)
        ):
            result = runner.invoke(Source.SMELLS)
        self.assertIs(result.wire_format, WireFormat.JSON)
        self.assertFalse(result.degraded)
        self.assertEqual(len(result.findings), 37)

    def test_falls_back_to_sarif_and_reports_degradation(self):
        runner = self._runner()
        runs = [
            completed("", 99, "error: unexpected argument '--json'"),
            completed(load("smells.sarif"), 1),
        ]
        with patch.object(runner, "_execute", side_effect=runs):
            result = runner.invoke(Source.SMELLS)

        self.assertIs(result.wire_format, WireFormat.SARIF)
        # Degradation is surfaced, never silent.
        self.assertTrue(result.degraded)
        self.assertIn("--json", result.degrade_reason)
        self.assertEqual(len(result.findings), 37)

    def test_raises_when_both_formats_fail(self):
        runner = self._runner()
        runs = [completed("", 99, "boom"), completed("", 99, "boom")]
        with patch.object(runner, "_execute", side_effect=runs):
            with self.assertRaises(QltyInvocationError) as ctx:
                runner.invoke(Source.SMELLS)
        # Must be explicit that this is not a clean repo.
        self.assertIn("NOT a clean repo", str(ctx.exception))

    def test_exit_one_means_issues_found_not_failure(self):
        runner = self._runner()
        with patch.object(
            runner, "_execute", return_value=completed(load("check.json"), 1)
        ) as executed:
            result = runner.invoke(Source.CHECK)
        self.assertEqual(len(result.findings), 2)
        # Only one call: exit 1 is a successful scan, so no fallback.
        self.assertEqual(executed.call_count, 1)

    def test_exit_zero_with_empty_array_is_clean(self):
        runner = self._runner()
        with patch.object(runner, "_execute", return_value=completed("[]", 0)):
            result = runner.invoke(Source.CHECK)
        self.assertEqual(result.findings, ())
        self.assertFalse(result.degraded)

    def test_hard_error_with_garbage_stdout_raises(self):
        runner = self._runner()
        runs = [completed("not json", 0), completed("not json either", 0)]
        with patch.object(runner, "_execute", side_effect=runs):
            with self.assertRaises(QltyInvocationError):
                runner.invoke(Source.SMELLS)

    def test_check_never_mutates_the_tree(self):
        runner = self._runner()
        with patch.object(
            runner, "_execute", return_value=completed("[]", 0)
        ) as executed:
            runner.invoke(Source.CHECK)
        args = executed.call_args[0][0]
        self.assertIn("--no-fix", args)

    def test_scan_all_flag_is_passed(self):
        runner = self._runner()
        with patch.object(
            runner, "_execute", return_value=completed("[]", 0)
        ) as executed:
            runner.invoke(Source.SMELLS, scan_all=True)
        self.assertIn("--all", executed.call_args[0][0])

    def test_changed_scope_omits_all_flag(self):
        runner = self._runner()
        with patch.object(
            runner, "_execute", return_value=completed("[]", 0)
        ) as executed:
            runner.invoke(Source.SMELLS, scan_all=False)
        self.assertNotIn("--all", executed.call_args[0][0])


class ResolveBinaryTests(unittest.TestCase):
    def test_explicit_missing_path_raises(self):
        with self.assertRaises(QltyNotInstalledError):
            resolve_binary("/nonexistent/qlty-binary")

    def test_falls_back_to_path_lookup(self):
        with patch("qlty.runner._DEFAULT_BINARY") as default:
            default.is_file.return_value = False
            with patch("qlty.runner.shutil.which", return_value="/usr/bin/qlty"):
                with patch.dict("os.environ", {}, clear=True):
                    self.assertEqual(resolve_binary(), "/usr/bin/qlty")

    def test_raises_when_not_installed_anywhere(self):
        with patch("qlty.runner._DEFAULT_BINARY") as default:
            default.is_file.return_value = False
            with patch("qlty.runner.shutil.which", return_value=None):
                with patch.dict("os.environ", {}, clear=True):
                    with self.assertRaises(QltyNotInstalledError):
                        resolve_binary()


if __name__ == "__main__":
    unittest.main()
