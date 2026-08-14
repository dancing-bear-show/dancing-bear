"""Parsing/normalization contract for qlty's --json and --sarif output."""

from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from core.cli_errors import CLIError, ExitCode
from qlty.models import Source, WireFormat
from qlty.runner import (
    QltyError,
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

    def test_absent_or_unusable_location_degrades_to_empty_not_crash(self):
        # A finding with no parseable location is still a finding; losing the
        # position must not lose the whole entry.
        payload = json.dumps(
            [
                {"ruleKey": "a"},
                {"ruleKey": "b", "location": "not-a-dict"},
                {"ruleKey": "c", "location": {"path": "src/c.py"}},
                {"ruleKey": "d", "location": {"path": "src/d.py", "range": "bad"}},
            ]
        )
        findings = parse_json_findings(payload, Source.SMELLS)
        self.assertEqual([f.file for f in findings], ["", "", "src/c.py", "src/d.py"])
        self.assertTrue(all(f.line == 0 for f in findings))

    def test_non_integer_value_is_dropped_rather_than_coerced(self):
        # `value` feeds numeric thresholds. A non-int must become None
        # ("unknown"), never 0, which would read as "below every threshold".
        payload = '[{"ruleKey": "a", "value": "6"}]'
        self.assertIsNone(parse_json_findings(payload, Source.SMELLS)[0].value)


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

    def test_non_object_document_raises(self):
        # A SARIF array (rather than an object) means the format moved; it must
        # not decay to zero findings.
        with self.assertRaises(QltyInvocationError) as ctx:
            parse_sarif_findings("[]", Source.SMELLS)
        self.assertIn("expected a SARIF object", str(ctx.exception))

    def test_malformed_run_entry_raises(self):
        # A non-dict inside `runs` would otherwise be skipped silently, hiding
        # however many findings that run contained.
        payload = '{"runs": [1]}'
        with self.assertRaises(QltyInvocationError) as ctx:
            parse_sarif_findings(payload, Source.SMELLS)
        self.assertIn("malformed SARIF", str(ctx.exception))

    def test_message_accepts_both_sarif_shapes(self):
        # SARIF nests message under {"text": ...}; some emitters use a bare
        # string. Both must survive, or findings render with empty messages.
        payload = json.dumps(
            {
                "runs": [
                    {
                        "results": [
                            {"ruleId": "qlty:a", "message": {"text": "nested"}},
                            {"ruleId": "qlty:b", "message": "bare"},
                            {"ruleId": "qlty:c"},
                        ]
                    }
                ]
            }
        )
        messages = [f.message for f in parse_sarif_findings(payload, Source.SMELLS)]
        self.assertEqual(messages, ["nested", "bare", ""])

    def test_unusable_location_entries_are_skipped_not_fatal(self):
        # Unlike a malformed *result*, a malformed location entry loses only
        # position detail -- the finding itself still counts, so it is dropped
        # rather than raising.
        payload = json.dumps(
            {
                "runs": [
                    {
                        "results": [
                            {
                                "ruleId": "qlty:a",
                                "locations": [
                                    "not-a-dict",
                                    {"physicalLocation": "not-a-dict"},
                                    {
                                        "physicalLocation": {
                                            "artifactLocation": {"uri": "src/a.py"},
                                            "region": {"startLine": 4},
                                        }
                                    },
                                ],
                            }
                        ]
                    }
                ]
            }
        )
        findings = parse_sarif_findings(payload, Source.SMELLS)
        self.assertEqual(len(findings), 1)
        # The one usable location survives and becomes the primary.
        self.assertEqual(findings[0].file, "src/a.py")
        self.assertEqual(findings[0].line, 4)

    def test_locations_absent_entirely_yields_empty_location(self):
        payload = '{"runs": [{"results": [{"ruleId": "qlty:a"}]}]}'
        findings = parse_sarif_findings(payload, Source.SMELLS)
        self.assertEqual(findings[0].file, "")
        self.assertEqual(findings[0].line, 0)


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

    def test_paths_are_guarded_by_an_end_of_options_marker(self):
        # Without the "--", a path beginning with "-" is parsed by qlty as a
        # flag, silently changing what gets scanned.
        runner = self._runner()
        with patch.object(
            runner, "_execute", return_value=completed("[]", 0)
        ) as executed:
            runner.invoke(Source.SMELLS, paths=("-weird.py", "src/a.py"))

        args = executed.call_args[0][0]
        self.assertIn("--", args)
        # The marker must precede the paths, or it guards nothing.
        self.assertLess(args.index("--"), args.index("-weird.py"))

    def test_no_end_of_options_marker_when_no_paths_given(self):
        # A bare "--" with nothing after it is noise; only emit it when it
        # actually guards something.
        runner = self._runner()
        with patch.object(
            runner, "_execute", return_value=completed("[]", 0)
        ) as executed:
            runner.invoke(Source.SMELLS)
        self.assertNotIn("--", executed.call_args[0][0])

    def test_changed_scope_omits_all_flag(self):
        runner = self._runner()
        with patch.object(
            runner, "_execute", return_value=completed("[]", 0)
        ) as executed:
            runner.invoke(Source.SMELLS, scan_all=False)
        self.assertNotIn("--all", executed.call_args[0][0])


class ExecuteSubprocessFailureTests(unittest.TestCase):
    """The two subprocess failure modes _execute itself maps.

    Every other runner test patches `_execute`, which mocks over the very
    try/except being asserted here. These patch `subprocess.run` instead so the
    real mapping code runs.
    """

    def _runner(self) -> QltyRunner:
        """A runner whose binary resolves without touching the filesystem.

        `_execute` resolves the binary before spawning, so an unresolvable path
        would raise QltyNotInstalledError and never reach the subprocess call
        these tests exist to exercise.
        """
        runner = QltyRunner(binary="/fake/qlty", timeout=7)
        patcher = patch.object(runner, "_resolved_binary", return_value="/fake/qlty")
        patcher.start()
        self.addCleanup(patcher.stop)
        return runner

    def test_timeout_becomes_invocation_error(self):
        # qlty hanging must surface as a loud failure, never an empty finding
        # set that reads as a clean repo.
        boom = subprocess.TimeoutExpired(cmd=["qlty", "smells"], timeout=7)
        with patch("qlty.runner.subprocess.run", side_effect=boom):
            with self.assertRaises(QltyInvocationError) as ctx:
                self._runner()._execute(["smells"])

        message = str(ctx.exception)
        self.assertIn("timed out", message)
        # The timeout value is what the operator needs to act on.
        self.assertIn("7", message)
        self.assertTrue(ctx.exception.hint)

    def test_unexecutable_binary_becomes_invocation_error(self):
        # Binary missing or not +x: OSError from exec, not a scan result.
        boom = OSError(13, "Permission denied")
        with patch("qlty.runner.subprocess.run", side_effect=boom):
            with self.assertRaises(QltyInvocationError) as ctx:
                self._runner()._execute(["smells"])

        message = str(ctx.exception)
        self.assertIn("could not execute qlty", message)
        self.assertIn("Permission denied", message)
        # Name the binary that failed, so the hint is actionable.
        self.assertIn("/fake/qlty", message)
        self.assertTrue(ctx.exception.hint)

    def test_successful_run_is_captured(self):
        # Pins the happy path through the same code, so the two failure tests
        # above cannot pass merely because _execute always raises.
        proc = subprocess.CompletedProcess(
            args=["qlty", "smells"], returncode=1, stdout="[]", stderr="spinner"
        )
        with patch("qlty.runner.subprocess.run", return_value=proc):
            run = self._runner()._execute(["smells"])

        self.assertEqual(run.stdout, "[]")
        self.assertEqual(run.returncode, 1)
        self.assertEqual(run.command, ("/fake/qlty", "smells"))


class ParseOrRaiseTests(unittest.TestCase):
    """_parse_or_raise's two failure modes are distinct and both must be loud."""

    def test_invocation_error_propagates_with_its_own_message(self):
        # Already a QltyInvocationError: re-raised as-is, so the specific
        # diagnosis survives instead of being flattened into the generic
        # "unparseable output" wrapper _parse_or_raise adds to ValueErrors.
        runner = QltyRunner(binary="/fake/qlty")
        with patch.object(
            runner, "_execute", return_value=completed('{"oops": true}', 0)
        ):
            with self.assertRaises(QltyInvocationError) as ctx:
                runner.invoke(Source.SMELLS)

        message = str(ctx.exception)
        self.assertIn("expected a JSON array", message)
        self.assertNotIn("unparseable", message)

    def test_json_decode_error_is_wrapped_as_not_a_clean_scan(self):
        # A raw ValueError from json.loads would escape the CLIError contract;
        # it must be converted and must say it is not a clean scan.
        runner = QltyRunner(binary="/fake/qlty")
        runs = [completed("{not json", 0), completed("{not json", 0)]
        with patch.object(runner, "_execute", side_effect=runs):
            with self.assertRaises(QltyInvocationError) as ctx:
                runner.invoke(Source.SMELLS)
        self.assertIn("clean scan", str(ctx.exception))


class ErrorContractTests(unittest.TestCase):
    """qlty errors participate in the framework's CLIError contract."""

    def test_qlty_error_is_a_cli_error(self):
        # So CLIApp's handler renders message + hint instead of each command
        # hand-formatting its own.
        self.assertTrue(issubclass(QltyError, CLIError))

    def test_not_installed_carries_a_config_exit_code_and_hint(self):
        with self.assertRaises(QltyNotInstalledError) as ctx:
            resolve_binary("/nonexistent/qlty-binary")

        self.assertEqual(ctx.exception.code, ExitCode.CONFIG_ERROR)
        self.assertIn("qlty.sh", ctx.exception.hint)


class ResolveBinaryTests(unittest.TestCase):
    def test_explicit_missing_path_raises(self):
        with self.assertRaises(QltyNotInstalledError):
            resolve_binary("/nonexistent/qlty-binary")

    def test_explicit_existing_path_is_used_verbatim(self):
        with patch("qlty.runner.Path") as path_cls:
            path_cls.return_value.is_file.return_value = True
            self.assertEqual(resolve_binary("/opt/qlty"), "/opt/qlty")

    def test_env_var_is_consulted_when_no_explicit_path(self):
        # $QLTY_BIN is the documented override; it must win over the default
        # install path.
        with patch("qlty.runner.Path") as path_cls:
            path_cls.return_value.is_file.return_value = True
            with patch.dict("os.environ", {"QLTY_BIN": "/env/qlty"}, clear=True):
                self.assertEqual(resolve_binary(), "/env/qlty")

    def test_default_install_path_is_preferred_over_path_lookup(self):
        # CLAUDE.md documents ~/.qlty/bin/qlty as canonical, so a stale `qlty`
        # earlier on PATH must not shadow it.
        with patch("qlty.runner._DEFAULT_BINARY") as default:
            default.is_file.return_value = True
            default.__str__.return_value = "/home/u/.qlty/bin/qlty"
            with patch("qlty.runner.shutil.which", return_value="/usr/bin/qlty"):
                with patch.dict("os.environ", {}, clear=True):
                    self.assertEqual(resolve_binary(), "/home/u/.qlty/bin/qlty")

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


class BaseArgsPathForwardingTests(unittest.TestCase):
    """Explicit paths must never be re-read by qlty as flags."""

    def test_no_separator_when_no_paths(self):
        args = QltyRunner._base_args(Source.SMELLS, scan_all=True, paths=())
        self.assertNotIn("--", args)

    def test_separator_precedes_explicit_paths(self):
        args = QltyRunner._base_args(
            Source.SMELLS, scan_all=False, paths=("src/qlty/runner.py",)
        )
        self.assertIn("--", args)
        self.assertLess(args.index("--"), args.index("src/qlty/runner.py"))

    def test_leading_dash_path_is_not_read_as_a_flag(self):
        # A file literally named "-foo.py", or a stray "--all", must land after
        # the end-of-options marker rather than altering the scan.
        args = QltyRunner._base_args(
            Source.CHECK, scan_all=False, paths=("-foo.py", "--all")
        )
        sep = args.index("--")
        self.assertEqual(args[sep + 1:], ["-foo.py", "--all"])
        # --all appears only as a forwarded path, never as a scan flag.
        self.assertNotIn("--all", args[:sep])

    def test_check_keeps_read_only_flags_before_the_separator(self):
        args = QltyRunner._base_args(
            Source.CHECK, scan_all=True, paths=("src/qlty/",)
        )
        sep = args.index("--")
        self.assertIn("--no-fix", args[:sep])
        self.assertIn("--no-cache", args[:sep])
        self.assertIn("--all", args[:sep])


if __name__ == "__main__":
    unittest.main()
