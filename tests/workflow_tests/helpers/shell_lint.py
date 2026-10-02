"""Shared builders for the shell-lint test modules (workflow.linter_shell).

The ``test_linter_shell*.py`` suites build workflows, lint them and assert
per-rule results through these helpers and the fixtures they share. Not a
test module: its name keeps unittest discovery from collecting it.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
import unittest.mock as mock
from pathlib import Path

from workflow.linter import (
    LintResult,
    lint_workflow,
)
from workflow.linter_shell import (
    RULE_GUARD_REFUSED,
    RULE_PYTHON_NOT_ISOLATED,
    RULE_UNBOUND_VARIABLE,
    RULE_UNQUOTED_FAN_OUT_KEY,
    RULE_UNVALIDATED_PARAM,
    RULE_VALIDATE_WRITES_OUTPUT,
)
from workflow.linter_types import LintWarning


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


# Params and rule for the ollama_host fixtures, shared by the
# unvalidated-param and guard-refused suites.
OLLAMA_PARAMS = 'ollama_host: "http://localhost:11434"'
OLLAMA_RULE = "ollama_host: 'https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?/?'"


def _fenced(line: str) -> str:
    """*line* as a fenced bash block; blank lines survive the folded scalar as line breaks."""
    return f"```bash\n\n{line}\n\n```\n"


# qwen-local-handler.yaml verify stage at 6474c76e (PR #391 round 0).
BARE_PYTHON = """
    Confirm the import resolves to this worktree:

      python3 -c "import worker; print(worker.__file__)"
"""
