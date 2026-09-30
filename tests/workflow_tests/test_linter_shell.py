"""Tests for the shell-text lint rules (workflow.linter_shell, workflow.shell_text).

The worker, guard-refused, python-not-isolated and extraction suites live in
the sibling ``test_linter_shell_*.py`` modules; shared builders are in
``helpers/shell_lint.py``.

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
import unittest
from pathlib import Path

from tests.workflow_tests.helpers.shell_lint import (
    _BARE_PYTHON,
    _OLLAMA_PARAMS,
    _OLLAMA_RULE,
    _RuleCase,
    _fenced,
    _hits,
    _lint,
    _lint_text,
    _stage,
    _workflow,
)
from workflow.linter import lint_workflow
from workflow.linter_shell import (
    RULE_PYTHON_NOT_ISOLATED,
    RULE_UNBOUND_VARIABLE,
    RULE_UNQUOTED_FAN_OUT_KEY,
    RULE_UNVALIDATED_PARAM,
    RULE_VALIDATE_WRITES_OUTPUT,
)


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

    def test_quoted_heredoc_body_placeholder_fires(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nOAmF: a quoted delimiter stops the
        # SHELL expanding the body, but {host} is substituted into the text
        # before bash parses it, so a value of "EOF\n<command>" closes the
        # heredoc and runs the rest (param_guard.py's module docstring). The
        # body was dropped from line segments and skipped as inert in fences.
        for desc in (
            "Write the file:\n\n  cat > \"$TMPDIR/notes.txt\" <<'EOF'\n  {host}\n  EOF\n",
            "```bash\n\ncat > \"$TMPDIR/notes.txt\" <<'EOF'\n\n{host}\n\nEOF\n\n```\n",
        ):
            with self.subTest(desc=desc):
                hits = self.assert_fires(_workflow(_stage(desc), params='host: "example.com"'))
                self.assertIn("'{host}'", hits[0].message)

    def test_quoted_heredoc_body_placeholder_with_param_rule_is_silent(self) -> None:
        # Happy path: an engine-enforced rule constrains the value first.
        desc = "Write the file:\n\n  cat > \"$TMPDIR/notes.txt\" <<'EOF'\n  {host}\n  EOF\n"
        self.assert_silent(_workflow(
            _stage(desc), params='host: "example.com"', rules="host: '[a-z.]+'"))

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
        self.assert_fires(_fan_out_workflow("echo ok # don't\n  rm {domain}"))

    def test_key_in_comment_is_silent(self) -> None:
        # Agent fan-out keys are held to [A-Za-z0-9][A-Za-z0-9._-]* by the
        # orchestrator (SKILL.md SAFE_KEY_VALUE): no newline can end a comment.
        self.assert_silent(_fan_out_workflow("echo ok # sweep {domain}"))

    def test_key_in_quoted_heredoc_body_is_silent(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nOAmF, checked for this rule too: the
        # same allowlist means no value can carry the newline that ends a
        # quoted heredoc, so the body stays inert here (unlike a {param}).
        self.assert_silent(_fan_out_workflow("cat <<'EOF'\n  {domain}\n  EOF"))

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


if __name__ == "__main__":
    unittest.main()
