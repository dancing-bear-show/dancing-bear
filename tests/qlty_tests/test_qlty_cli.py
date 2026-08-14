"""CLI wiring: exit codes, scan scope defaults, and the worktree guard."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from typing import Protocol
from unittest.mock import patch

from qlty import cli
from qlty.models import Source
from qlty.runner import InvocationResult, QltyInvocationError
from qlty.scanner import Scanner
from tests.qlty_tests.shared_fixtures import FakeRunner, make_finding, result_of


def run_cli(argv: list[str]) -> tuple[int, str]:
    """Invoke the CLI, capturing stdout only.

    Errors go to stderr so that --format json stdout stays parseable, so
    stdout alone is what a downstream consumer would pipe into jq.
    """
    code, out, _ = run_cli_streams(argv)
    return code, out


def run_cli_streams(argv: list[str]) -> tuple[int, str, str]:
    """Invoke the CLI, capturing stdout and stderr separately."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class _RunnerLike(Protocol):
    """Structural type for anything Scanner can drive.

    Annotated as a Protocol rather than FakeRunner because tests also pass
    one-off doubles (e.g. a runner that always raises).
    """

    def invoke(self, source: Source, **kwargs: object) -> InvocationResult:
        raise NotImplementedError  # pragma: no cover - structural protocol


def _patched_scanner(runner: _RunnerLike):
    """Patch the CLI to use a Scanner backed by a fake runner."""
    return patch.object(cli, "_build_scanner", lambda: Scanner(runner))


class ScanCommandTests(unittest.TestCase):
    def test_scan_succeeds_and_lists_findings(self):
        runner = FakeRunner({Source.SMELLS: [result_of([make_finding()])]})
        with _patched_scanner(runner):
            code, out = run_cli(["scan", "--smells-only"])
        self.assertEqual(code, 0)
        self.assertIn("function-parameters", out)

    def test_scan_defaults_to_all_files(self):
        # F1: diff-only is opt-in; the default must scan the whole repo.
        runner = FakeRunner()
        with _patched_scanner(runner):
            run_cli(["scan"])
        self.assertTrue(all(call[1] for call in runner.calls))

    def test_scan_runs_both_sources_by_default(self):
        runner = FakeRunner()
        with _patched_scanner(runner):
            run_cli(["scan"])
        self.assertEqual(
            {call[0] for call in runner.calls}, {Source.CHECK, Source.SMELLS}
        )

    def test_changed_flag_opts_into_diff_only(self):
        runner = FakeRunner()
        with _patched_scanner(runner):
            run_cli(["scan", "--changed"])
        self.assertTrue(all(call[1] is False for call in runner.calls))

    def test_scan_defaults_to_including_tests(self):
        # The silent-empty-scan trap: `qlty smells` excludes test_patterns
        # unless told otherwise, so the default here must be "included".
        runner = FakeRunner()
        with _patched_scanner(runner):
            run_cli(["scan"])
        self.assertTrue(all(call[3] for call in runner.calls))

    def test_no_include_tests_flag_excludes_tests(self):
        runner = FakeRunner()
        with _patched_scanner(runner):
            run_cli(["scan", "--no-include-tests"])
        self.assertTrue(all(call[3] is False for call in runner.calls))

    def test_changed_empty_result_explains_the_scope(self):
        runner = FakeRunner()
        with _patched_scanner(runner):
            code, out = run_cli(["scan", "--changed"])
        self.assertEqual(code, 0)
        self.assertIn("0 findings in changed files", out)
        self.assertIn("--all", out)

    def test_json_format_is_machine_readable(self):
        runner = FakeRunner({Source.SMELLS: [result_of([make_finding()])]})
        with _patched_scanner(runner):
            _, out = run_cli(["scan", "--smells-only", "--format", "json"])
        payload = json.loads(out)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["scope"], "all")

    def test_markdown_format_renders(self):
        runner = FakeRunner({Source.SMELLS: [result_of([make_finding()])]})
        with _patched_scanner(runner):
            _, out = run_cli(["scan", "--smells-only", "--format", "md"])
        self.assertIn("# qlty scan", out)

    def test_paths_are_forwarded(self):
        runner = FakeRunner()
        with _patched_scanner(runner):
            run_cli(["scan", "src/core"])
        self.assertEqual(runner.calls[0][2], ("src/core",))

    def test_runner_failure_exits_nonzero(self):
        # A failed scan must never be reported as a clean repo.
        class Failing:
            def invoke(self, *a, **kw):
                raise QltyInvocationError("qlty exploded")

        with _patched_scanner(Failing()):
            code, out, err = run_cli_streams(["scan"])
        self.assertNotEqual(code, 0)
        # Errors belong on stderr, never mixed into the data stream.
        self.assertIn("qlty exploded", err)
        self.assertNotIn("qlty exploded", out)


class ExpectMinGuardTests(unittest.TestCase):
    """Guards the **/.claude/** exclusion trap (isolated worktrees scan empty)."""

    def test_fails_when_findings_are_implausibly_few(self):
        runner = FakeRunner()
        with _patched_scanner(runner):
            code, _, err = run_cli_streams(["scan", "--expect-min", "10"])
        self.assertNotEqual(code, 0)
        self.assertIn("expected at least 10", err)
        self.assertIn("broken environment", err)

    def test_json_output_stays_parseable_when_the_guard_trips(self):
        # The guard message must not be appended to the JSON payload on
        # stdout, or every downstream `| jq` breaks.
        runner = FakeRunner({Source.SMELLS: [result_of([make_finding()])]})
        with _patched_scanner(runner):
            code, out, err = run_cli_streams(
                ["scan", "--smells-only", "--format", "json", "--expect-min", "99"]
            )
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(out)["total"], 1)
        self.assertIn("expected at least 99", err)

    def test_passes_when_threshold_is_met(self):
        runner = FakeRunner({Source.SMELLS: [result_of([make_finding()])]})
        with _patched_scanner(runner):
            code, _ = run_cli(["scan", "--smells-only", "--expect-min", "1"])
        self.assertEqual(code, 0)

    def test_guard_is_inactive_when_not_requested(self):
        runner = FakeRunner()
        with _patched_scanner(runner):
            code, _ = run_cli(["scan"])
        self.assertEqual(code, 0)

    def test_guard_also_applies_to_triage(self):
        runner = FakeRunner()
        with _patched_scanner(runner):
            code, _, err = run_cli_streams(["triage", "--expect-min", "5"])
        self.assertNotEqual(code, 0)
        self.assertIn("expected at least 5", err)


class TriageCommandTests(unittest.TestCase):
    def test_triage_groups_by_tier(self):
        findings = [
            make_finding(rule="boolean-logic", path="src/a.py"),
            make_finding(rule="similar-code", path="src/b.py", group_key="h"),
        ]
        runner = FakeRunner({Source.SMELLS: [result_of(findings)]})
        with _patched_scanner(runner):
            code, out = run_cli(["triage", "--smells-only"])
        self.assertEqual(code, 0)
        self.assertIn("Tier A", out)
        self.assertIn("Tier D", out)

    def test_tier_d_never_proposes_a_fix(self):
        findings = [make_finding(rule="return-statements", path="src/a.py")]
        runner = FakeRunner({Source.SMELLS: [result_of(findings)]})
        with _patched_scanner(runner):
            _, out = run_cli(["triage", "--smells-only", "--format", "json"])
        payload = json.loads(out)
        entry = payload["tiers"][0]
        self.assertEqual(entry["tier"], "D")
        self.assertFalse(entry["proposes_fix"])

    def test_triage_output_never_claims_completeness(self):
        runner = FakeRunner({Source.SMELLS: [result_of([make_finding()])]})
        with _patched_scanner(runner):
            _, out = run_cli(["triage", "--smells-only"])
        self.assertIn("visible in this run", out)
        self.assertNotIn("all remaining issues", out)

    def test_params_drift_cross_reference_runs_for_tier_b(self):
        findings = [make_finding(rule="function-parameters", path="src/x.py")]
        runner = FakeRunner({Source.SMELLS: [result_of(findings)]})
        with patch.object(cli, "sibling_uses_params_object", return_value=True):
            with _patched_scanner(runner):
                _, out = run_cli(
                    ["triage", "--smells-only", "--format", "json"]
                )
        payload = json.loads(out)
        self.assertEqual(payload["tiers"][0]["drift_candidates"], ["src/x.py"])

    def test_triage_markdown_format_renders(self):
        runner = FakeRunner({Source.SMELLS: [result_of([make_finding()])]})
        with _patched_scanner(runner):
            code, out = run_cli(["triage", "--smells-only", "--format", "md"])
        self.assertEqual(code, 0)
        self.assertIn("#", out)
        self.assertIn("function-parameters", out)

    def test_drift_cross_reference_skips_duplicate_and_empty_paths(self):
        # _drift_candidates dedupes by file: the sibling-module read is the
        # expensive part, so the same module must not be probed twice.
        findings = [
            make_finding(rule="function-parameters", path="src/x.py", line=1),
            make_finding(rule="function-parameters", path="src/x.py", line=2),
            make_finding(rule="function-parameters", path="", line=3),
        ]
        runner = FakeRunner({Source.SMELLS: [result_of(findings)]})
        with patch.object(
            cli, "sibling_uses_params_object", return_value=True
        ) as probe:
            with _patched_scanner(runner):
                _, out = run_cli(["triage", "--smells-only", "--format", "json"])

        payload = json.loads(out)
        self.assertEqual(payload["tiers"][0]["drift_candidates"], ["src/x.py"])
        # Probed once for src/x.py; never for the empty path.
        probe.assert_called_once_with("src/x.py")

    def test_no_drift_candidates_when_module_lacks_params_object(self):
        findings = [make_finding(rule="function-parameters", path="src/x.py")]
        runner = FakeRunner({Source.SMELLS: [result_of(findings)]})
        with patch.object(cli, "sibling_uses_params_object", return_value=False):
            with _patched_scanner(runner):
                _, out = run_cli(
                    ["triage", "--smells-only", "--format", "json"]
                )
        payload = json.loads(out)
        self.assertEqual(payload["tiers"][0]["drift_candidates"], [])


class RulesCommandTests(unittest.TestCase):
    def test_rules_lists_the_table(self):
        code, out = run_cli(["rules"])
        self.assertEqual(code, 0)
        self.assertIn("function-parameters", out)
        self.assertIn("similar-code", out)

    def test_rules_json_is_parseable(self):
        code, out = run_cli(["rules", "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["rules"])

    def test_rules_does_not_scan_without_counts(self):
        runner = FakeRunner()
        with _patched_scanner(runner):
            run_cli(["rules"])
        self.assertEqual(runner.calls, [])

    def test_rules_counts_triggers_a_scan(self):
        findings = [make_finding(rule="boolean-logic")]
        runner = FakeRunner({Source.SMELLS: [result_of(findings)]})
        with _patched_scanner(runner):
            code, out = run_cli(["rules", "--counts", "--format", "json"])
        self.assertEqual(code, 0)
        by_rule = {r["rule"]: r for r in json.loads(out)["rules"]}
        self.assertEqual(by_rule["boolean-logic"]["count"], 1)

    def test_rules_markdown_format_renders(self):
        code, out = run_cli(["rules", "--format", "md"])
        self.assertEqual(code, 0)
        self.assertIn("#", out)
        self.assertIn("function-parameters", out)

    def test_check_only_runs_just_the_check_source(self):
        # The mirror of the existing --smells-only test; together they pin that
        # each flag narrows to exactly one source rather than silently keeping
        # both.
        runner = FakeRunner()
        with _patched_scanner(runner):
            run_cli(["scan", "--check-only"])
        self.assertEqual({call[0] for call in runner.calls}, {Source.CHECK})

    def test_rules_counts_scan_failure_exits_nonzero(self):
        # --counts is the only path where `rules` shells out, so a broken scan
        # must fail loudly rather than printing the table with silent zeros.
        class Failing:
            def invoke(self, *a, **kw):
                raise QltyInvocationError("qlty exploded")

        with _patched_scanner(Failing()):
            code, out, err = run_cli_streams(["rules", "--counts"])

        self.assertNotEqual(code, 0)
        self.assertIn("qlty exploded", err)
        # No partial table on stdout: a rule list with no counts would read as
        # "scanned, found nothing".
        self.assertNotIn("qlty exploded", out)
        self.assertNotIn("function-parameters", out)

    def test_rules_counts_failure_reports_the_hint(self):
        # QltyError is a CLIError, so the framework renders its remedy too.
        class Failing:
            def invoke(self, *a, **kw):
                raise QltyInvocationError("qlty exploded", hint="try --changed")

        with _patched_scanner(Failing()):
            _, _, err = run_cli_streams(["rules", "--counts"])
        self.assertIn("try --changed", err)


class AgenticTests(unittest.TestCase):
    def test_agentic_capsule_emits(self):
        code, out = run_cli(["--agentic"])
        self.assertEqual(code, 0)
        self.assertIn("agentic: qlty", out)

    def test_agentic_json_schema_emits(self):
        code, out = run_cli(["--agentic", "--agentic-format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload)

    def test_capsule_documents_the_scan_default(self):
        _, out = run_cli(["--agentic"])
        self.assertIn("--all", out)

    def test_no_command_prints_help(self):
        code, out = run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("scan", out)


class MetaTests(unittest.TestCase):
    def test_bin_name_does_not_shadow_the_real_binary(self):
        from qlty.meta import META

        self.assertEqual(META.bin_name, "./bin/qlty-assistant")
        self.assertNotEqual(META.bin_name, "./bin/qlty")


if __name__ == "__main__":
    unittest.main()
