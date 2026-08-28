"""Merge, dedup, rescan-until-stable, and the params-object cross-reference."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from qlty.models import Scope, Source, WireFormat
from qlty.runner import parse_json_findings
from qlty.scanner import ScanRequest, Scanner, sibling_uses_params_object
from tests.qlty_tests.shared_fixtures import (
    FakeRunner,
    load,
    make_finding,
    result_of,
)


class MergeTests(unittest.TestCase):
    def test_merges_check_and_smells(self):
        # Neither subcommand is a superset of the other, so both must run.
        check = parse_json_findings(load("check.json"), Source.CHECK)
        smells = parse_json_findings(load("smells.json"), Source.SMELLS)
        runner = FakeRunner(
            {
                Source.CHECK: [result_of(check, source=Source.CHECK)],
                Source.SMELLS: [result_of(smells, source=Source.SMELLS)],
            }
        )
        result = Scanner(runner).scan()

        sources = {f.source for f in result.findings}
        self.assertEqual(sources, {Source.CHECK, Source.SMELLS})
        self.assertEqual({c[0] for c in runner.calls}, {Source.CHECK, Source.SMELLS})

    def test_defaults_to_scanning_all_files(self):
        runner = FakeRunner()
        Scanner(runner).scan()
        self.assertTrue(all(call[1] for call in runner.calls))

    def test_changed_scope_is_propagated(self):
        runner = FakeRunner()
        Scanner(runner).scan(ScanRequest(scan_all=False))
        self.assertTrue(all(call[1] is False for call in runner.calls))

    def test_include_tests_defaults_to_true(self):
        self.assertTrue(ScanRequest().include_tests)

    def test_include_tests_is_propagated(self):
        runner = FakeRunner()
        Scanner(runner).scan(ScanRequest(include_tests=False))
        self.assertTrue(all(call[3] is False for call in runner.calls))

    def test_path_scan_includes_tests(self):
        """A path-scoped scan keeps --include-tests: it is what stops a scan of
        a test file from analysing zero files and reporting a false clean."""
        self.assertTrue(
            ScanRequest(paths=("tests/foo_test.py",)).effective_include_tests
        )

    def test_repo_wide_scan_excludes_tests_by_default(self):
        """A repo-wide scan drops it: with hundreds of files analysed there is no
        false-clean hazard, and the flag would only override qlty.toml's
        test_patterns and surface fixture smells CI never reports."""
        self.assertFalse(ScanRequest().effective_include_tests)

    def test_repo_wide_scan_honours_explicit_force(self):
        self.assertTrue(ScanRequest(force_include_tests=True).effective_include_tests)

    def test_no_include_tests_beats_force(self):
        """Belt-and-braces at the API level: the CLI rejects this combination as a
        UsageError, but ScanRequest is constructible directly, so the opt-out
        still wins rather than silently including tests."""
        self.assertFalse(
            ScanRequest(
                include_tests=False, force_include_tests=True
            ).effective_include_tests
        )

    def test_no_include_tests_beats_path_scope(self):
        self.assertFalse(
            ScanRequest(
                include_tests=False, paths=("tests/foo_test.py",)
            ).effective_include_tests
        )

    def test_repo_wide_scan_does_not_pass_include_tests_to_runner(self):
        runner = FakeRunner()
        Scanner(runner).scan(ScanRequest())
        self.assertTrue(all(call[3] is False for call in runner.calls))

    def test_path_scan_does_pass_include_tests_to_runner(self):
        runner = FakeRunner()
        Scanner(runner).scan(ScanRequest(paths=("tests/foo_test.py",)))
        self.assertTrue(all(call[3] is True for call in runner.calls))

    def test_single_source_can_be_selected(self):
        runner = FakeRunner()
        Scanner(runner).scan(ScanRequest(sources=(Source.SMELLS,)))
        self.assertEqual([c[0] for c in runner.calls], [Source.SMELLS])

    def test_degradation_is_carried_through(self):
        runner = FakeRunner(
            {
                Source.SMELLS: [
                    result_of(
                        [make_finding()],
                        wire_format=WireFormat.SARIF,
                        degraded=True,
                        degrade_reason="--json unavailable",
                    )
                ]
            }
        )
        result = Scanner(runner).scan(ScanRequest(sources=(Source.SMELLS,)))
        self.assertTrue(result.degraded)
        self.assertIn("--json unavailable", result.degradations[0])


class DedupTests(unittest.TestCase):
    def test_similar_code_collapses_to_clone_groups(self):
        # qlty reports each clone pair once per location; 13 findings are 6
        # groups, so counting raw findings overstates the rule ~2x.
        smells = parse_json_findings(load("smells.json"), Source.SMELLS)
        runner = FakeRunner({Source.SMELLS: [result_of(smells)]})
        result = Scanner(runner).scan(ScanRequest(sources=(Source.SMELLS,)))

        clones = [f for f in result.findings if f.rule == "similar-code"]
        self.assertEqual(len(clones), 6)
        self.assertEqual(result.duplicates_collapsed, 7)

    def test_distinct_findings_are_not_collapsed(self):
        findings = [
            make_finding(path="src/a.py", line=1),
            make_finding(path="src/b.py", line=2),
        ]
        runner = FakeRunner({Source.SMELLS: [result_of(findings)]})
        result = Scanner(runner).scan(ScanRequest(sources=(Source.SMELLS,)))
        self.assertEqual(result.total, 2)
        self.assertEqual(result.duplicates_collapsed, 0)

    def test_same_group_key_collapses_across_locations(self):
        findings = [
            make_finding(rule="similar-code", path="src/a.py", group_key="h1"),
            make_finding(rule="similar-code", path="src/b.py", group_key="h1"),
        ]
        runner = FakeRunner({Source.SMELLS: [result_of(findings)]})
        result = Scanner(runner).scan(ScanRequest(sources=(Source.SMELLS,)))
        self.assertEqual(result.total, 1)


class RescanTests(unittest.TestCase):
    """qlty caps issues per run, so one scan can under-report (plan F5)."""

    def test_single_scan_by_default(self):
        runner = FakeRunner({Source.SMELLS: [result_of([make_finding()])]})
        result = Scanner(runner).scan(ScanRequest(sources=(Source.SMELLS,)))
        self.assertEqual(result.iterations, 1)
        self.assertEqual(len(runner.calls), 1)

    def test_rescan_accumulates_findings_across_runs(self):
        # A finding crowded out of run 1 but present in run 2 must survive:
        # the union is closer to the truth than any single run.
        first = result_of([make_finding(path="src/a.py")])
        second = result_of(
            [make_finding(path="src/a.py"), make_finding(path="src/b.py")]
        )
        runner = FakeRunner({Source.SMELLS: [first, second]})
        result = Scanner(runner).scan(
            ScanRequest(sources=(Source.SMELLS,)), rescan_until_stable=True
        )
        files = {f.file for f in result.findings}
        self.assertEqual(files, {"src/a.py", "src/b.py"})

    def test_rescan_stops_once_identities_repeat(self):
        steady = result_of([make_finding()])
        runner = FakeRunner({Source.SMELLS: [steady]})
        result = Scanner(runner).scan(
            ScanRequest(sources=(Source.SMELLS,)), rescan_until_stable=True
        )
        self.assertTrue(result.stable)
        self.assertEqual(result.iterations, 2)

    def test_rescan_carries_degradation_from_any_iteration(self):
        # The SARIF fallback may fire on only one iteration. Merging must keep
        # that warning, or a degraded run would present as a full-fidelity one.
        clean = result_of([make_finding(path="src/a.py")])
        degraded = result_of(
            [make_finding(path="src/b.py")],
            degraded=True,
            degrade_reason="--json unavailable; fell back to --sarif",
        )
        runner = FakeRunner({Source.SMELLS: [clean, degraded]})
        result = Scanner(runner).scan(
            ScanRequest(sources=(Source.SMELLS,)), rescan_until_stable=True
        )
        self.assertTrue(result.degradations)
        self.assertIn("--sarif", result.degradations[0])

    def test_repeated_degradation_reason_is_reported_once(self):
        # Every iteration degrades for the same reason; repeating the warning
        # per-iteration would bury the finding list in noise.
        degraded = result_of(
            [make_finding()],
            degraded=True,
            degrade_reason="--json unavailable; fell back to --sarif",
        )
        runner = FakeRunner({Source.SMELLS: [degraded]})
        result = Scanner(runner).scan(
            ScanRequest(sources=(Source.SMELLS,)), rescan_until_stable=True
        )
        self.assertEqual(len(result.degradations), 1)

    def test_unstable_scan_is_flagged_at_the_cap(self):
        # Alternating results never settle; the run must report instability
        # rather than silently presenting the last iteration as complete.
        runs = [
            result_of([make_finding(path=f"src/{i}.py")]) for i in range(10)
        ]
        runner = FakeRunner({Source.SMELLS: runs})
        result = Scanner(runner).scan(
            ScanRequest(sources=(Source.SMELLS,)),
            rescan_until_stable=True,
            max_iterations=3,
        )
        self.assertFalse(result.stable)
        self.assertEqual(result.iterations, 3)


class ScanResultTests(unittest.TestCase):
    def test_by_rule_orders_by_descending_count(self):
        findings = [
            make_finding(rule="b", path="src/1.py"),
            make_finding(rule="a", path="src/2.py"),
            make_finding(rule="a", path="src/3.py"),
        ]
        runner = FakeRunner({Source.SMELLS: [result_of(findings)]})
        result = Scanner(runner).scan(ScanRequest(sources=(Source.SMELLS,)))
        self.assertEqual(list(result.by_rule()), ["a", "b"])

    def test_identities_exclude_volatile_fields(self):
        # Identity is (rule, file, line) so a shifting metric does not make a
        # finding look new across runs.
        one = make_finding(value=6, message="a")
        two = make_finding(value=9, message="b")
        self.assertEqual(one.identity, two.identity)


class ScanRequestScopeTests(unittest.TestCase):
    """ScanRequest.scope derives the three-valued scope from its fields."""

    def test_scan_all_true_no_paths_is_all(self):
        self.assertIs(ScanRequest(scan_all=True).scope, Scope.ALL)

    def test_scan_all_false_no_paths_is_changed(self):
        self.assertIs(ScanRequest(scan_all=False).scope, Scope.CHANGED)

    def test_paths_override_scan_all_true(self):
        # The runner drops --all when paths are given, so the scan covered
        # neither the repo nor the diff -- claiming "all" would be a false clean.
        request = ScanRequest(scan_all=True, paths=("src/foo.py",))
        self.assertIs(request.scope, Scope.PATHS)

    def test_paths_override_scan_all_false(self):
        request = ScanRequest(scan_all=False, paths=("src/foo.py",))
        self.assertIs(request.scope, Scope.PATHS)

    def test_scope_stored_on_scan_result(self):
        runner = FakeRunner()
        result = Scanner(runner).scan(ScanRequest(paths=("src/x.py",)))
        self.assertIs(result.scope, Scope.PATHS)


class SiblingParamsObjectTests(unittest.TestCase):
    """The cross-reference that separates signal from noise."""

    def _tmpdir(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        return tmp

    def _write(self, body: str) -> tuple[Path, str]:
        tmp = self._tmpdir()
        (tmp / "mod.py").write_text(body, encoding="utf-8")
        return tmp, "mod.py"

    def test_detects_existing_params_object(self):
        root, name = self._write(
            "@dataclass\nclass EventCreationParams:\n    a: int\n"
        )
        self.assertTrue(sibling_uses_params_object(name, root=root))

    def test_detects_request_and_options_suffixes(self):
        for suffix in ("Request", "Options", "Config", "Patch", "Spec"):
            root, name = self._write(f"class Update{suffix}:\n    pass\n")
            self.assertTrue(
                sibling_uses_params_object(name, root=root), msg=suffix
            )

    def test_module_without_params_object(self):
        root, name = self._write("def f(a, b, c):\n    return a\n")
        self.assertFalse(sibling_uses_params_object(name, root=root))

    def test_unreadable_module_reports_no_evidence(self):
        # Must not guess: absence of evidence keeps the finding in the
        # default-LEAVE bucket rather than proposing a fix.
        self.assertFalse(
            sibling_uses_params_object("does/not/exist.py", root=self._tmpdir())
        )


if __name__ == "__main__":
    unittest.main()
