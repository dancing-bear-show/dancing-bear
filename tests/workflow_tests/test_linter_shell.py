"""Tests for the shell-text lint rules (workflow.linter_shell, workflow.shell_text).

Every rule has three kinds of test:

* a fire fixture excerpted from a real historical defect -- the commit it
  came from is named in each fixture's comment;
* near-miss fixtures that must NOT fire (quoted, validated, or prose);
* a teeth test: with only that rule's check stubbed out, the fire fixture
  lints clean with zero warnings, so no other check already covers it and
  the rule is what makes the defect visible.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

from workflow.linter import LintResult, lint_workflow
from workflow.linter_shell import (
    RULE_GUARD_REFUSED,
    RULE_PYTHON_NOT_ISOLATED,
    RULE_UNBOUND_VARIABLE,
    RULE_UNQUOTED_FAN_OUT_KEY,
    RULE_UNVALIDATED_PARAM,
    RULE_VALIDATE_WRITES_OUTPUT,
)
from workflow.linter_types import LintWarning
from workflow.shell_text import extract_shell_segments, quote_context

# The check behind each rule id, for the teeth tests.
_RULE_CHECKS: dict[str, str] = {
    RULE_UNVALIDATED_PARAM: "_unvalidated_params",
    RULE_UNQUOTED_FAN_OUT_KEY: "_unquoted_fan_out_keys",
    RULE_UNBOUND_VARIABLE: "_unbound_variables",
    RULE_PYTHON_NOT_ISOLATED: "_unisolated_pythons",
    RULE_VALIDATE_WRITES_OUTPUT: "_validate_writes_output",
    RULE_GUARD_REFUSED: "_guard_refused",
}


def _indent(text: str, spaces: int) -> str:
    return textwrap.indent(textwrap.dedent(text).strip("\n"), " " * spaces)


def _stage(
    description: str,
    *,
    name: str = "work",
    kind: str = "execute",
    depends_on: str = "[]",
    extra: str = "",
) -> str:
    """One stage entry. *description* is dedented and placed in a folded scalar."""
    return (
        f"  - name: {name}\n"
        f"    kind: {kind}\n"
        f"    depends_on: {depends_on}\n"
        f"    description: >\n{_indent(description, 6)}\n"
        f"    agent:\n      role: code-writer\n"
        f"{extra}"
    )


def _workflow(*stages: str, params: str = "", rules: str = "", tail: str = "") -> str:
    trigger = "trigger:\n  source: manual\n"
    if params:
        trigger += f"  params:\n{_indent(params, 4)}\n"
    if rules:
        trigger += f"  param_rules:\n{_indent(rules, 4)}\n"
    return (
        'name: t\nversion: "1.0"\ndescription: d\n'
        f"{trigger}stages:\n" + "".join(stages) + tail
    )


def _lint_text(yaml_text: str, tmp_dir: str, name: str = "wf.yaml") -> LintResult:
    path = Path(tmp_dir) / name
    path.write_text(yaml_text, encoding="utf-8")
    return lint_workflow(path)


def _lint(yaml_text: str) -> LintResult:
    with tempfile.TemporaryDirectory() as tmp_dir:
        return _lint_text(yaml_text, tmp_dir)


def _hits(result: LintResult, rule: str) -> list[LintWarning]:
    return [w for w in result.warnings if w.rule == rule]


class _RuleCase(unittest.TestCase):
    rule: str = ""

    def assert_fires(self, yaml_text: str, *, count: int = 1) -> list[LintWarning]:
        result = _lint(yaml_text)
        hits = _hits(result, self.rule)
        self.assertEqual(len(hits), count, msg=[w.message for w in result.warnings])
        for w in hits:
            self.assertEqual(w.field, "description")
            self.assertTrue(w.message.startswith(f"[{self.rule}] "))
        self.assertTrue(result.valid, msg="shell rules are warnings, never errors")
        return hits

    def assert_silent(self, yaml_text: str) -> None:
        result = _lint(yaml_text)
        self.assertEqual(_hits(result, self.rule), [], msg=[w.message for w in result.warnings])

    def assert_has_teeth(self, yaml_text: str) -> None:
        """With this rule's check stubbed out, the fixture lints clean."""
        self.assertTrue(_hits(_lint(yaml_text), self.rule))
        with mock.patch(f"workflow.linter_shell.{_RULE_CHECKS[self.rule]}", return_value=[]):
            result = _lint(yaml_text)
        self.assertEqual(result.warnings, [])
        self.assertTrue(result.valid)


# ---------------------------------------------------------------------------
# shell-unvalidated-param
# ---------------------------------------------------------------------------

# qwen-local-handler.yaml survey stage at 6474c76e (PR #391 round 0), the
# class that took 30 threads over 11 rounds.
_OLLAMA_PROBE = """
    Probe each layer:

      command -v ollama || echo "ollama: absent"
      curl -sS -m 3 -f -o /dev/null {ollama_host}/api/tags && echo "http: ok" || echo "http: unreachable"
"""
_OLLAMA_PARAMS = 'ollama_host: "http://localhost:11434"'
_OLLAMA_RULE = "ollama_host: 'https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?/?'"
_CHECK_PARAMS = """
    Validate the host first:

      ./bin/workflow check-params "{workspace}"/manifest.json \\
        --check 'ollama_host=https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?/?'
"""


class TestUnvalidatedParam(_RuleCase):
    rule = RULE_UNVALIDATED_PARAM

    def test_fires_on_historical_unvalidated_host(self) -> None:
        hits = self.assert_fires(_workflow(_stage(_OLLAMA_PROBE), params=_OLLAMA_PARAMS))
        self.assertIn("'{ollama_host}'", hits[0].message)
        self.assertIn("curl -sS", hits[0].message)

    def test_double_quotes_do_not_count_as_validation(self) -> None:
        # qwen-job-type.yaml write-handler at 6474c76e: quoted, still injectable.
        desc = 'Commit:\n\n  git commit -m "feat(worker): add {job_type} demo handler"\n'
        self.assert_fires(_workflow(_stage(desc), params='job_type: "qwen_patch"'))

    def test_param_rules_entry_validates(self) -> None:
        self.assert_silent(_workflow(_stage(_OLLAMA_PROBE), params=_OLLAMA_PARAMS, rules=_OLLAMA_RULE))

    def test_check_params_in_same_stage_validates(self) -> None:
        self.assert_silent(_workflow(_stage(_CHECK_PARAMS + _OLLAMA_PROBE), params=_OLLAMA_PARAMS))

    def test_check_params_in_ancestor_stage_validates(self) -> None:
        yaml_text = _workflow(
            _stage(_CHECK_PARAMS, name="init"),
            _stage("Relay stage.", name="middle", depends_on="[init]"),
            _stage(_OLLAMA_PROBE, name="probe", depends_on="[middle]"),
            params=_OLLAMA_PARAMS,
        )
        self.assert_silent(yaml_text)

    def test_check_params_in_unrelated_stage_does_not_validate(self) -> None:
        yaml_text = _workflow(
            _stage(_CHECK_PARAMS, name="sibling"),
            _stage(_OLLAMA_PROBE, name="probe"),
            params=_OLLAMA_PARAMS,
        )
        hits = self.assert_fires(yaml_text)
        self.assertEqual(hits[0].stage, "probe")

    def test_check_of_another_param_does_not_validate(self) -> None:
        other = _CHECK_PARAMS.replace("ollama_host=", "model_tag=")
        self.assert_fires(_workflow(_stage(other + _OLLAMA_PROBE), params=_OLLAMA_PARAMS))

    def test_prose_mention_is_not_shell(self) -> None:
        desc = "Probe {ollama_host} and record whether it answers.\n\nReport `{ollama_host}` as down.\n"
        self.assert_silent(_workflow(_stage(desc), params=_OLLAMA_PARAMS))

    def test_engine_guarded_placeholders_are_exempt(self) -> None:
        desc = "Run:\n\n  ls {workspace}/outputs {work_dir}\n"
        self.assert_silent(_workflow(_stage(desc), params='work_dir: "out"'))

    def test_fragment_stage_judged_against_importer_rules(self) -> None:
        """A shared fragment's params are the importer's -- judge them there."""
        fragment = (
            "fragment: true\nstages:\n"
            + _stage("Read the PR:\n\n  ./bin/github pr view --pr {pr_number}\n", name="fetch")
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            frag = Path(tmp_dir) / "frag.yaml"
            frag.write_text(fragment, encoding="utf-8")
            include = f'include:\n  - path: {frag}\n    prefix: ""\n'
            own = _stage("Prepare.", name="prep")
            unruled = _lint_text(_workflow(own, params='pr_number: ""', tail=include), tmp_dir)
            ruled = _lint_text(
                _workflow(own, params='pr_number: ""', rules="pr_number: '[1-9][0-9]*'", tail=include),
                tmp_dir,
            )
            standalone = lint_workflow(frag)
        self.assertTrue(unruled.valid, msg=unruled.errors)
        self.assertEqual([w.stage for w in _hits(unruled, self.rule)], ["fetch"])
        self.assertEqual(_hits(ruled, self.rule), [])
        self.assertEqual(_hits(standalone, self.rule), [], msg="fragment declares no params itself")

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_workflow(_stage(_OLLAMA_PROBE), params=_OLLAMA_PARAMS))


# ---------------------------------------------------------------------------
# shell-unquoted-fan-out-key
# ---------------------------------------------------------------------------


def _fan_out_workflow(command: str) -> str:
    """coverage-uplift.yaml reuse-sweep shape at 04913a0f: fan-out over domains."""
    return _workflow(
        _stage("List domains.", name="gather", extra="    writes_to:\n      - domains.json\n"),
        _stage(
            f"Sweep one domain:\n\n  {command}\n",
            name="reuse-sweep",
            depends_on="[gather]",
            extra=(
                "    reads_from: [gather]\n"
                "    fan_out:\n      source: gather\n      field: domains\n      key: domain\n"
            ),
        ),
    )


class TestUnquotedFanOutKey(_RuleCase):
    rule = RULE_UNQUOTED_FAN_OUT_KEY

    _HISTORICAL = 'grep -rn "^def make_" tests/{domain}/'

    def test_fires_on_historical_unquoted_key(self) -> None:
        hits = self.assert_fires(_fan_out_workflow(self._HISTORICAL))
        self.assertIn("'{domain}'", hits[0].message)

    def test_quoted_key_is_silent(self) -> None:
        self.assert_silent(_fan_out_workflow('grep -rn "^def make_" "tests/{domain}/"'))

    def test_key_inside_command_substitution_in_quotes_is_quoted(self) -> None:
        self.assert_silent(_fan_out_workflow('echo "$(ls "tests/{domain}")"'))

    def test_key_in_prose_is_silent(self) -> None:
        self.assert_silent(_fan_out_workflow("Record findings for {domain} only."))

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_fan_out_workflow(self._HISTORICAL))


# ---------------------------------------------------------------------------
# shell-unbound-variable
# ---------------------------------------------------------------------------

# shared/pr-thread-resolve.yaml resolve-threads at 1e0ac137 (PR #400), found
# by Copilot on PR #404: THREAD_ID is expanded but never bound.
_UNBOUND = """
    Post the reply:

      GITHUB_TOKEN= gh api graphql -f query='
      mutation($threadId:ID!,$body:String!){
        addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$threadId, body:$body}){ comment{ id } }
      }' -F threadId="$THREAD_ID" -f body="$BODY"

    Build the body from the plan file:

      BODY=$(jq -r '.reply' "{workspace}/outputs/plan.json")
"""


class TestUnboundVariable(_RuleCase):
    rule = RULE_UNBOUND_VARIABLE

    def test_fires_on_historical_unbound_thread_id(self) -> None:
        hits = self.assert_fires(_workflow(_stage(_UNBOUND)))
        self.assertIn("$THREAD_ID", hits[0].message)

    def test_assignment_binds(self) -> None:
        bound = _UNBOUND + "\n  THREAD_ID=$(jq -r '.thread_id' \"{workspace}/outputs/plan.json\")\n"
        self.assert_silent(_workflow(_stage(bound)))

    def test_assignment_behind_a_prose_label_binds(self) -> None:
        # review-and-fix.yaml merge-fix-worktrees: `Bash tool: F=...` binds F.
        desc = 'Bash tool: F="{workspace}/outputs/x.json"\n           BRANCH="$(jq -er \'.branch\' "$F")"\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_for_and_read_bind(self) -> None:
        desc = 'Loop:\n\n  jq -r ".[]" f.json | while read -r ITEM; do echo "$ITEM"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_single_quoted_default_and_environment_are_silent(self) -> None:
        desc = (
            "Run:\n\n"
            "  jq -n '$FOO' --arg FOO x\n"
            '  echo "${UDID:-none}" "${CREDS_FILE:+set}" "$HOME" "$GITHUB_TOKEN"\n'
        )
        self.assert_silent(_workflow(_stage(desc)))

    def test_prose_mention_is_silent(self) -> None:
        self.assert_silent(_workflow(_stage("Compare the result against $THREAD_ID from the plan.")))

    def test_assignment_in_another_stage_does_not_bind(self) -> None:
        yaml_text = _workflow(
            _stage("Bind it:\n\n  THREAD_ID=$(jq -r .id f.json)\n", name="a"),
            _stage('Use it:\n\n  ./bin/github threads reply --thread "$THREAD_ID"\n', name="b", depends_on="[a]"),
        )
        self.assertEqual([w.stage for w in self.assert_fires(yaml_text)], ["b"])

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_workflow(_stage(_UNBOUND)))


# ---------------------------------------------------------------------------
# python-not-isolated
# ---------------------------------------------------------------------------

# qwen-local-handler.yaml verify stage at 6474c76e (PR #391 round 0).
_BARE_PYTHON = """
    Confirm the import resolves to this worktree:

      python3 -c "import worker; print(worker.__file__)"
"""


class TestPythonNotIsolated(_RuleCase):
    rule = RULE_PYTHON_NOT_ISOLATED

    def test_fires_on_historical_bare_interpreter(self) -> None:
        hits = self.assert_fires(_workflow(_stage(_BARE_PYTHON)))
        self.assertIn("lacks -I", hits[0].message)

    def test_fires_on_script_and_venv_interpreter(self) -> None:
        for command in ("python3 workflows/code/scripts/detect_facades.py --root src",
                        ".venv/bin/python tests/fixtures/build.py",
                        "python3 -S -c 'print(1)'"):
            with self.subTest(command=command):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_isolated_forms_are_silent(self) -> None:
        for command in ("python3 -I -S -c 'print(1)'", "python3 -IS -c 'print(1)'",
                        "python3 -I -m json.tool f.json", ".venv/bin/python -I -m pip install x",
                        "python3 -E -c 'print(1)'"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_explicit_pythonpath_is_exempt(self) -> None:
        desc = 'Run:\n\n  PYTHONPATH="$PWD/src" python3 -m unittest tests.workflow_tests -v\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_prose_is_silent(self) -> None:
        self.assert_silent(_workflow(_stage("Run:\n\n  python3 is required for this step\n")))

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_workflow(_stage(_BARE_PYTHON)))


# ---------------------------------------------------------------------------
# validate-stage-writes-output
# ---------------------------------------------------------------------------

# qwen-local-handler.yaml verify stage at e4a37006 (PR #391): kind validate,
# so this object was replaced by the generic findings array.
_VERIFY = """
    Prove the stack works end to end.

    Write {workspace}/validation/verify.json:
      {
        "verified": true|false,
        "detail": "..."
      }
"""


class TestValidateStageWritesOutput(_RuleCase):
    rule = RULE_VALIDATE_WRITES_OUTPUT

    def test_fires_on_historical_validate_stage(self) -> None:
        hits = self.assert_fires(_workflow(_stage(_VERIFY, kind="validate")))
        self.assertIn("validation/verify.json", hits[0].message)

    def test_execute_stage_is_silent(self) -> None:
        self.assert_silent(_workflow(_stage(_VERIFY, kind="execute")))

    def test_validate_stage_without_write_instruction_is_silent(self) -> None:
        self.assert_silent(_workflow(_stage("Check the outputs agree.", kind="validate")))

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_workflow(_stage(_VERIFY, kind="validate")))


# ---------------------------------------------------------------------------
# shell-guard-refused
# ---------------------------------------------------------------------------

# qwen-admin.yaml health stage at f00a50d5 (PR #391 round 7): the heredoc
# guard that a value carrying the delimiter could close early.
_HEREDOC = """
    Get the value off the command line:

      cat > "$TMPDIR/qwen-admin-host" <<'RAW'
      {ollama_host}
      RAW
"""
# review-fix-threads.yaml verify-fixes, on main today.
_LOOP = "Run twice:\n\n  for pass in 1 2; do make test; done\n"


class TestGuardRefused(_RuleCase):
    rule = RULE_GUARD_REFUSED

    def test_fires_on_historical_heredoc(self) -> None:
        hits = self.assert_fires(_workflow(_stage(_HEREDOC), params=_OLLAMA_PARAMS, rules=_OLLAMA_RULE))
        self.assertIn("heredoc", hits[0].message)

    def test_fires_on_shell_loops(self) -> None:
        for desc in (_LOOP, "Drain:\n\n  while test -s q.txt; do sleep 1; done\n"):
            with self.subTest(desc=desc):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_here_string_and_prose_are_silent(self) -> None:
        for desc in (
            "Run:\n\n  jq -r . <<< '{}'\n",
            "NEITHER IS A HEREDOC. The earlier `<<'RAW'` form was broken.\n",
            "The loop reads a file: zsh does not word-split `for R in $ROOTS`.\n",
            'Run:\n\n  echo "use <<EOF in a script, not here"\n',
        ):
            with self.subTest(desc=desc):
                self.assert_silent(_workflow(_stage(desc)))

    def test_python_for_loop_is_not_shell(self) -> None:
        desc = "Inline:\n\n  python3 -I -S -c \"\n  for parser in PARSERS:\n      print(parser)\n  \"\n"
        self.assert_silent(_workflow(_stage(desc)))

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_workflow(_stage(_LOOP)))


# ---------------------------------------------------------------------------
# Shell-text extraction and serialisation
# ---------------------------------------------------------------------------


class TestExtractShellSegments(unittest.TestCase):
    def _texts(self, description: str) -> list[str]:
        return [s.text for s in extract_shell_segments(description)]

    def test_command_lines_spans_and_fences(self) -> None:
        desc = (
            "Intro prose mentioning gh in the middle.\n"
            "  ./bin/github pr view --pr 1\n"
            "Then run `git status --short` and read `outputs/x.json`.\n"
            "```bash\nmake test\n```\n"
            "```json\n{\"a\": 1}\n```\n"
        )
        texts = self._texts(desc)
        self.assertIn("./bin/github pr view --pr 1", texts)
        self.assertIn("git status --short", texts)
        self.assertIn("make test", texts)
        self.assertNotIn("outputs/x.json", texts)
        self.assertFalse(any('"a"' in t for t in texts), msg="json fence is not shell")

    def test_continuation_and_open_quote_pull_lines_in(self) -> None:
        desc = "  HOST=$(./bin/workflow check-params m.json \\\n    --print ollama_host) || exit 1\n"
        self.assertEqual(len(self._texts(desc)), 1)
        self.assertIn("--print ollama_host", self._texts(desc)[0])

    def test_weak_words_need_shell_context(self) -> None:
        self.assertEqual(self._texts("  make sure the gate runs\n  test coverage matters\n"), [])
        self.assertEqual(self._texts("  make -C src lint\n"), ["make -C src lint"])

    def test_loop_head_needs_do_on_the_line(self) -> None:
        # receipts-domain-build.yaml: Python's `for parser in PARSERS:` was
        # read as shell before this; so was prose quoting `for R in $ROOTS`.
        self.assertEqual(self._texts("  for parser in PARSERS:\n"), [])
        self.assertEqual(self._texts("Note `for R in $ROOTS` splits.\n"), [])
        self.assertEqual(self._texts("  for p in a b; do echo $p; done\n"), ["for p in a b; do echo $p; done"])

    def test_prose_line_closing_a_paren_is_not_shell(self) -> None:
        self.assertEqual(self._texts("  git add -A) and run /open-pr with a title\n"), [])

    def test_quote_context_handles_nested_substitution(self) -> None:
        text = 'X="$(jq -r \'.a\' "$F")" {k}'
        ctx = quote_context(text)
        self.assertEqual(ctx[text.index(".a")], "'")
        self.assertEqual(ctx[text.index("{k}")], "")
        self.assertEqual(ctx[text.index("$F")], '"')


class TestRuleSerialisation(unittest.TestCase):
    def test_rule_id_is_serialised(self) -> None:
        result = _lint(_workflow(_stage(_BARE_PYTHON)))
        warnings = cast(list[dict[str, str]], result.as_dict()["warnings"])
        self.assertEqual([w["rule"] for w in warnings], [RULE_PYTHON_NOT_ISOLATED])

    def test_unnamed_warning_serialises_empty_rule(self) -> None:
        w = LintWarning(stage="s", field="f", message="m")
        self.assertEqual(w.rule, "")


if __name__ == "__main__":
    unittest.main()
