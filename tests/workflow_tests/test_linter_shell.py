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

import json
import tempfile
import textwrap
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import cast

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
from workflow.shell_text import (
    extract_shell_segments,
    quote_context,
)

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

    def assert_fires(
        self, yaml_text: str, *, count: int = 1, field: str = "description"
    ) -> list[LintWarning]:
        result = _lint(yaml_text)
        hits = _hits(result, self.rule)
        self.assertEqual(len(hits), count, msg=[w.message for w in result.warnings])
        for w in hits:
            self.assertEqual(w.field, field)
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

    def test_check_params_as_argument_to_another_command_does_not_validate(self) -> None:
        # A token merely ENDING in "check-params" that is an argument to some
        # other command (here, echo) is not a real check-params invocation --
        # no check-params process ever ran, so the later {ollama_host} use
        # must still be flagged.
        desc = (
            "  echo check-params --check 'ollama_host=https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?/?'\n"
            + _OLLAMA_PROBE
        )
        hits = self.assert_fires(_workflow(_stage(desc), params=_OLLAMA_PARAMS))
        self.assertIn("'{ollama_host}'", hits[0].message)

    def test_check_params_run_by_another_program_does_not_validate(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6m6V99: any path-qualified program
        # word used to count as the workflow CLI, so an arbitrary executable
        # given a check-params operand suppressed the rule though no
        # check-params ever ran. A bare `check-params` names no executable.
        for program in ("/tmp/anything", "./bin/evil", "check-params"):  # nosec B108 - fixture text, never opened
            with self.subTest(program=program):
                operands = "" if program == "check-params" else " check-params"
                desc = _fenced(f"{program}{operands} m.json --check host=trusted\n\necho {{host}}")
                hits = self.assert_fires(_workflow(_stage(desc), params='host: "example.com"'))
                self.assertIn("'{host}'", hits[0].message)

    def test_workflow_cli_by_any_path_validates(self) -> None:
        # Fenced so the parser, not the prose heuristic that picks shell
        # lines out of a description, decides what the call runs.
        for program in ("./bin/workflow", "/opt/repo/bin/workflow", "workflow"):
            with self.subTest(program=program):
                desc = _fenced(f"{program} check-params m.json --check host=trusted\n\necho {{host}}")
                self.assert_silent(_workflow(_stage(desc), params='host: "example.com"'))

    def test_placeholder_in_shell_comment_still_fires(self) -> None:
        # Copilot "Previously missed" on PR #437 asked for comments to be
        # skipped. Not for this rule: the value is substituted into the text
        # before the shell reads it, so a newline in it ends the comment and
        # the rest runs -- the break-out param_guard.py documents for a
        # quoted heredoc. shell-unbound-variable does skip comments.
        desc = "Run:\n\n  echo ok # document {host} and $UNBOUND\n"
        result = _lint(_workflow(_stage(desc), params='host: "example.com"'))
        self.assertEqual(len(_hits(result, self.rule)), 1, msg=[w.message for w in result.warnings])
        self.assertEqual(_hits(result, RULE_UNBOUND_VARIABLE), [])

    def test_check_params_after_the_use_does_not_validate_it(self) -> None:
        # PR #433 review: check-params validation must respect ordering. A
        # {ollama_host} used BEFORE a same-stage check-params --check call has
        # already reached shell by the time the check runs, so it must still
        # be flagged -- the check protects only uses that come after it.
        desc = _OLLAMA_PROBE + _CHECK_PARAMS
        hits = self.assert_fires(_workflow(_stage(desc), params=_OLLAMA_PARAMS))
        self.assertIn("'{ollama_host}'", hits[0].message)

    def test_check_params_after_the_use_in_a_later_fence_does_not_validate_it(self) -> None:
        # PR #433 review r4118013911: extract_shell_segments used to
        # concatenate all fence segments before all line segments, so a line
        # segment's index never reflected its real position relative to a
        # fence segment -- a use extracted as a LINE segment sorted after a
        # check-params call extracted as a FENCE segment even when the use
        # appears first in the real source. Exact triage repro shape: a plain
        # {host} use, then a fenced check-params call for the same param.
        desc = (
            "Probe {host}:\n\n"
            "  echo {host}\n\n"
            "```bash\n"
            "./bin/workflow check-params m.json --check host=trusted\n"
            "```\n"
        )
        hits = self.assert_fires(_workflow(_stage(desc), params='host: "example.com"'))
        self.assertIn("'{host}'", hits[0].message)

    def test_check_params_in_earlier_fence_validates_a_later_line_use(self) -> None:
        # Happy-path sibling of the above: when the fenced check-params call
        # genuinely comes FIRST in the real source and the plain-line use
        # comes after it, the use is validated and the rule stays silent --
        # confirms the fix orders by real offset, not just "line beats fence".
        desc = (
            "```bash\n"
            "./bin/workflow check-params m.json --check host=trusted\n"
            "```\n\n"
            "Probe {host}:\n\n"
            "  echo {host}\n"
        )
        self.assert_silent(_workflow(_stage(desc), params='host: "example.com"'))

    def test_unquoted_heredoc_body_placeholder_fires(self) -> None:
        # Unlinked triage finding shell_text.py:305, end to end: before the
        # heredoc-body fix, _line_segments emitted only the "cat <<EOF"
        # opener line, so {host} substituted into the body never appeared in
        # any segment's text and this rule never saw it -- a real
        # security-relevant gap, since the body genuinely shell-expands at
        # runtime.
        desc = 'Write the file:\n\n  cat > "$TMPDIR/notes.txt" <<EOF\n  {host}\n  EOF\n'
        hits = self.assert_fires(_workflow(_stage(desc), params='host: "example.com"'))
        self.assertIn("'{host}'", hits[0].message)

    def test_quoted_heredoc_body_placeholder_does_not_validate(self) -> None:
        # Happy-path sibling: a QUOTED delimiter's body is inert to the shell
        # (no expansion happens at all), so a {host} placeholder there is not
        # a real unvalidated-param exposure and must stay silent.
        desc = "Write the file:\n\n  cat > \"$TMPDIR/notes.txt\" <<'EOF'\n  {host}\n  EOF\n"
        self.assert_silent(_workflow(_stage(desc), params='host: "example.com"'))

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

    def test_later_commands_check_flag_does_not_validate_earlier_call(self) -> None:
        # PR #433 review: _check_param_names_at scanned to the end of the
        # segment with no stop at a command separator, so a later unrelated
        # command's --check flag (here, after echo, joined by ';') could
        # donate a spec to an earlier, unrelated check-params invocation.
        desc = (
            "  ./bin/workflow check-params \"{workspace}/manifest.json\"; "
            "echo --check 'ollama_host=https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?/?'\n"
        ) + _OLLAMA_PROBE
        hits = self.assert_fires(_workflow(_stage(desc), params=_OLLAMA_PARAMS))
        self.assertIn("'{ollama_host}'", hits[0].message)

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

    # ------------------------------------------------------------------
    # Grammar parity tests (shared PLACEHOLDER_RE from placeholders.py)
    # ------------------------------------------------------------------

    def test_placeholder_in_json_wrapper_fires(self) -> None:
        # Missed-warning case: the old regex had a (?!\}) closing lookahead
        # that skipped {name} when it was immediately followed by a }, as in
        # '{"value": {name}}'. The engine substitutes this correctly, so the
        # linter must flag it too.
        desc = "Run:\n\n  curl -d '{\"value\": {name}}' http://example.com\n"
        hits = self.assert_fires(_workflow(_stage(desc), params='name: "default"'))
        self.assertIn("'{name}'", hits[0].message)

    def test_shell_expansion_not_flagged_as_placeholder(self) -> None:
        # False-warning case: the old regex lacked the $ lookbehind that
        # placeholders.py has, so ${name} (a shell variable expansion) was
        # wrongly treated as a workflow placeholder. It must not fire.
        desc = "Run:\n\n  echo ${name}\n"
        self.assert_silent(_workflow(_stage(desc), params='name: "default"'))

    def test_plain_placeholder_still_fires(self) -> None:
        # Happy path: the shared grammar still catches plain {name}.
        desc = "Run:\n\n  echo {name}\n"
        hits = self.assert_fires(_workflow(_stage(desc), params='name: "default"'))
        self.assertIn("'{name}'", hits[0].message)

    def test_escaped_placeholder_does_not_fire(self) -> None:
        # Happy path: {{name}} must not be treated as a placeholder.
        desc = "Run:\n\n  echo '{{name}}'\n"
        self.assert_silent(_workflow(_stage(desc), params='name: "default"'))


class TestIncludedFragmentsAreLinted(unittest.TestCase):
    """PR #433 review: an included fragment's context-free rules must run too.

    check_shell_rules skips unbound-variable/fan-out/isolation/guard-refused/
    validate-writes for stages inlined from a fragment, on purpose: those rules
    need the fragment's OWN params, not the importer's. Before this fix nothing
    ever ran them on the fragment's side either -- lint_workflow only checked
    that the include file exists, never linted its content -- so those rules
    silently never ran on an included stage at all.
    """

    def test_parent_lint_surfaces_fragment_context_free_findings(self) -> None:
        fragment = (
            "fragment: true\nstages:\n"
            + _stage(_BARE_PYTHON, name="probe")
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            frag = Path(tmp_dir) / "frag.yaml"
            frag.write_text(fragment, encoding="utf-8")
            include = f'include:\n  - path: {frag}\n    prefix: ""\n'
            own = _stage("Prepare.", name="prep")
            result = _lint_text(_workflow(own, tail=include), tmp_dir)
        hits = _hits(result, RULE_PYTHON_NOT_ISOLATED)
        self.assertEqual(len(hits), 1, msg=[w.message for w in result.warnings])
        self.assertIn("frag.yaml:probe", hits[0].stage)

    def test_parent_lint_is_silent_when_fragment_has_no_findings(self) -> None:
        # Sad-path companion: a fragment with no context-free violation must
        # not manufacture a finding just because it is now linted.
        fragment = (
            "fragment: true\nstages:\n"
            + _stage("Run:\n\n  python3 -I -S -c 'print(1)'\n", name="probe")
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            frag = Path(tmp_dir) / "frag.yaml"
            frag.write_text(fragment, encoding="utf-8")
            include = f'include:\n  - path: {frag}\n    prefix: ""\n'
            own = _stage("Prepare.", name="prep")
            result = _lint_text(_workflow(own, tail=include), tmp_dir)
        self.assertEqual(_hits(result, RULE_PYTHON_NOT_ISOLATED), [])
        self.assertTrue(result.valid, msg=result.errors)


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

    def test_key_after_apostrophe_in_comment_fires(self) -> None:
        # An apostrophe in a comment opens no quote; read raw, it marked the
        # rest of the segment single-quoted and hid the unquoted key.
        self.assert_fires(_worker_queue_workflow("echo ok # don't\nrm {domain}"), field="fan_out.script")

    def test_key_in_comment_is_silent(self) -> None:
        # Agent fan-out keys are held to [A-Za-z0-9][A-Za-z0-9._-]* by the
        # orchestrator (SKILL.md SAFE_KEY_VALUE): no newline can end a comment.
        self.assert_silent(_fan_out_workflow("echo ok # sweep {domain}"))

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_fan_out_workflow(self._HISTORICAL))


def _worker_queue_workflow(
    script: str, *, description: str = "Enqueued once per domain.", stage_script: str = ""
) -> str:
    """worker-queue-fanout.yaml check-domain shape: a worker_queue fan-out over domains."""
    extra = (
        "    reads_from: [gather]\n"
        "    fan_out:\n      source: gather\n      field: domains\n      key: domain\n"
        f"      mode: worker_queue\n      script: {json.dumps(script)}\n"
    )
    if stage_script:
        extra += f"    executor: worker_queue\n    script: {json.dumps(stage_script)}\n"
    return _workflow(
        _stage("List domains.", name="gather", extra="    writes_to:\n      - domains.json\n"),
        _stage(description, name="check-domain", depends_on="[gather]", extra=extra),
    )


class TestUnquotedFanOutKeyWorkerQueue(unittest.TestCase):
    """PR #437 thread PRRT_kwDOQr1kjM6m6V-G: a worker_queue fan-out runs its script, not its prose."""

    def _hits(self, yaml_text: str) -> list[LintWarning]:
        result = _lint(yaml_text)
        self.assertTrue(result.valid, msg=result.errors)
        return _hits(result, RULE_UNQUOTED_FAN_OUT_KEY)

    def test_unquoted_key_in_fan_out_script_fires(self) -> None:
        hits = self._hits(_worker_queue_workflow("rm {domain}"))
        self.assertEqual([w.field for w in hits], ["fan_out.script"])
        self.assertIn("'{domain}'", hits[0].message)
        self.assertIn("rm {domain}", hits[0].message)

    def test_unquoted_key_in_enqueued_stage_script_fires(self) -> None:
        # WorkerQueueDispatcher enqueues the stage-level script as the job's payload.
        hits = self._hits(_worker_queue_workflow('rm "{domain}"', stage_script="ls {domain}/"))
        self.assertEqual([w.field for w in hits], ["script"])

    def test_quoted_key_in_script_is_silent(self) -> None:
        self.assertEqual(self._hits(_worker_queue_workflow('rm "{domain}"', stage_script="ls '{domain}'/")), [])

    def test_description_is_not_checked_in_worker_queue_mode(self) -> None:
        # Neither prose nor a shell-shaped line in the description reaches a
        # shell or an agent in this mode.
        for description in ("Remove the {domain} directory.", "Remove it:\n\n  rm -r {domain}\n"):
            with self.subTest(description=description):
                self.assertEqual(self._hits(_worker_queue_workflow('rm "{domain}"', description=description)), [])

    def test_has_teeth(self) -> None:
        yaml_text = _worker_queue_workflow("rm {domain}")
        self.assertTrue(self._hits(yaml_text))
        with mock.patch("workflow.linter_shell._unquoted_fan_out_keys", return_value=[]):
            self.assertEqual(_lint(yaml_text).warnings, [])


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


def _fenced(line: str) -> str:
    """*line* as a fenced bash block; blank lines survive the folded scalar as line breaks."""
    return f"```bash\n\n{line}\n\n```\n"


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

    def test_fires_when_folded_scalar_collapses_fence_marker_onto_first_command(self) -> None:
        # PR #433 review: a YAML folded scalar (`description: >`) collapses a
        # fence's opening marker line and its first command onto one line
        # before shell rules ever see them -- "```bash" + a command becomes
        # one line starting "```bash <command>". _stage() places this
        # fixture in a real folded scalar (no blank lines), so PyYAML does
        # the actual folding; before the fix, _FENCE_RE could not match that
        # line and the whole fenced block -- including this unbound
        # reference -- was silently skipped by every shell rule.
        desc = '```bash echo "$UNBOUND_VAR"\n```\n'
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("$UNBOUND_VAR", hits[0].message)

    def test_fires_when_folded_scalar_collapses_unlabelled_fence_marker(self) -> None:
        # PR #433 review (follow-up): an UNLABELLED fence folded onto one
        # line ("``` echo ...") has no language tag at all, but
        # _FENCE_OPEN_RE's lang-tag group is greedy and still captures the
        # first word of the body ("echo") as if it were one. _fence_is_shell
        # then rejected "echo" (not in _SHELL_FENCE_LANGS) and the whole
        # fenced block -- including this unbound reference -- was silently
        # dropped, the same failure mode as the labelled case above but for
        # a fence with no language tag whatsoever.
        desc = '``` echo "$UNBOUND_VAR"\n```\n'
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("$UNBOUND_VAR", hits[0].message)

    def test_folded_real_language_tag_is_not_misread_as_unlabelled_shell(self) -> None:
        # PR #433 review (this fix): a REAL, non-shell language tag folded
        # onto one line ("```python python3 -c ...") has the exact same
        # shape as the unlabelled-fence case two tests above -- an
        # unrecognised tag with trailing text. Before this fix, both were
        # treated identically: the fence was reclassified as unlabelled
        # shell, its "tag" plus trailing text became the first body line
        # ("python python3 -c ..."), and "python3" (a strong command) made
        # is_command_line() call the whole thing shell. A genuine
        # python-labelled code block must stay silent, even though its
        # first body word after folding looks like a shell command.
        desc = '```python python3 -c "print($UNBOUND_VAR)"\n```\n'
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

    def test_escaped_dollar_is_silent(self) -> None:
        # Copilot PR #433 r4099834621: echo "\$NAME" is a literal $NAME in
        # POSIX sh, not an expansion -- quote_context alone can't tell that.
        self.assert_silent(_workflow(_stage('Print it literally:\n\n  echo "\\$NAME"\n')))

    def test_unescaped_dollar_after_literal_backslash_still_fires(self) -> None:
        # A doubled backslash is an escaped backslash, so the following $ is a
        # real expansion again -- must not be swallowed by the escape check.
        hits = self.assert_fires(_workflow(_stage('Run:\n\n  echo "\\\\$THREAD_ID"\n')))
        self.assertIn("$THREAD_ID", hits[0].message)

    def test_assignment_in_another_stage_does_not_bind(self) -> None:
        yaml_text = _workflow(
            _stage("Bind it:\n\n  THREAD_ID=$(jq -r .id f.json)\n", name="a"),
            _stage('Use it:\n\n  ./bin/github threads reply --thread "$THREAD_ID"\n', name="b", depends_on="[a]"),
        )
        self.assertEqual([w.stage for w in self.assert_fires(yaml_text)], ["b"])

    def test_quoted_assignment_looking_literal_does_not_bind(self) -> None:
        # PR #433 review: an assignment-shaped literal inside a quoted string is
        # quoted text, not a binding -- FOO is never actually assigned, so a real
        # later $FOO expansion must still fire shell-unbound-variable.
        desc = 'Run:\n\n  echo "example FOO=literal"\n  echo "$FOO"\n'
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("$FOO", hits[0].message)

    def test_unquoted_non_assignment_position_does_not_bind(self) -> None:
        # PR #433 review: NAME=value as an argument to another command (not
        # itself in assignment position) is not a binding -- the shell never
        # runs an assignment there, so a real later $FOO expansion must still
        # fire shell-unbound-variable, even though the token is unquoted.
        desc = 'Run:\n\n  echo FOO=literal\n  echo "$FOO"\n'
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("$FOO", hits[0].message)

    def test_export_prefixed_assignment_binds(self) -> None:
        # export/local/declare are assignment keywords: the word right after
        # them is still a real binding even though it is not the first word
        # of the command.
        for keyword in ("export", "local", "declare"):
            with self.subTest(keyword=keyword):
                desc = f'Run:\n\n  {keyword} FOO=literal\n  echo "$FOO"\n'
                self.assert_silent(_workflow(_stage(desc)))

    def test_second_consecutive_assignment_word_binds(self) -> None:
        # Unlinked triage finding linter_shell.py:384: _is_assignment_position
        # only accepted the first word of a command or a word right after
        # export/local/declare, so a SECOND (or later) consecutive assignment
        # word before a command -- POSIX sh allows any number of them -- was
        # not recognised as a binding. BAR here is preceded by "one", the
        # value half of FOO=one, not by an assignment keyword or a command
        # boundary, so the old logic rejected it outright.
        desc = 'Run:\n\n  FOO=one BAR=two echo "$FOO $BAR"\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_third_consecutive_assignment_word_binds(self) -> None:
        # Sad-path companion at one more level of chaining, to confirm the
        # backward walk recurses rather than only handling exactly two.
        desc = 'Run:\n\n  FOO=one BAR=two BAZ=three echo "$BAZ"\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_value_looking_like_assignment_does_not_falsely_chain(self) -> None:
        # A command word that merely CONTAINS '=' in its first operand, after
        # a real assignment, must not be misread as a second assignment word:
        # only the assignment prefix before a real command's first word
        # matters, and unassigned use after the real command starts must
        # still fire.
        desc = 'Run:\n\n  FOO=one echo "a=b" "$BAR"\n'
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("$BAR", hits[0].message)

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_workflow(_stage(_UNBOUND)))

    def test_expansion_in_shell_comment_is_silent(self) -> None:
        # Copilot "Previously missed" on PR #437: the shell never expands a
        # comment, so a $NAME there is not a use.
        self.assert_silent(_workflow(_stage("Run:\n\n  echo ok # document {host} and $UNBOUND\n")))

    def test_hash_inside_a_word_is_not_a_comment(self) -> None:
        for line in ("echo $FOO#bar", "echo a#b $FOO", 'echo "${#x}" "$FOO"'):
            with self.subTest(line=line):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  {line}\n")))
                self.assertIn("$FOO", hits[0].message)

    def test_apostrophe_in_comment_does_not_quote_later_lines(self) -> None:
        # Read raw, the ' in "don't" opened a single quote that ran to the
        # end of the segment and hid $FOO.
        desc = "```bash\n\necho ok # don't\n\necho $FOO\n\n```\n"
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("$FOO", hits[0].message)

    def test_quoted_heredoc_body_does_not_spuriously_fire_unbound(self) -> None:
        # PR #433 review: a quoted-delimiter heredoc returned from
        # _absorb_heredoc_body without consuming its body lines, so
        # _line_segments revisited the body's `echo "$UNBOUND"` as its own
        # independent shell segment and this rule fired on it -- even though
        # a quoted heredoc body is inert data that never shell-expands.
        desc = "Write the file:\n\n  cat <<'EOF'\n  echo \"$UNBOUND\"\n  EOF\n"
        self.assert_silent(_workflow(_stage(desc)))

    def test_assignment_in_quoted_heredoc_body_does_not_bind(self) -> None:
        # PR #433 review (linter_shell.py:436): _assigned_names scanned the raw
        # description, so a FOO=literal line in a quoted heredoc body -- inert
        # data fed to cat -- counted as a binding and hid the unbound $FOO.
        desc = "Write it:\n\n  cat <<'EOF'\n  FOO=literal\n  EOF\n  echo \"$FOO\"\n"
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("$FOO", hits[0].message)

    def test_assignment_in_heredoc_body_inside_a_fence_does_not_bind(self) -> None:
        # Same class, fenced: the fence keeps the body in the segment text, so
        # only parsing the heredoc as data keeps it out of the bindings. Blank
        # lines survive the folded scalar as single line breaks.
        desc = "```bash\n\ncat <<'EOF'\n\nFOO=literal\n\nEOF\n\necho \"$FOO\"\n\n```\n"
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("$FOO", hits[0].message)

    def test_assignment_after_a_quoted_heredoc_still_binds(self) -> None:
        # Happy path: the same assignment as a real command after the heredoc
        # closes is a binding.
        desc = "Write it:\n\n  cat <<'EOF'\n  literal\n  EOF\n  FOO=literal\n  echo \"$FOO\"\n"
        self.assert_silent(_workflow(_stage(desc)))

    def test_expansion_in_quoted_heredoc_body_inside_a_fence_is_silent(self) -> None:
        # A quoted body never expands, fenced or not.
        desc = "```bash\n\ncat <<'EOF'\n\necho \"$NOT_EXPANDED\"\n\nEOF\n\n```\n"
        self.assert_silent(_workflow(_stage(desc)))

    def test_assignment_binds_after_an_apostrophe_in_prose(self) -> None:
        # Tree-wide sweep: the old whole-description quote scan read a prose
        # apostrophe as an opening quote, so every later assignment looked
        # quoted and bound nothing (qlty-complexity-sweep.yaml $PRE_SWEEP,
        # pr-thread-resolve.yaml $PLAN). Bindings now come from each parsed
        # segment, where prose quoting cannot reach.
        desc = "Don't skip this.\n\n  PRIV=$(mktemp -d)\n  rm -rf \"$PRIV\"\n"
        self.assert_silent(_workflow(_stage(desc)))

    def test_read_as_an_argument_does_not_bind(self) -> None:
        # `read` binds only as the program word; `echo read FOO` prints.
        hits = self.assert_fires(_workflow(_stage('Run:\n\n  echo read FOO\n  echo "$FOO"\n')))
        self.assertIn("$FOO", hits[0].message)

    def test_unquoted_heredoc_body_still_fires_unbound(self) -> None:
        # Happy-path sibling: an UNQUOTED delimiter's body is live shell, so a
        # real unbound reference inside it must still fire -- confirms the fix
        # only stops the quoted body from being independently re-scanned, and
        # does not also silence the unquoted case round 5 already covers.
        desc = 'Write the file:\n\n  cat <<EOF\n  echo "$UNBOUND"\n  EOF\n'
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("$UNBOUND", hits[0].message)

    # PR #433 review (linter_shell.py _assigned_names): parse_shell flattened
    # commands from command substitutions into script.commands, so an
    # assignment made in a child shell counted as a binding for the stage's
    # shell, which never sees it.

    def test_assignment_in_child_shell_does_not_bind_the_parent(self) -> None:
        cases = {
            "command substitution": 'echo "$(FOO=bar true)"; echo "$FOO"',
            "subshell group": '( FOO=1 ); echo "$FOO"',
            "backticks": 'echo `FOO=1 true`; echo "$FOO"',
            "process substitution": 'diff <(FOO=1 sort a) b; echo "$FOO"',
            "loop variable in a group": '( for FOO in a; do :; done ); echo "$FOO"',
            "sibling child shell": '( FOO=1 ); ( echo "$FOO" )',
        }
        for label, line in cases.items():
            with self.subTest(label):
                hits = self.assert_fires(_workflow(_stage(_fenced(line))))
                self.assertIn("$FOO", hits[0].message)

    def test_binding_visible_where_the_shell_sees_it(self) -> None:
        cases = {
            "parent binding inside a child": 'FOO=1; echo "$(echo "$FOO")"',
            "brace group": '{ FOO=1; }; echo "$FOO"',
            "export": 'export FOO=1; echo "$FOO"',
            "binding and use in one child": '( FOO=1; echo "$FOO" )',
            "read and use in one substitution": 'echo "$(read -r FOO; echo "$FOO")"',
            "outer child binding inside an inner one": '( FOO=1; ( echo "$FOO" ) )',
        }
        for label, line in cases.items():
            with self.subTest(label):
                self.assert_silent(_workflow(_stage(_fenced(line))))


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

    def test_fires_on_non_py_suffixed_script_operand(self) -> None:
        # Copilot PR #433 r4099834636: a script path with no .py suffix, or a
        # quoted variable holding the script path, still starts the
        # interpreter with the ambient PYTHONPATH.
        for command in ('python3 tools/run_checks', 'python3 "$SCRIPT"'):
            with self.subTest(command=command):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_pythonpath_assignment_in_a_prior_command_does_not_exempt(self) -> None:
        # PR #433 review r4118063072 (and unlinked triage finding
        # linter_shell.py:489, same root cause): the exemption scanned the
        # previous 3 tokens for any PYTHONPATH= prefix with no regard for
        # command boundaries, so an assignment belonging to a PRIOR, unrelated
        # command -- separated here by ';' -- wrongly exempted the python
        # invocation that follows it. The interpreter still inherits the
        # ambient PYTHONPATH and is not isolated.
        desc = 'Run:\n\n  echo PYTHONPATH=/tmp; python3 tools/run_checks\n'
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("lacks -I", hits[0].message)

    def test_pythonpath_assignment_in_the_same_command_still_exempts(self) -> None:
        # Happy-path sibling: a real same-command PYTHONPATH= prefix -- no
        # separator between it and the python invocation -- must keep
        # exempting the call, same as test_explicit_pythonpath_is_exempt.
        desc = 'Run:\n\n  echo setup; PYTHONPATH="$PWD/src" python3 tools/run_checks\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_fires_on_versioned_interpreter(self) -> None:
        # Unlinked triage finding shell_text.py:209: _is_command_word only
        # recognised the exact names "python"/"python3" or a path ending in
        # "/python3", so a versioned interpreter line was never extracted as
        # shell at all -- this rule never even saw it to flag it.
        for command in ("python3.11 tools/run_checks", "/usr/bin/python3.12 -c 'print(1)'"):
            with self.subTest(command=command):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_isolated_versioned_interpreter_is_silent(self) -> None:
        # Happy-path sibling: a versioned interpreter that IS isolated must
        # not fire, same as the unversioned forms in test_isolated_forms_are_silent.
        self.assert_silent(_workflow(_stage("Run:\n\n  python3.11 -I -S -c 'print(1)'\n")))

    def test_fires_on_bare_interpreter_with_no_operands(self) -> None:
        # PR #433 review r4118063056: _is_invocation([]) returned False, so a
        # command line consisting of just "python3"/"python" -- with no
        # operands at all -- was never reported as unisolated, even though
        # extract_shell_segments has already decided this is a real command
        # line (not prose) and it still starts the interpreter with the
        # ambient PYTHONPATH.
        for command in ("python3", "python"):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))
                self.assertIn("lacks -I", hits[0].message)

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_workflow(_stage(_BARE_PYTHON)))

    def test_isolated_form_after_value_taking_flag_is_silent(self) -> None:
        # Copilot PRRT_kwDOQr1kjM6mhoot (PR #433): the flag scan stopped at
        # the first arg not starting with "-", so "-X utf8" (a value-taking
        # flag whose value is the NEXT token) was misread as the end of the
        # flag list and "-I" right after it was never reached.
        for command in (
            "python3 -X utf8 -I -c 'print(1)'",
            "python3 -W error -I -c 'print(1)'",
            "python3 -X utf8 -W error -I -c 'print(1)'",
        ):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_interpreter_as_an_argument_is_silent(self) -> None:
        # PR #433 review (linter_shell.py:570): every token matching the
        # interpreter name was treated as an invocation, so `echo python3 -c`
        # warned although echo runs, not python3.
        for command in ("echo python3 -c 'print(1)'", "test -x .venv/bin/python",
                        "grep -n python3 setup.cfg"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_interpreter_in_command_position_after_a_separator_fires(self) -> None:
        # Happy path for the same fix: the interpreter is still found wherever
        # it IS the program -- after a separator, a reserved word, a wrapper,
        # or inside a command substitution.
        for command in ("echo setup; python3 -c 'print(1)'",
                        "if python3 -c 'import x'; then echo ok; fi",
                        "cd src && env FOO=1 python3 -c 'print(1)'",
                        "X=$(python3 -c 'print(1)'); echo \"$X\""):
            with self.subTest(command=command):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_bare_interpreter_before_a_separator_fires(self) -> None:
        # PR #433 review (linter_shell.py:574): the operand list ran past
        # the separator, so `;`/`&&` became the first operand and the bare
        # interpreter was taken for prose.
        for command in ("python3 ; echo done", "python3 && echo done"):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))
                self.assertIn("lacks -I", hits[0].message)

    def test_isolated_interpreter_before_a_separator_is_silent(self) -> None:
        # Happy path: bounding the operands must not drop a later command's
        # flags onto the interpreter or lose its own.
        for command in ("python3 -I ; echo done", "python3 -I -c 'print(1)' && echo -X"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_env_pythonpath_exempts_only_its_own_command(self) -> None:
        self.assert_silent(_workflow(_stage("Run:\n\n  cd src && env PYTHONPATH=. python3 -m foo\n")))
        self.assert_fires(_workflow(_stage("Run:\n\n  cd src && env PYTHONPATH=. true; python3 -m foo\n")))

    def test_fires_in_folded_unlabelled_fence_opening_with_python(self) -> None:
        # PR #433 review (shell_text.py:317): "``` python -c ..." -- an
        # unlabelled fence folded onto its first command -- was read as a
        # fence tagged `python` and dropped, so the unisolated call was never
        # linted. The space after the marker marks the word as body text.
        hits = self.assert_fires(_workflow(_stage("``` python -c 'print(1)'\n```\n")))
        self.assertIn("lacks -I", hits[0].message)

    def test_folded_python_tagged_fence_is_still_not_shell(self) -> None:
        # Happy path: a glued tag ("```python") is a language tag; the
        # fence is Python source, not shell.
        self.assert_silent(_workflow(_stage("```python python3 -c 'print(1)'\n```\n")))

    def test_value_taking_flag_without_isolation_flag_still_fires(self) -> None:
        # Sad-path sibling: consuming -X's value must not itself grant
        # isolation -- a command with -X but no -I/-E still lacks it.
        hits = self.assert_fires(_workflow(_stage("Run:\n\n  python3 -X utf8 -c 'print(1)'\n")))
        self.assertIn("lacks -I", hits[0].message)

    def test_fires_on_bare_relative_script_operand(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6ms2U4: `_is_invocation(["runner"])`
        # was False, so `python3 runner` -- a script with no suffix and no
        # slash -- started the interpreter with the ambient PYTHONPATH
        # unreported. Prose is now kept out by the segment extractor instead.
        for command in ("python3 runner", "python3 runner --verbose"):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))
                self.assertIn("python3 runner", hits[0].message)

    def test_python_is_required_prose_is_silent(self) -> None:
        # Happy path for the same thread: with the operand heuristic gone,
        # "python3 is required" stays silent because it is never a segment.
        self.assert_silent(_workflow(_stage("Setup:\n\n  python3 is required\n")))

    def test_fires_on_wrapper_led_interpreter_line(self) -> None:
        # PR #437 "Previously missed" (shell_text.py is_command_line): a line
        # led by a wrapper parse_shell sees through produced no segment, so
        # its unisolated interpreter was never linted.
        for command in ("env FOO=1 python3 -c 'print(1)'", "timeout 5 python3 run.py",
                        "sudo -u me nice -n 5 python3 run.py"):
            with self.subTest(command=command):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_fires_in_folded_unlabelled_fence_opening_with_single_word(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6ms2Wg: "``` python3" -- an unlabelled
        # fence whose first line is the bare interpreter -- was read as a fence
        # tagged `python3` and dropped.
        self.assert_fires(_workflow(_stage("Run:\n\n  ``` python3\n  ```\n")))


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

    def test_fires_on_create_verb_and_non_listed_extension(self) -> None:
        # Copilot PR #433 r4099834597: only Write/Save and five extensions
        # were recognised, so "Create ... result.json" passed silently.
        hits = self.assert_fires(
            _workflow(_stage("Create {workspace}/outputs/result.json with the findings.", kind="validate"))
        )
        self.assertIn("outputs/result.json", hits[0].message)

    def test_fires_on_emit_output_produce_verbs(self) -> None:
        for verb in ("Emit", "Output", "Produce"):
            desc = f"{verb} {{workspace}}/outputs/summary.log now."
            with self.subTest(verb=verb):
                self.assert_fires(_workflow(_stage(desc, kind="validate")))

    def test_fires_on_colon_after_to(self) -> None:
        # An unlinked finding: "Write to: {workspace}/..." never matched
        # because the regex required "to" to be followed directly by
        # whitespace, with no punctuation allowed in between.
        hits = self.assert_fires(
            _workflow(_stage("Write to: {workspace}/outputs/result.json", kind="validate"))
        )
        self.assertIn("outputs/result.json", hits[0].message)

    def test_no_colon_after_to_still_fires(self) -> None:
        # Sad path for the same fix: the plain "to " form (no punctuation)
        # must keep matching after the colon is made optional.
        hits = self.assert_fires(
            _workflow(_stage("Write to {workspace}/outputs/result.json", kind="validate"))
        )
        self.assertIn("outputs/result.json", hits[0].message)

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_workflow(_stage(_VERIFY, kind="validate")))


# ---------------------------------------------------------------------------
# shell-guard-refused
# ---------------------------------------------------------------------------

# qwen-admin.yaml health stage at f00a50d5 (PR #391 round 7), adapted to an
# UNQUOTED delimiter: the guard's own contract (guard-contract.yaml "heredoc
# subst runs" -> block) only refuses this shape because $(...) in the body
# expands before the guard can inspect the result. The original fixture used
# a quoted `<<'RAW'` delimiter, which the guard allows outright ("quoted
# heredoc data" -> allow) -- Copilot PR #433 flagged that mismatch directly.
_HEREDOC = """
    Get the value off the command line:

      cat > "$TMPDIR/qwen-admin-host" <<RAW
      $(echo {ollama_host})
      RAW
"""
# review-fix-threads.yaml verify-fixes, adapted to a mutating body: the guard
# allows a read-only loop outright (guard-contract.yaml "loop variable in a
# read" -> allow), so the original `do make test; done` body -- a false
# positive Copilot PR #433 flagged -- must not fire this rule any more.
_LOOP = "Run twice:\n\n  for pass in 1 2; do rm -rf \"$TMPDIR/scratch-$pass\"; done\n"


class TestGuardRefused(_RuleCase):
    rule = RULE_GUARD_REFUSED

    def test_fires_on_historical_heredoc(self) -> None:
        hits = self.assert_fires(_workflow(_stage(_HEREDOC), params=_OLLAMA_PARAMS, rules=_OLLAMA_RULE))
        self.assertIn("heredoc", hits[0].message)

    def test_fires_on_shell_loops(self) -> None:
        for desc in (_LOOP, "Drain:\n\n  while test -s q.txt; do mv q.txt \"$TMPDIR/done\"; done\n"):
            with self.subTest(desc=desc):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_quoted_mutating_command_name_as_argument_is_silent(self) -> None:
        # Unlinked triage finding linter_shell.py:631: _loop_body_is_mutating
        # treated ANY token equal to a mutating command name as an executed
        # command regardless of shell command position. shlex strips quotes
        # during tokenisation, so a quoted argument like "rm" passed to echo
        # is indistinguishable at the token level from a bare rm invocation --
        # but it is not one: echo just prints the word "rm", the loop reads
        # only.
        desc = 'Report:\n\n  for f in src/*.py; do echo "rm" "$f"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_real_mutating_command_after_argument_use_still_fires(self) -> None:
        # Sad-path sibling: a genuine mutating invocation in COMMAND position
        # later in the same loop body must still fire, so the command-position
        # check does not accidentally suppress every mention of the word.
        desc = 'Report:\n\n  for f in src/*.py; do echo "rm"; rm -f "$f"; done\n'
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_fires_on_path_qualified_mutating_command(self) -> None:
        # PR #433 review (linter_shell.py:844): mutators were matched by exact
        # bare token, while the guard resolves the basename -- `/bin/rm` in a
        # loop was refused by the guard and passed here.
        for command in ('for p in files; do /bin/rm -f "$p"; done',
                        'for p in files; do "$HOME/bin/../../bin/mv" "$p" x; done'):
            with self.subTest(command=command):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))[0].message)

    def test_path_qualified_read_only_command_is_silent(self) -> None:
        # Happy path: basename matching must not turn a read into a write.
        self.assert_silent(_workflow(_stage('Run:\n\n  for p in files; do /usr/bin/wc -l "$p"; done\n')))

    def test_fires_on_mutating_command_after_wrapper_or_reserved_word(self) -> None:
        # PR #433 review (linter_shell.py:844, second finding): a command was
        # in command position only as the first token or after punctuation,
        # so `env rm` and `then rm` were skipped although the guard refuses
        # both. Wrappers and reserved words now pass command position on.
        for command in (
            'for f in files; do env rm -f "$f"; done',
            'for f in files; do if true; then rm -f "$f"; fi; done',
            'for f in files; do sudo -u me rm "$f"; done',
            'for f in files; do timeout 5 nice -n 2 rm "$f"; done',
            'for f in files; do echo "$f" | xargs -n 1 rm; done',
            'for f in files; do FOO=1 command rm "$f"; done',
            'for f in files; do ! rm "$f"; done',
        ):
            with self.subTest(command=command):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))[0].message)

    def test_mutating_name_as_wrapper_or_keyword_argument_is_silent(self) -> None:
        # Happy path: after a wrapper or keyword, only the command word counts.
        for command in (
            'for f in files; do env FOO=1 wc -l "$f"; done',
            "for f in files; do command -v rm; done",
            'for f in files; do if true; then echo rm "$f"; fi; done',
            'for f in files; do timeout 5 grep rm "$f"; done',
        ):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_command_after_the_loop_ends_is_not_in_the_loop(self) -> None:
        # The old body scan ran to the end of the segment, past `done`.
        self.assert_silent(_workflow(_stage('Run:\n\n  for f in a; do cat "$f"; done; rm -f x\n')))

    def test_redirect_on_the_loop_itself_fires(self) -> None:
        # `done > file` redirects the whole loop's output.
        desc = 'Run:\n\n  for f in a; do cat "$f"; done > out.txt\n'
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

    def test_quoted_heredoc_delimiter_is_silent(self) -> None:
        # Copilot PR #433 review: a quoted delimiter makes the body inert data --
        # no expansion occurs inside it at all -- so the guard allows it outright
        # (guard-contract.yaml "quoted heredoc data" -> allow). This must not fire
        # even though {ollama_host} sits in the body, unlike the unquoted _HEREDOC
        # fixture above.
        desc = (
            "Get the value off the command line:\n\n"
            '  cat > "$TMPDIR/qwen-admin-host" <<\'RAW\'\n'
            "  {ollama_host}\n"
            "  RAW\n"
        )
        self.assert_silent(_workflow(_stage(desc), params=_OLLAMA_PARAMS, rules=_OLLAMA_RULE))

    def test_read_only_loop_is_silent(self) -> None:
        # guard-contract.yaml "loop variable in a read" -> allow: a loop whose
        # body only reads is not something the guard refuses, so this rule must
        # not warn on it either.
        desc = 'Report line counts:\n\n  for f in src/*.py; do wc -l "$f"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_static_heredoc_body_is_silent(self) -> None:
        # PR #433 review: _has_heredoc previously fired for every unquoted
        # delimiter regardless of body content. The guard only fails to
        # inspect a heredoc body that contains a substitution -- a purely
        # literal body like this one is something the guard accepts outright.
        desc = (
            "Write the file:\n\n"
            '  cat > "$TMPDIR/notes.txt" <<EOF\n'
            "  literal\n"
            "  EOF\n"
        )
        self.assert_silent(_workflow(_stage(desc)))

    def test_unquoted_heredoc_with_backtick_substitution_fires(self) -> None:
        # A backtick substitution in the body is just as unresolvable to the
        # guard as $(...); the sad path for the static-body fix must still
        # catch this shape.
        desc = (
            "Write the file:\n\n"
            '  cat > "$TMPDIR/notes.txt" <<EOF\n'
            "  `date`\n"
            "  EOF\n"
        )
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("heredoc", hits[0].message)

    def test_python_for_loop_is_not_shell(self) -> None:
        desc = "Inline:\n\n  python3 -I -S -c \"\n  for parser in PARSERS:\n      print(parser)\n  \"\n"
        self.assert_silent(_workflow(_stage(desc)))

    def test_fires_on_loop_preceded_by_setup_line_in_same_fence(self) -> None:
        # Copilot PR #433 r4099834657: split_tokens discards newlines, so a
        # loop head right after setup text in the same fenced block glued
        # onto that text's last word instead of following a separator. The
        # blank line here is only to survive the folded (`>`) YAML scalar
        # this fixture format uses -- extract_shell_segments still returns
        # the setup line and the loop as a single fence segment either way.
        # The body removes a file (mutating), so this also stays a positive
        # case under the guard-contract-aligned loop check.
        desc = "```bash\necho setup\n\nfor p in items; do rm -f \"$p\"; done\n```\n"
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("loop", hits[0].message)

    def test_fires_on_loop_with_sed_in_place(self) -> None:
        # PR #433 review r4099834XXX: sed -i is a write per the guard's
        # "Written" table but was absent from _MUTATING_COMMANDS, so a loop
        # calling it passed shell-guard-refused even though the guard refuses it.
        for command in (
            'for p in files; do sed -i "s/a/b/" "$p"; done',
            'for p in files; do sed --in-place "s/a/b/" "$p"; done',
            'for p in files; do sed -ie "s/a/b/" "$p"; done',
        ):
            with self.subTest(command=command):
                desc = f"Run:\n\n  {command}\n"
                self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_sed_without_in_place_in_loop_is_silent(self) -> None:
        # sed -n (or any sed call without -i/--in-place) only reads: the
        # guard's "Written" table blocks sed operands only with -i present.
        desc = 'Read:\n\n  for p in files; do sed -n "1p" "$p"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_later_commands_dash_i_flag_does_not_taint_earlier_sed(self) -> None:
        # Unlinked triage findings linter_shell.py:586/601: _has_sed_in_place
        # scanned every token after "sed" in the WHOLE loop body, not just
        # tokens belonging to that invocation, so a LATER unrelated command's
        # own -i-shaped flag (here, "grep -i" after the read-only sed) was
        # wrongly attributed to the earlier sed call, firing a false
        # shell-guard-refused on an otherwise safe read-only loop.
        desc = 'Read:\n\n  for p in files; do sed -n "1p" "$p"; grep -i pattern "$p"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_fires_on_loop_with_unsafe_patch(self) -> None:
        # patch is refused by the guard unless --dry-run or -o FILE is given,
        # because it writes the files named inside the diff.
        desc = 'Run:\n\n  for p in diffs; do patch < "$p"; done\n'
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_patch_with_safe_flag_in_loop_is_silent(self) -> None:
        for command in (
            'for p in diffs; do patch --dry-run < "$p"; done',
            'for p in diffs; do patch -o "$p.out" < "$p"; done',
        ):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_later_commands_safe_flag_does_not_exempt_earlier_unsafe_patch(self) -> None:
        # Sad-path sibling for the same bounding fix, applied to patch: a
        # LATER command's --dry-run-shaped token must not be misread as
        # belonging to an earlier, unsafe patch invocation and wrongly
        # exempt it.
        desc = 'Run:\n\n  for p in diffs; do patch < "$p"; echo --dry-run; done\n'
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_fd_duplication_in_loop_is_silent(self) -> None:
        # Unlinked triage finding linter_shell.py:125/633: _REDIRECT_RE matched
        # file-descriptor duplication like `2>&1`, which the guard treats as
        # non-writing (guard-contract.yaml "fd duplication is not a path" and
        # "fd dup is not a path" -> allow), causing a false shell-guard-refused
        # on an otherwise read-only loop.
        desc = 'Report line counts:\n\n  for f in src/*.py; do wc -l "$f" 2>&1; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_bracket_string_comparison_in_loop_is_silent(self) -> None:
        # Unlinked triage finding linter_shell.py:633: the redirect scanner
        # flagged '>' anywhere in a loop body, including inside a
        # `[[ "$f" > a ]]` shell string comparison, which the guard contract
        # explicitly allows as read-only (guard-contract.yaml
        # "[[ > ]] compares" -> allow).
        desc = 'Compare names:\n\n  for f in src/*.py; do [[ "$f" > "a" ]] && echo "$f"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_real_redirect_after_bracket_comparison_still_fires(self) -> None:
        # Sad-path sibling: a genuine write redirect elsewhere in the same
        # loop body must still fire even when a bracket comparison's bare '>'
        # also appears in the body -- the bracket exemption must not swallow
        # an unrelated real redirect.
        desc = (
            "Run:\n\n"
            '  for f in src/*.py; do [[ "$f" > "a" ]] && echo "$f" > out.log; done\n'
        )
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_quoted_redirect_char_as_argument_is_silent(self) -> None:
        # Copilot PRRT_kwDOQr1kjM6mhoo2 (PR #433): split_tokens strips quotes
        # via shlex, so a quoted ">" argument becomes an indistinguishable
        # bare ">" token and was misread as a write redirect. The loop only
        # echoes the character; it writes nothing.
        desc = 'Report:\n\n  for f in files; do echo ">" "$f"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_real_redirect_alongside_quoted_char_still_fires(self) -> None:
        # Sad-path sibling: a genuine write redirect in the same body as a
        # quoted ">" argument must still fire -- the quote-awareness fix must
        # not blind the scan to a real redirect appearing elsewhere.
        desc = 'Report:\n\n  for f in files; do echo ">" "$f" > out.log; done\n'
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_second_heredoc_with_identical_opener_text_still_inspected(self) -> None:
        # Unlinked triage findings linter_shell.py:552/568: _has_heredoc's
        # full_text.find(text) fallback anchors to the FIRST occurrence of
        # matching opener text, so when two heredocs share an identical
        # opener (same redirect target and delimiter) the second, dangerous
        # one's own substitution-bearing body could be missed if the search
        # ever resolved against the wrong occurrence. Fixed by anchoring the
        # search with the segment's own source offset (ShellSegment.start)
        # rather than a text search. Here the first heredoc's body is static
        # (guard accepts it) and the second, textually-identical-opener
        # heredoc's body substitutes (guard refuses it) -- the rule must
        # still fire, driven by the second occurrence.
        desc = (
            "First write:\n\n"
            '  cat > "out" <<EOF\n'
            "  literal\n"
            "  EOF\n\n"
            "Second write:\n\n"
            '  cat > "out" <<EOF\n'
            "  $(date)\n"
            "  EOF\n"
        )
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("heredoc", hits[0].message)

    def test_fires_on_find_write_actions_in_loop(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6ms2Vv: the guard's h_find treats
        # -delete and -fprint as writes, but `cmd.name` was only `find`.
        for command in ('for p in files; do find "$p" -delete; done',
                        'for p in files; do find "$p" -name x -fprint out.txt; done'):
            with self.subTest(command=command):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))[0].message)

    def test_fires_on_find_exec_mutator_in_loop(self) -> None:
        # Same thread: h_find judges the command after -exec/-execdir/-ok.
        for command in ('for p in files; do find "$p" -exec rm {} +; done',
                        'for p in files; do find "$p" -execdir env mv {} x \\; ; done',
                        'for p in files; do find "$p" -ok sed -i "s/a/b/" {} \\; ; done'):
            with self.subTest(command=command):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))[0].message)

    def test_read_only_find_in_loop_is_silent(self) -> None:
        # Happy path: find's read-only forms, and a -delete-shaped word that
        # belongs to an -exec body rather than to find, stay silent.
        for command in ("for p in files; do find . -name x; done",
                        "for p in files; do find . -exec grep -n x {} +; done",
                        "for p in files; do find . -exec grep -delete x {} +; done"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_fires_on_eval_and_bare_nested_shell_anywhere(self) -> None:
        # Same thread: block-destructive-bash.sh refuses eval, a bare
        # `sh -c`, and xargs into a shell outright -- in a loop or not.
        for command in ('eval "$CMD"', "bash -c 'echo hi'", "sh -ec 'echo hi'",
                        "echo a | xargs -n 1 sh run.sh", "find . -exec bash -c 'echo {}' \\;"):
            with self.subTest(command=command):
                desc = f"Run:\n\n  ```bash\n  {command}\n  ```\n"
                self.assertIn("eval/sh -c", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_fires_on_mutator_inside_qualified_shell_string_in_loop(self) -> None:
        # Same thread: a /bin/sh -c string escapes the destructive guard's
        # nested-shell check, but _bash_write_targets.py h_shell parses the
        # string and judges its commands; so does this rule. A shell reading
        # its program from stdin is refused by h_shell too.
        for command in ("for f in a; do /bin/sh -c 'rm -f x'; done",
                        "for f in a; do /bin/bash -c 'cd x && touch y'; done",
                        "for f in a; do echo x | /bin/bash; done"):
            with self.subTest(command=command):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))[0].message)

    def test_read_only_qualified_shell_forms_are_silent(self) -> None:
        # Happy path: a read-only -c string, a script file (command semantics,
        # out of the guard's reach), and a qualified shell outside a loop.
        for command in ("for f in a; do /bin/sh -c 'wc -l x'; done",
                        "for f in a; do /bin/bash script.sh; done",
                        "/bin/sh -c 'rm -f x'",
                        "echo eval sh -c"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))

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

    def test_fence_marker_alone_on_its_line_is_still_recognized(self) -> None:
        # Happy path: a normal fence, unaffected by folded-scalar collapsing,
        # still yields one fence segment with all its body lines intact.
        desc = "```bash\necho setup\nfor p in items; do echo \"$p\"; done\n```\n"
        segments = extract_shell_segments(desc)
        fence_segments = [s for s in segments if s.origin == "fence"]
        self.assertEqual(len(fence_segments), 1)
        self.assertEqual(fence_segments[0].text, 'echo setup\nfor p in items; do echo "$p"; done')

    def test_folded_scalar_collapses_fence_marker_onto_first_command(self) -> None:
        # PR #433 review: most workflow stages use YAML folded scalars
        # (`description: >`), which collapse a fence's opening marker line
        # and its first command onto one line before this function ever
        # sees them -- "```bash" + "echo setup" arrives as
        # "```bash echo setup". The old _FENCE_RE required the marker alone
        # on its line, so it missed that line entirely and the whole fenced
        # block -- including the loop line -- was silently dropped as shell.
        desc = '```bash echo setup\nfor p in items; do echo "$p"; done\n```\n'
        segments = extract_shell_segments(desc)
        fence_segments = [s for s in segments if s.origin == "fence"]
        self.assertEqual(len(fence_segments), 1)
        self.assertEqual(fence_segments[0].text, 'echo setup\nfor p in items; do echo "$p"; done')
        # The collapsed first command must survive, not be discarded.
        self.assertIn("echo setup", fence_segments[0].text)

    def test_folded_scalar_collapses_unlabelled_fence_marker_onto_first_command(self) -> None:
        # PR #433 review (follow-up): the fix above only covers a LABELLED
        # fence folded onto one line ("```bash echo setup"). An UNLABELLED
        # fence folded the same way ("``` echo setup") has no language tag,
        # but the lang-tag group in _FENCE_OPEN_RE is greedy and captures
        # "echo" as if it were one; _fence_is_shell then rejected it
        # ("echo" not in _SHELL_FENCE_LANGS) and the whole block -- an
        # unlabelled fence whose first line is a command, which the module's
        # own contract says counts as shell -- was silently dropped.
        desc = '``` echo setup\nfor p in items; do echo "$p"; done\n```\n'
        segments = extract_shell_segments(desc)
        fence_segments = [s for s in segments if s.origin == "fence"]
        self.assertEqual(len(fence_segments), 1)
        self.assertEqual(fence_segments[0].text, 'echo setup\nfor p in items; do echo "$p"; done')

    def test_folded_scalar_collapsed_unlabelled_fence_with_prose_first_line_stays_silent(self) -> None:
        # Sibling near-miss: when the collapsed first line is NOT a command
        # (prose, not a recognised command word), the fence must still be
        # rejected as non-shell -- the fix must not turn every unlabelled
        # collapsed fence into shell regardless of content.
        desc = "``` this is just prose\nmore prose\n```\n"
        self.assertEqual(extract_shell_segments(desc), [])

    def test_folded_python_fence_is_not_reclassified_as_unlabelled_shell(self) -> None:
        # PR #433 review: a REAL language tag ("python") folded onto one
        # line by a YAML folded scalar ("```python python3 -c ...") has the
        # same shape, after folding, as the unlabelled-fence case above --
        # an unrecognised tag with trailing text. Before this fix, both
        # were handled identically: the fallback discarded the tag and
        # treated "python python3 -c ..." as an unlabelled fence's first
        # body line, and "python3" (a strong command in _STRONG_COMMANDS)
        # made the fence lint as shell. A python-labelled fence is not a
        # shell fence and must yield zero fence segments.
        desc = '```python python3 -c "print(1)"\nmore_code = 2\n```\n'
        segments = extract_shell_segments(desc)
        fence_segments = [s for s in segments if s.origin == "fence"]
        self.assertEqual(fence_segments, [])

    def test_folded_unlabelled_fence_opening_with_python_is_shell(self) -> None:
        # PR #433 review (shell_text.py:317): the space after the marker
        # marks "python" as the body's first word, not a language tag.
        desc = "``` python -c 'print(1)'\nmore_code\n```\n"
        fence_segments = [s for s in extract_shell_segments(desc) if s.origin == "fence"]
        self.assertEqual([s.text for s in fence_segments], ["python -c 'print(1)'\nmore_code"])

    def test_spaced_shell_tag_with_trailing_text_stays_shell(self) -> None:
        # "``` bash echo x" is shell whichever way the word is read.
        desc = "``` bash echo x\n```\n"
        self.assertEqual(len([s for s in extract_shell_segments(desc) if s.origin == "fence"]), 1)

    def test_spaced_tag_alone_on_its_line_keeps_its_language(self) -> None:
        # Nothing was folded onto "``` python", so the word is its tag.
        self.assertEqual(extract_shell_segments("``` python\nprint(1)\n```\n"), [])

    def test_folded_unlabelled_fence_opening_with_single_word_command(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6ms2Wg: "``` echo" has a gap but no
        # trailing text, so "echo" was returned as the language and the fence
        # was dropped although its first body line is a command.
        self.assertEqual(self._texts("``` echo\nhi\n```\n"), ["echo\nhi"])
        self.assertEqual(self._texts("``` python3\n```\n"), ["python3"])

    def test_python_tagged_fences_stay_non_shell(self) -> None:
        # Happy path: a glued "```python" tag, and the spaced "``` python"
        # language tag, are still Python fences.
        for desc in ("```python\nprint(1)\n```\n", "``` python\nprint(1)\n```\n",
                     "``` python\nimport os\n```\n"):
            with self.subTest(desc=desc):
                self.assertEqual(extract_shell_segments(desc), [])

    def test_bare_interpreter_operand_is_a_command_line(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6ms2U4: a suffixless script operand.
        self.assertEqual(self._texts("  python3 runner\n"), ["python3 runner"])
        self.assertEqual(self._texts("  python3 runner -v\n"), ["python3 runner -v"])

    def test_interpreter_prose_is_not_a_command_line(self) -> None:
        for line in ("python3 is required", "python3 is required for this step",
                     "python must be 3.11 or newer"):
            with self.subTest(line=line):
                self.assertEqual(self._texts(f"  {line}\n"), [])

    def test_wrapper_led_lines_are_command_lines(self) -> None:
        # PR #437 "Previously missed" finding: wrappers parse_shell sees
        # through (WRAPPER_NAMES) now lead a command line when what they run
        # is itself a command.
        for line in ("env FOO=1 python3 -c 'print(1)'", "timeout 5 python3 run.py",
                     "timeout 1200 ./bin/github pr checks --pr 1", "nohup git fetch",
                     "time -p make -C src lint", "command rm -f x"):
            with self.subTest(line=line):
                self.assertEqual(self._texts(f"  {line}\n"), [line])

    def test_prose_led_by_a_wrapper_word_is_not_a_command_line(self) -> None:
        # Happy path: the words that follow a wrapper-shaped English word are
        # prose, so the line is too. The last three are real lines from
        # workflows/code/qwen-local-handler.yaml and qwen-admin.yaml.
        for line in ("env vars must be set before the run", "time to wait for CI",
                     "time regardless of lock state.", "timeout to interrupt a blocked handler",
                     "timeout — so the exposure is seconds rather than minutes,",
                     "nice to have: a faster runner"):
            with self.subTest(line=line):
                self.assertEqual(self._texts(f"  {line}\n"), [])

    def test_assignment_and_if_lines_are_commands(self) -> None:
        self.assertEqual(self._texts("  export FOO=1\n"), ["export FOO=1"])
        self.assertEqual(self._texts("  if true; then echo ok; fi\n"), ["if true; then echo ok; fi"])
        self.assertEqual(self._texts("  if the gate fails, stop\n"), [])

    def test_quote_context_handles_nested_substitution(self) -> None:
        text = 'X="$(jq -r \'.a\' "$F")" {k}'
        ctx = quote_context(text)
        self.assertEqual(ctx[text.index(".a")], "'")
        self.assertEqual(ctx[text.index("{k}")], "")
        self.assertEqual(ctx[text.index("$F")], '"')

    def test_versioned_interpreter_is_a_command_line(self) -> None:
        # Unlinked triage finding shell_text.py:209: only the exact names
        # "python"/"python3", or a path ending in "/python3", were recognised
        # -- a versioned interpreter like python3.11 was silently treated as
        # prose and extracted no segment at all.
        self.assertEqual(self._texts("  python3.11 tools/run_checks\n"), ["python3.11 tools/run_checks"])
        self.assertEqual(
            self._texts("  /usr/bin/python3.12 -c 'print(1)'\n"),
            ["/usr/bin/python3.12 -c 'print(1)'"],
        )

    def test_unversioned_python_still_a_command_line(self) -> None:
        # Happy-path sibling: the pre-existing exact-name/-path forms this
        # function already handled must keep working after generalising to
        # the regex-based versioned check.
        self.assertEqual(self._texts("  python3 -c 'print(1)'\n"), ["python3 -c 'print(1)'"])
        self.assertEqual(
            self._texts("  /usr/bin/python3 -c 'print(1)'\n"), ["/usr/bin/python3 -c 'print(1)'"],
        )

    def test_heredoc_body_is_included_in_the_line_segment(self) -> None:
        # Unlinked triage finding shell_text.py:305: _line_segments only ever
        # emitted the heredoc OPENER line -- the opener itself has no
        # unclosed quote or trailing backslash, so _can_continue stopped
        # right after it and the body never became part of any segment's
        # text. A caller-supplied placeholder substituted into an unquoted
        # (shell-expanding) heredoc body must reach the same segment text a
        # {param} scan inspects.
        desc = "cat <<EOF\n{host}\nEOF\n"
        segments = extract_shell_segments(desc)
        self.assertEqual(len(segments), 1)
        self.assertIn("{host}", segments[0].text)
        self.assertEqual(segments[0].text, "cat <<EOF\n{host}\nEOF")

    def test_quoted_heredoc_body_is_not_absorbed(self) -> None:
        # Happy-path sibling: a quoted delimiter's body is inert (no shell
        # expansion happens inside it at all), so absorbing it into the
        # segment TEXT is unnecessary -- confirms the fix only widens the
        # unquoted case's appended text, matching linter_shell.py's own
        # quoted/unquoted heredoc distinction.
        desc = "cat <<'EOF'\n{host}\nEOF\n"
        segments = extract_shell_segments(desc)
        self.assertEqual(len(segments), 1)
        self.assertNotIn("{host}", segments[0].text)
        self.assertEqual(segments[0].text, "cat <<'EOF'")

    def test_quoted_heredoc_body_is_still_consumed_as_its_own_segment(self) -> None:
        # PR #433 review: the quoted-delimiter branch used to return early
        # without marking the body lines CONSUMED, so _line_segments revisited
        # a command-looking body line as an INDEPENDENT segment of its own --
        # even though the same body text is correctly excluded from the
        # opener's segment text above. A quoted heredoc body must produce
        # exactly one segment total (the opener), not two.
        desc = "cat <<'EOF'\necho \"$UNBOUND\"\nEOF\n"
        segments = extract_shell_segments(desc)
        self.assertEqual(len(segments), 1, msg=segments)
        self.assertEqual(segments[0].text, "cat <<'EOF'")



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
