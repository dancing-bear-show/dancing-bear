"""Shell-lint rules on worker-dispatched stages: check-params credit, worker_queue fan-outs, scripts."""

from __future__ import annotations

import json
import unittest
import unittest.mock as mock

from tests.workflow_tests.helpers.shell_lint import (
    _RuleCase,
    _hits,
    _lint,
    _stage,
    _workflow,
)
from workflow.linter_shell import (
    RULE_GUARD_REFUSED,
    RULE_PYTHON_NOT_ISOLATED,
    RULE_UNBOUND_VARIABLE,
    RULE_UNQUOTED_FAN_OUT_KEY,
    RULE_UNVALIDATED_PARAM,
)
from workflow.linter_types import LintWarning


# Fenced as _fenced() builds them (helpers/shell_lint.py).
_HOST_CHECK = "```bash\n\n./bin/workflow check-params m.json --check host=trusted\n\n```\n"
_HOST_USE = "```bash\n\necho {host}\n\n```\n"


def _upstream_check_workflow(upstream_extra: str) -> str:
    """A check-params in an upstream stage's description, then a {host} use downstream."""
    return _workflow(
        _stage(_HOST_CHECK, name="check", extra=upstream_extra),
        _stage(_HOST_USE, name="use", depends_on="[check]"),
        params='host: "example.com"',
    )


class TestWorkerStageCheckParams(_RuleCase):
    """PR #437 thread PRRT_kwDOQr1kjM6nU0Mh: a worker stage's description never runs.

    Its check-params calls used to be credited as validation for every
    descendant, though a worker runs only the script fields.
    """

    rule = RULE_UNVALIDATED_PARAM

    def test_worker_stage_description_check_does_not_validate_descendants(self) -> None:
        for extra in ("    executor: worker_queue\n    script: \"ls data/\"\n",
                      "    fan_out:\n      source: seed\n      field: items\n      key: item\n"
                      "      mode: worker_queue\n      script: \"ls data/\"\n"):
            with self.subTest(extra=extra.split(":")[0].strip()):
                hits = self.assert_fires(_upstream_check_workflow(extra))
                self.assertEqual(hits[0].stage, "use")
                self.assertIn("'{host}'", hits[0].message)

    def test_worker_stage_description_check_does_not_validate_its_own_uses(self) -> None:
        extra = "    executor: worker_queue\n    script: \"ls data/\"\n"
        yaml_text = _workflow(_stage(_HOST_CHECK + _HOST_USE, extra=extra), params='host: "example.com"')
        self.assertEqual(self.assert_fires(yaml_text)[0].stage, "work")

    def test_worker_script_check_does_not_validate_descendants(self) -> None:
        # The engine records the worker stage pending at enqueue and never
        # reads the job's exit status, so a rejected check stops nothing.
        script = json.dumps("./bin/workflow check-params m.json --check host=trusted")
        yaml_text = _workflow(
            _stage("Enqueued.", name="check", extra=f"    executor: worker_queue\n    script: {script}\n"),
            _stage(_HOST_USE, name="use", depends_on="[check]"),
            params='host: "example.com"',
        )
        self.assertEqual(self.assert_fires(yaml_text)[0].stage, "use")

    def test_agent_stage_check_still_validates_descendants(self) -> None:
        self.assert_silent(_upstream_check_workflow(""))


def _worker_queue_workflow(
    script: str, *, description: str = "Enqueued once per domain.", stage_script: str = "",
    params: str = "",
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
        params=params,
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

    def test_key_in_enqueued_stage_script_fires(self) -> None:
        # WorkerQueueDispatcher enqueues the stage-level script as the job's payload.
        hits = self._hits(_worker_queue_workflow("ls data/", stage_script="ls {domain}/"))
        self.assertEqual([w.field for w in hits], ["script"])

    def test_quoted_key_in_script_fires(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nH4zT: a worker_queue key is never
        # checked against SAFE_KEY_VALUE, and it is substituted before bash
        # parses the script, so a value like `x'; rm -rf ~; '` escapes quotes.
        for script in ("rm '{domain}'", 'rm "{domain}"'):
            with self.subTest(script=script):
                hits = self._hits(_worker_queue_workflow(script))
                self.assertEqual([w.field for w in hits], ["fan_out.script"])
                self.assertIn("not allowlisted before worker dispatch", hits[0].message)
                self.assertIn("pass it as data", hits[0].message)

    def test_key_in_comment_of_script_fires(self) -> None:
        # Same thread: a newline in the value ends the comment.
        hits = self._hits(_worker_queue_workflow("ls data/  # {domain}"))
        self.assertEqual([w.field for w in hits], ["fan_out.script"])

    def test_key_in_quoted_heredoc_of_script_fires(self) -> None:
        # Same thread: a line equal to the delimiter in the value ends the heredoc.
        hits = self._hits(_worker_queue_workflow("cat <<'EOF'\n{domain}\nEOF"))
        self.assertEqual([w.field for w in hits], ["fan_out.script"])

    def test_every_occurrence_is_counted_per_script(self) -> None:
        hits = self._hits(_worker_queue_workflow(
            "ls \"{domain}/\" || echo 'no dir: {domain}'", stage_script="ls '{domain}'"))
        self.assertEqual([w.field for w in hits], ["fan_out.script", "script"])
        self.assertIn("2 time(s)", hits[0].message)
        self.assertIn("1 time(s)", hits[1].message)

    def test_executor_worker_queue_with_agent_fan_out_checks_the_script(self) -> None:
        # CompositeDispatcher routes on executor: the stage script runs, the
        # description reaches no agent.
        yaml_text = _workflow(
            _stage("List domains.", name="gather", extra="    writes_to:\n      - domains.json\n"),
            _stage(
                'Check:\n\n  ls "{domain}/"\n', name="check-domain", depends_on="[gather]",
                extra=(
                    "    reads_from: [gather]\n"
                    "    fan_out:\n      source: gather\n      field: domains\n      key: domain\n"
                    f"    executor: worker_queue\n    script: {json.dumps('ls {domain}')}\n"
                ),
            ),
        )
        self.assertEqual([w.field for w in self._hits(yaml_text)], ["script"])

    def test_script_without_key_is_silent(self) -> None:
        # Happy path: a script that takes nothing from the fan-out item.
        self.assertEqual(self._hits(_worker_queue_workflow("ls data/", stage_script="wc -l data/x")), [])

    def test_description_is_not_checked_in_worker_queue_mode(self) -> None:
        # Neither prose nor a shell-shaped line in the description reaches a
        # shell or an agent in this mode.
        for description in ("Remove the {domain} directory.", "Remove it:\n\n  rm -r {domain}\n"):
            with self.subTest(description=description):
                self.assertEqual(self._hits(_worker_queue_workflow("ls data/", description=description)), [])

    def test_has_teeth(self) -> None:
        yaml_text = _worker_queue_workflow("rm {domain}")
        self.assertTrue(self._hits(yaml_text))
        with mock.patch("workflow.linter_shell._unquoted_fan_out_keys", return_value=[]):
            self.assertEqual(_lint(yaml_text).warnings, [])


class TestWorkerScriptsAreLinted(unittest.TestCase):
    """PR #437 thread PRRT_kwDOQr1kjM6nOAmz: a worker runs its scripts, so every shell rule reads them."""

    def _warnings(self, yaml_text: str) -> list[tuple[str, str]]:
        result = _lint(yaml_text)
        self.assertTrue(result.valid, msg=result.errors)
        return [(w.rule, w.field) for w in result.warnings]

    def test_unisolated_python_in_stage_script_fires(self) -> None:
        warnings = self._warnings(_worker_queue_workflow("ls data/", stage_script="python3 runner"))
        self.assertEqual(warnings, [(RULE_PYTHON_NOT_ISOLATED, "script")])

    def test_unisolated_python_in_fan_out_script_fires(self) -> None:
        warnings = self._warnings(_worker_queue_workflow("python3 runner data/"))
        self.assertEqual(warnings, [(RULE_PYTHON_NOT_ISOLATED, "fan_out.script")])

    def test_unbound_variable_in_script_fires(self) -> None:
        warnings = self._warnings(_worker_queue_workflow('ls "$UNBOUND"', stage_script='wc -l "$OTHER"'))
        self.assertEqual(warnings, [(RULE_UNBOUND_VARIABLE, "fan_out.script"), (RULE_UNBOUND_VARIABLE, "script")])

    def test_each_script_is_its_own_shell(self) -> None:
        # Each field runs as a separate `bash FILE`: a binding in one does
        # not reach the other.
        warnings = self._warnings(_worker_queue_workflow("X=1", stage_script='echo "$X"'))
        self.assertEqual(warnings, [(RULE_UNBOUND_VARIABLE, "script")])

    def test_guard_refused_construct_in_script_fires(self) -> None:
        warnings = self._warnings(_worker_queue_workflow('for f in a b; do rm "$f"; done'))
        self.assertEqual(warnings, [(RULE_GUARD_REFUSED, "fan_out.script")])

    def test_clean_scripts_are_silent(self) -> None:
        # Happy path: isolated interpreter, variable bound in the same script.
        self.assertEqual(self._warnings(_worker_queue_workflow(
            'X=data; ls "$X"', stage_script="python3 -I x.py")), [])

    def test_description_is_not_checked_or_double_reported(self) -> None:
        # The description never executes in this mode: a bare interpreter,
        # an unbound variable and a refused loop there report nothing, and
        # the script's own offender is reported once, under its field.
        description = 'Run:\n\n  python3 runner\n  echo "$UNBOUND"\n  for f in a; do rm "$f"; done\n'
        self.assertEqual(self._warnings(_worker_queue_workflow(
            "ls data/", description=description, stage_script="python3 -I x.py")), [])
        self.assertEqual(self._warnings(_worker_queue_workflow(
            "ls data/", description=description, stage_script="python3 runner")),
            [(RULE_PYTHON_NOT_ISOLATED, "script")])

    def test_caller_params_in_scripts_are_not_reported(self) -> None:
        # The engine substitutes caller params into the description only
        # (compiler.resolve_params); a script's {host} is never replaced, so
        # shell-unvalidated-param stays off for scripts.
        warnings = self._warnings(_worker_queue_workflow(
            "curl {host}", stage_script="curl {host}", params='host: "example.com"'))
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
