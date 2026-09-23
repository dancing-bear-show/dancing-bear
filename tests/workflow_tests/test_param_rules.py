"""Engine-enforced trigger ``param_rules`` / ``required`` (workflow.param_rules).

The rules must be enforced BEFORE ``resolve_params`` substitutes a value into
stage text: once substituted, the value is already in the prompt an agent
reads, so a check the agent is told to run is too late. Every rejection test
therefore asserts that compilation RAISED -- no manifest, no rendered prompt --
and that the error names the param without reproducing the value.

Assertions are on exceptions and exit status. Where printed text is checked,
it is only to prove the value was NOT echoed, never as the verdict.
"""

from __future__ import annotations

import subprocess  # nosec B404 - runs the repo's own ./bin/workflow wrapper
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import cast

from core.cli_errors import CLIError
from workflow.cli_compile import _build_compile_payload
from workflow.compiler import WorkflowCompileError, compile_workflow
from workflow.include import _parse_fragment_str
from workflow.linter import lint_workflow
from workflow.models import ParamRules, WorkflowManifest
from workflow.orchestrator import OrchestratorConfig, WorkflowExecutionError, WorkflowOrchestrator
from workflow.param_guard import ParamCheck
from workflow.parser import WorkflowParseError, parse_workflow, parse_workflow_str

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Cap on each wrapper subprocess: generous for a parse + compile, but finite,
#: so a hung wrapper fails this test instead of hanging the suite.
_WRAPPER_TIMEOUT_S = 60

HOST_PATTERN = r"https?://[A-Za-z0-9._-]+(:[0-9]{1,5})?/?"
PR_PATTERN = r"[1-9][0-9]{0,8}"

#: Closed a single-quoted heredoc early when substituted into script text.
HEREDOC_ESCAPE = "http://ok\nRAW\ntouch /tmp/X\ncat > /dev/null <<'RAW'\nx"
SUBSHELL = "http://h$(touch /tmp/X)"
BACKTICK = "http://h`id`"
HOSTILE = (HEREDOC_ESCAPE, SUBSHELL, BACKTICK, "http://ok; rm -rf ~", "http://ok\n")


def _workflow_yaml(
    *,
    rules: str = "",
    params: str = '    ollama_host: "http://localhost:11434"\n    pr_number: ""\n',
    extra_trigger: str = "",
    include: str = "",
) -> str:
    """A minimal workflow whose one stage substitutes both params into its text."""
    return (
        "name: probe\n"
        'version: "1"\n'
        "description: probe\n"
        "trigger:\n"
        "  source: manual\n"
        "  params:\n"
        f"{params}"
        f"{rules}"
        f"{extra_trigger}"
        f"{include}"
        "stages:\n"
        "  - name: s1\n"
        "    kind: gather\n"
        '    description: "host={ollama_host} pr={pr_number}"\n'
        "    agent: {role: researcher}\n"
    )


_RULES = (
    "  param_rules:\n"
    f"    ollama_host: '{HOST_PATTERN}'\n"
    f"    pr_number: '{PR_PATTERN}'\n"
)
_REQUIRED = "  required: [pr_number]\n"


def _compile(yaml_text: str, overrides: dict[str, str] | None = None) -> WorkflowManifest:
    return compile_workflow(parse_workflow_str(yaml_text), trigger_params=overrides)


def _description(manifest: WorkflowManifest) -> str:
    return manifest.resolved_stages["s1"].spec.description


class TestReservedPlaceholderParams(unittest.TestCase):
    """PR #406 round 11: resolve_params substitutes every declared {param},
    so a param named fan_out_index or workspace would overwrite the dispatch
    placeholder -- every fan-out item then shares one result file."""

    def test_param_named_after_a_dispatch_placeholder_is_rejected(self) -> None:
        for name in ("fan_out_index", "workspace"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(WorkflowCompileError, f"{name} collide with reserved"):
                    _compile(_workflow_yaml(params=f'    {name}: "0"\n'))

    def test_ordinary_params_still_compile(self) -> None:
        _compile(_workflow_yaml(params='    fan_out_idx: "0"\n    ollama_host: "http://h"\n    pr_number: "1"\n'))


def _fan_out_yaml(key: str, params: str = '    domain: "trigger-value"\n') -> str:
    """A source stage plus a fan-out stage keyed on *key*; the fan-out stage's
    description names both {domain} and {other}."""
    return (
        "name: probe\n"
        'version: "1"\n'
        "description: probe\n"
        "trigger:\n"
        "  source: manual\n"
        "  params:\n"
        f"{params}"
        '    other: "o"\n'
        "stages:\n"
        "  - name: src\n"
        "    kind: gather\n"
        '    description: "list items"\n'
        "    agent: {role: researcher}\n"
        "    writes_to: [items.json]\n"
        "  - name: fan\n"
        "    kind: execute\n"
        "    depends_on: [src]\n"
        '    description: "item={domain} other={other}"\n'
        "    agent: {role: researcher}\n"
        "    fan_out:\n"
        "      source: src\n"
        "      field: items\n"
        f"      key: {key!r}\n"
    )


class TestFanOutKeyVersusTriggerParams(unittest.TestCase):
    """PR #406 round 13: resolve_params substituted a trigger param that
    shared the fan-out key's name, so every item saw the trigger value; and
    an empty key was accepted, so every item shared one result path."""

    def test_fan_out_key_is_left_for_the_item_not_the_trigger_param(self) -> None:
        manifest = _compile(_fan_out_yaml("domain"))
        description = manifest.resolved_stages["fan"].spec.description
        self.assertIn("item={domain}", description)
        self.assertIn("other=o", description)

    def test_same_param_is_still_substituted_in_non_fan_out_stages(self) -> None:
        yaml_text = _fan_out_yaml("domain").replace('description: "list items"',
                                                    'description: "list {domain}"')
        manifest = _compile(yaml_text)
        self.assertIn("list trigger-value", manifest.resolved_stages["src"].spec.description)

    def test_empty_fan_out_key_is_rejected(self) -> None:
        for key in ("", "   "):
            with self.subTest(key=key):
                with self.assertRaisesRegex(WorkflowCompileError, "fan_out.key must be a non-empty name"):
                    _compile(_fan_out_yaml(key))


class TestCompileEnforcement(unittest.TestCase):
    """compile_workflow is the enforcement point: it raises before substituting."""

    def test_hostile_override_is_rejected_and_never_echoed(self) -> None:
        for payload in HOSTILE:
            with self.subTest(payload=payload):
                with self.assertRaises(WorkflowCompileError) as ctx:
                    _compile(_workflow_yaml(rules=_RULES), {"ollama_host": payload})
                message = str(ctx.exception)
                self.assertIn("ollama_host", message)
                self.assertNotIn(payload, message)
                # No fragment of the payload's executable part leaks either.
                self.assertNotIn("touch", message)

    def test_heredoc_escape_payload_is_rejected(self) -> None:
        with self.assertRaises(WorkflowCompileError):
            _compile(_workflow_yaml(rules=_RULES), {"ollama_host": HEREDOC_ESCAPE})

    def test_subshell_payload_is_rejected(self) -> None:
        with self.assertRaises(WorkflowCompileError):
            _compile(_workflow_yaml(rules=_RULES), {"ollama_host": SUBSHELL})

    def test_trailing_newline_is_rejected_by_fullmatch(self) -> None:
        # re.match/search with `$` would accept "…:11434\n"; fullmatch must not.
        with self.assertRaises(WorkflowCompileError):
            _compile(_workflow_yaml(rules=_RULES), {"ollama_host": "http://h:1\n"})

    def test_valid_override_passes_and_is_substituted(self) -> None:
        manifest = _compile(_workflow_yaml(rules=_RULES), {"ollama_host": "http://gpu-box:11434", "pr_number": "42"})
        self.assertEqual(_description(manifest), "host=http://gpu-box:11434 pr=42")

    def test_default_passes(self) -> None:
        manifest = _compile(_workflow_yaml(rules=_RULES))
        self.assertEqual(_description(manifest), "host=http://localhost:11434 pr=")

    def test_optional_blank_param_is_exempt_from_its_rule(self) -> None:
        # pr_number has a rule that "" cannot match, but is not required.
        manifest = _compile(_workflow_yaml(rules=_RULES), {"pr_number": ""})
        self.assertIn("pr=", _description(manifest))

    def test_required_blank_fails_naming_the_param_and_the_fix(self) -> None:
        with self.assertRaises(WorkflowCompileError) as ctx:
            _compile(_workflow_yaml(rules=_RULES, extra_trigger=_REQUIRED))
        self.assertIn("pr_number", str(ctx.exception))
        self.assertIn("--params pr_number=", str(ctx.exception))

    def test_required_whitespace_only_counts_as_blank(self) -> None:
        with self.assertRaises(WorkflowCompileError) as ctx:
            _compile(_workflow_yaml(extra_trigger=_REQUIRED), {"pr_number": "  \t"})
        self.assertIn("required", str(ctx.exception))

    def test_required_blank_is_reported_once_not_also_as_a_mismatch(self) -> None:
        with self.assertRaises(WorkflowCompileError) as ctx:
            _compile(_workflow_yaml(rules=_RULES, extra_trigger=_REQUIRED))
        self.assertNotIn("does not match", str(ctx.exception))

    def test_required_supplied_passes(self) -> None:
        manifest = _compile(_workflow_yaml(rules=_RULES, extra_trigger=_REQUIRED), {"pr_number": "391"})
        self.assertIn("pr=391", _description(manifest))

    def test_required_supplied_must_still_match_its_rule(self) -> None:
        with self.assertRaises(WorkflowCompileError) as ctx:
            _compile(_workflow_yaml(rules=_RULES, extra_trigger=_REQUIRED), {"pr_number": "0; id"})
        self.assertNotIn("0; id", str(ctx.exception))

    def test_every_violation_is_reported_at_once(self) -> None:
        with self.assertRaises(WorkflowCompileError) as ctx:
            _compile(_workflow_yaml(rules=_RULES), {"ollama_host": SUBSHELL, "pr_number": "x"})
        self.assertIn("ollama_host", str(ctx.exception))
        self.assertIn("pr_number", str(ctx.exception))

    def test_non_string_override_is_a_compile_error_not_a_type_error(self) -> None:
        # Previously resolve_params raised TypeError from str.replace. Applies
        # with or without rules, since the crash did too.
        # cast: the wrong type is the point -- a programmatic caller can pass it.
        overrides = cast(dict[str, str], {"pr_number": 5})
        for ruled, yaml_text in ((True, _workflow_yaml(rules=_RULES)), (False, _workflow_yaml())):
            with self.subTest(ruled=ruled), self.assertRaises(WorkflowCompileError) as ctx:
                _compile(yaml_text, overrides)
            self.assertIn("pr_number: not a string (got int)", str(ctx.exception))

    def test_workflow_without_rules_is_unchanged(self) -> None:
        defn = parse_workflow_str(_workflow_yaml())
        self.assertEqual(defn.trigger.rules, ParamRules())
        # Same raw substitution as before this feature: no rules, no filtering.
        manifest = compile_workflow(defn, trigger_params={"ollama_host": SUBSHELL})
        self.assertEqual(_description(manifest), f"host={SUBSHELL} pr=")


class TestParseTimeRejection(unittest.TestCase):
    """Malformed rule blocks fail parse -- and therefore lint -- not compile."""

    def _assert_parse_error(self, yaml_text: str, fragment: str) -> None:
        with self.assertRaises(WorkflowParseError) as ctx:
            parse_workflow_str(yaml_text)
        self.assertIn(fragment, str(ctx.exception))

    def test_rule_for_undeclared_param(self) -> None:
        self._assert_parse_error(
            _workflow_yaml(rules="  param_rules:\n    olama_host: 'x'\n"), "olama_host"
        )

    def test_required_undeclared_param(self) -> None:
        self._assert_parse_error(_workflow_yaml(extra_trigger="  required: [nope]\n"), "nope")

    def test_invalid_regex(self) -> None:
        self._assert_parse_error(
            _workflow_yaml(rules="  param_rules:\n    pr_number: '[0-9'\n"), "not a valid regex"
        )

    def test_non_string_rule(self) -> None:
        for bad in ("123", "[a, b]", "{x: y}", "null"):
            with self.subTest(bad=bad):
                self._assert_parse_error(
                    _workflow_yaml(rules=f"  param_rules:\n    pr_number: {bad}\n"),
                    "must be a string regex",
                )

    def test_param_rules_not_a_mapping(self) -> None:
        self._assert_parse_error(_workflow_yaml(rules="  param_rules: [pr_number]\n"), "must be a mapping")

    def test_required_not_a_list_of_names(self) -> None:
        for bad in ("pr_number", "[1]", "{pr_number: true}"):
            with self.subTest(bad=bad):
                self._assert_parse_error(
                    _workflow_yaml(extra_trigger=f"  required: {bad}\n"), "list of param names"
                )

    def test_default_that_fails_its_own_rule(self) -> None:
        self._assert_parse_error(
            _workflow_yaml(
                rules=f"  param_rules:\n    ollama_host: '{HOST_PATTERN}'\n",
                params='    ollama_host: "ftp://nope"\n    pr_number: ""\n',
            ),
            "default fails its own rule",
        )

    def test_rules_are_parsed_onto_the_trigger(self) -> None:
        defn = parse_workflow_str(_workflow_yaml(rules=_RULES, extra_trigger=_REQUIRED))
        self.assertEqual(
            defn.trigger.rules,
            ParamRules(
                checks=(ParamCheck("ollama_host", HOST_PATTERN), ParamCheck("pr_number", PR_PATTERN)),
                required=frozenset({"pr_number"}),
            ),
        )


class _TempDirMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path


class TestLint(_TempDirMixin):
    def test_malformed_param_rules_is_a_lint_error(self) -> None:
        path = self.write("wf.yaml", _workflow_yaml(rules="  param_rules:\n    pr_number: '(('\n"))
        result = lint_workflow(path)
        self.assertFalse(result.valid)
        self.assertTrue(any("not a valid regex" in e.message for e in result.errors))

    def test_malformed_fragment_rules_is_a_lint_error_on_the_fragment_alone(self) -> None:
        path = self.write("frag.yaml", _FRAGMENT.format(rules="  param_rules:\n    frag_param: 7\n"))
        result = lint_workflow(path)
        self.assertFalse(result.valid)
        self.assertTrue(any("must be a string regex" in e.message for e in result.errors))


_FRAGMENT = textwrap.dedent("""\
    fragment: true
    trigger:
      source: manual
      params:
        frag_param: "ok"
    {rules}
    stages:
      - name: f1
        kind: gather
        description: "frag={{frag_param}} host={{ollama_host}}"
        agent: {{role: researcher}}
    """)


class TestFragments(_TempDirMixin):
    """Fragments may carry rules; they merge with the importer's, never replace them."""

    def _parent(self, frag_rules: str, parent_rules: str = "") -> Path:
        self.write("frag.yaml", _FRAGMENT.format(rules=frag_rules))
        include = "include:\n  - path: frag.yaml\n    prefix: fr\n    depends_on: [s1]\n"
        return self.write("wf.yaml", _workflow_yaml(rules=parent_rules, include=include))

    def test_fragment_rule_is_enforced_when_the_parent_compiles(self) -> None:
        path = self._parent("  param_rules:\n    frag_param: '[a-z]+'\n")
        compile_workflow(parse_workflow(path), trigger_params={"frag_param": "fine"})
        with self.assertRaises(WorkflowCompileError) as ctx:
            compile_workflow(parse_workflow(path), trigger_params={"frag_param": SUBSHELL})
        self.assertIn("frag_param", str(ctx.exception))

    def test_parent_rule_covers_a_param_only_the_fragment_declares(self) -> None:
        path = self._parent("", parent_rules="  param_rules:\n    frag_param: '[a-z]+'\n")
        with self.assertRaises(WorkflowCompileError):
            compile_workflow(parse_workflow(path), trigger_params={"frag_param": SUBSHELL})

    def test_fragment_rule_on_a_param_the_parent_declares(self) -> None:
        # Shared fragments consume params the importer declares.
        path = self._parent(f"  param_rules:\n    ollama_host: '{HOST_PATTERN}'\n")
        with self.assertRaises(WorkflowCompileError):
            compile_workflow(parse_workflow(path), trigger_params={"ollama_host": HEREDOC_ESCAPE})

    def test_parent_and_fragment_rules_must_both_hold(self) -> None:
        path = self._parent(
            "  param_rules:\n    frag_param: '[a-z]+'\n",
            parent_rules="  param_rules:\n    frag_param: '[a-o]+'\n",  # default "ok" passes both
        )
        compile_workflow(parse_workflow(path), trigger_params={"frag_param": "abc"})
        with self.assertRaises(WorkflowCompileError):
            # Passes the fragment's rule, fails the parent's.
            compile_workflow(parse_workflow(path), trigger_params={"frag_param": "xyz"})

    def test_fragment_required_propagates(self) -> None:
        path = self._parent("  required: [frag_param]\n")
        with self.assertRaises(WorkflowCompileError):
            compile_workflow(parse_workflow(path), trigger_params={"frag_param": ""})

    def test_malformed_fragment_rule_fails_the_parent_parse(self) -> None:
        path = self._parent("  param_rules:\n    frag_param: '(('\n")
        with self.assertRaises(WorkflowParseError):
            parse_workflow(path)

    def test_fragment_rule_on_a_param_nobody_declares_fails_the_parent_parse(self) -> None:
        path = self._parent("  param_rules:\n    ghost: 'x'\n")
        with self.assertRaises(WorkflowParseError) as ctx:
            parse_workflow(path)
        self.assertIn("ghost", str(ctx.exception))

    def test_fragment_parser_rejects_malformed_rules(self) -> None:
        with self.assertRaises(WorkflowParseError):
            _parse_fragment_str(_FRAGMENT.format(rules="  required: frag_param\n"), "frag.yaml")


class TestCompileSubcommand(_TempDirMixin):
    """`workflow compile --params` now compiles WITH the overrides."""

    def test_hostile_params_are_rejected(self) -> None:
        path = self.write("wf.yaml", _workflow_yaml(rules=_RULES))
        with self.assertRaises(CLIError) as ctx:
            _build_compile_payload(str(path), [f"ollama_host={SUBSHELL}"])
        self.assertNotIn(SUBSHELL, str(ctx.exception))

    def test_required_param_supplied_via_params_compiles(self) -> None:
        path = self.write("wf.yaml", _workflow_yaml(rules=_RULES, extra_trigger=_REQUIRED))
        payload = _build_compile_payload(str(path), ["pr_number=12"])
        self.assertEqual(payload["total_stages"], 1)
        with self.assertRaises(CLIError):
            _build_compile_payload(str(path), [])


class TestOrchestratorRecheck(_TempDirMixin):
    """A compiled manifest paired with different params is re-checked before any work."""

    def _manifest(self) -> WorkflowManifest:
        return _compile(_workflow_yaml(rules=_RULES))

    def test_constructor_rejects_hostile_params_before_creating_a_workspace(self) -> None:
        base = self.tmp / "ws"
        config = OrchestratorConfig(
            manifest=self._manifest(), workspace_dir=base, dry_run=True,
            trigger_params={"ollama_host": HEREDOC_ESCAPE},
        )
        with self.assertRaises(WorkflowExecutionError) as ctx:
            WorkflowOrchestrator(config)
        self.assertNotIn(HEREDOC_ESCAPE, str(ctx.exception))
        self.assertFalse(base.exists())

    def test_resume_rejects_hostile_params(self) -> None:
        with self.assertRaises(WorkflowExecutionError):
            WorkflowOrchestrator.resume(
                self._manifest(), self.tmp, trigger_params={"pr_number": "$(id)"}
            )

    def test_valid_params_construct(self) -> None:
        config = OrchestratorConfig(
            manifest=self._manifest(), workspace_dir=self.tmp / "ws", dry_run=True,
            trigger_params={"pr_number": "7"},
        )
        self.assertIsInstance(WorkflowOrchestrator(config), WorkflowOrchestrator)


class TestWrapperEndToEnd(_TempDirMixin):
    """Drive the real ./bin/workflow wrapper the way the /workflow skill does."""

    def setUp(self) -> None:
        super().setUp()
        self.base = self.tmp / "base"
        self.base.mkdir()
        self.marker = self.tmp / "PWNED"
        self.wf = self.write("wf.yaml", _workflow_yaml(rules=_RULES))

    def _run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 - fixed argv, no shell, repo-owned binary
            [str(_REPO_ROOT / "bin" / "workflow"), *argv],
            capture_output=True, text=True, cwd=str(_REPO_ROOT), check=False,
            timeout=_WRAPPER_TIMEOUT_S,
        )

    def _payloads(self) -> tuple[str, ...]:
        return (
            f"http://ok\nRAW\ntouch {self.marker}\ncat > /dev/null <<'RAW'\nx",
            f"http://h$(touch {self.marker})",
        )

    def _init(self, value: str) -> subprocess.CompletedProcess[str]:
        return self._run(
            "init-workspace", str(self.wf), "--base-dir", str(self.base),
            "--params", f"ollama_host={value}",
        )

    def test_init_workspace_rejects_hostile_params_and_writes_nothing(self) -> None:
        for payload in self._payloads():
            with self.subTest(payload=payload):
                proc = self._init(payload)
                self.assertEqual(proc.returncode, 1, proc.stderr)
                self.assertEqual(list(self.base.rglob("manifest.json")), [])
                self.assertEqual(list(self.base.iterdir()), [])
                self.assertFalse(self.marker.exists())
                self.assertNotIn(payload, proc.stderr + proc.stdout)

    def test_init_workspace_accepts_a_valid_value(self) -> None:
        # Positive control: proves the rejection above is the rule, not a broken harness.
        proc = self._init("http://gpu-box:11434")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(list(self.base.rglob("manifest.json"))), 1)

    def test_run_rejects_hostile_params(self) -> None:
        proc = self._run(
            "run", str(self.wf), "--workspace", str(self.base),
            "--params", f"ollama_host={self._payloads()[1]}",
        )
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(list(self.base.iterdir()), [])

    def _compile(self, value: str) -> subprocess.CompletedProcess[str]:
        return self._run(
            "compile", str(self.wf), "--no-compile-cache", "--format", "json",
            "--params", f"ollama_host={value}",
        )

    def test_compile_rejects_hostile_params(self) -> None:
        proc = self._compile(self._payloads()[1])
        # Exactly 1 (CLIError), not merely non-zero: argparse's usage error is
        # 2, and a misspelt flag once made this test pass without compiling.
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("Compile error", proc.stderr)
        self.assertFalse(self.marker.exists())

    def test_compile_accepts_a_valid_value(self) -> None:
        self.assertEqual(self._compile("http://gpu-box:11434").returncode, 0)


if __name__ == "__main__":
    unittest.main()
