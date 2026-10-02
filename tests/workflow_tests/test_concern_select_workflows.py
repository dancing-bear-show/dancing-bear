"""Engine-level checks for the workflows that call ``select-concerns``.

These compile and render the real YAML through the engine, as an agent would
receive it:

* ``trigger.param_rules`` rejects shell-injection payloads at compile time in
  load-concerns, critique, and cli-standard-conformance (via the plan-critic
  fragment's rule), and still admits the legitimate values;
* load-concerns' task_type allowlist matches ``selection.yaml``;
* the select-guides prompt carries ``file_paths`` as data and never on a
  command line;
* the plan-critic fallback selects from a paths file plus
  ``--task-type workflow``, never from the plan document alone, and declares
  every file it writes.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from workflow.compiler import WorkflowCompileError, compile_workflow
from workflow.concern_select import select_guides, valid_task_types
from workflow.dispatch import build_agent_prompt
from workflow.parser import parse_workflow

_ROOT = Path(__file__).resolve().parents[2]
_LOAD_CONCERNS = _ROOT / "workflows/code/load-concerns.yaml"
_CRITIQUE = _ROOT / "workflows/shared/critique.yaml"
_CONFORMANCE = _ROOT / "workflows/code/cli-standard-conformance.yaml"

# Payloads that break out of a shell word, or smuggle a git option.
_INJECTIONS = (
    "x$(id)",
    "x`id`",
    "x;id",
    "x|id",
    "x&&id",
    "x id",
    "x\nid",
    'x"id',
    "x'id",
    "x>out",
    "x${IFS}id",
)


def _compile(path: Path, **params: str):
    return compile_workflow(parse_workflow(str(path)), project_root=_ROOT, trigger_params=params)


def _prompts(path: Path, **params: str) -> dict[str, str]:
    defn = parse_workflow(str(path))
    manifest = compile_workflow(defn, project_root=_ROOT, trigger_params=params)
    with tempfile.TemporaryDirectory() as ws:
        return {name: build_agent_prompt(stage, defn.name, ws)
                for name, stage in manifest.resolved_stages.items()}


class _RejectsMixin(unittest.TestCase):
    path: Path

    def assert_rejected(self, name: str, value: str) -> None:
        with self.subTest(param=name, value=value), self.assertRaises(WorkflowCompileError) as ctx:
            _compile(self.path, **{name: value})
        # Never echo a rejected value.
        self.assertNotIn(value, str(ctx.exception))

    def assert_accepted(self, name: str, value: str) -> None:
        with self.subTest(param=name, value=value):
            _compile(self.path, **{name: value})


class TestLoadConcernsParamRules(_RejectsMixin):
    path = _LOAD_CONCERNS

    def test_task_type_payloads_rejected(self) -> None:
        for payload in _INJECTIONS:
            self.assert_rejected("task_type", "feature" + payload[1:])
        self.assert_rejected("task_type", "features")  # typo, not a type

    def test_every_valid_task_type_compiles(self) -> None:
        for task_type in [*valid_task_types(), ""]:
            self.assert_accepted("task_type", task_type)

    def test_file_paths_payloads_rejected(self) -> None:
        for payload in _INJECTIONS:
            if payload == "x id":
                continue  # a space separates paths; it is legitimate here
            self.assert_rejected("file_paths", "src/a.py," + payload)

    def test_file_paths_separators_compile(self) -> None:
        self.assert_accepted("file_paths", "src/a.py, workflows/b.yaml")
        self.assert_accepted("file_paths", "src/a.py workflows/b.yaml")
        self.assert_accepted("file_paths", ".claude/agents/x.md")

    def test_task_type_rule_matches_selection_yaml(self) -> None:
        """The allowlist must name exactly the task_type_rules keys."""
        rules = {c.name: c.pattern for c in parse_workflow(str(_LOAD_CONCERNS)).trigger.rules.checks}
        match = re.fullmatch(r"\((.*)\)\?", rules["task_type"])
        if match is None:
            self.fail(f"task_type rule is not an optional alternation: {rules['task_type']}")
        self.assertEqual(set(match.group(1).split("|")), set(valid_task_types()))


class TestCritiqueParamRules(_RejectsMixin):
    path = _CRITIQUE

    def test_diff_ref_payloads_rejected(self) -> None:
        for payload in _INJECTIONS:
            self.assert_rejected("diff_ref", "main" + payload[1:])
        self.assert_rejected("diff_ref", "--output=/tmp/x")  # nosec B108 - payload text
        self.assert_rejected("diff_ref", "-p")

    def test_diff_ref_valid_values_compile(self) -> None:
        for ref in ("", "main...HEAD", "HEAD~1", "origin/main", "abc123^", "HEAD"):
            self.assert_accepted("diff_ref", ref)

    def test_target_payloads_rejected(self) -> None:
        for payload in _INJECTIONS:
            self.assert_rejected("target", "docs/a.md" + payload[1:])
        self.assert_rejected("target", "../outside.md")
        self.assert_rejected("target", "-rf")

    def test_target_valid_values_compile(self) -> None:
        for target in (".llm/DESIGN_CRITERIA.md", "workflows/code/foo.yaml", "src/a_b-c.py"):
            self.assert_accepted("target", target)

    def test_targets_payloads_rejected(self) -> None:
        for payload in _INJECTIONS:
            self.assert_rejected("targets", "a.md,b.md" + payload[1:])
        self.assert_rejected("targets", "a.md,../b.md")

    def test_targets_valid_values_compile(self) -> None:
        self.assert_accepted("targets", "src/a.py,src/b.py")
        self.assert_accepted("targets", "src/a.py, src/b.py")

    def test_plan_file_is_pinned(self) -> None:
        self.assert_rejected("plan_file", "design/plan.md")
        self.assert_rejected("plan_file", "context/target.md$(id)")
        self.assert_accepted("plan_file", "context/target.md")


class TestConformancePlanFileRule(_RejectsMixin):
    """The rule lives on the plan-critic fragment and reaches every includer."""

    path = _CONFORMANCE

    def test_plan_file_payloads_rejected(self) -> None:
        for payload in _INJECTIONS:
            self.assert_rejected("plan_file", "design/plan.md" + payload[1:])
        self.assert_rejected("plan_file", "../plan.md")
        self.assert_rejected("plan_file", "-plan.md")

    def test_default_plan_file_compiles(self) -> None:
        self.assert_accepted("plan_file", "design/plan.md")


class TestLoadConcernsSelectGuidesPrompt(unittest.TestCase):
    """file_paths must reach the stage as data, and only as data."""

    VALUE = "src/zzprobe_a.py, workflows/zzprobe_b.yaml"

    def setUp(self) -> None:
        self.prompt = _prompts(_LOAD_CONCERNS, file_paths=self.VALUE)["select-guides"]

    def test_value_appears_in_the_prompt(self) -> None:
        self.assertIn(self.VALUE, self.prompt)

    def test_value_is_never_on_a_command_line(self) -> None:
        command_markers = ("./bin/", "--paths", "select-concerns", "echo ", "git ", "$(", "<<")
        for line in self.prompt.splitlines():
            if "zzprobe" not in line:
                continue
            with self.subTest(line=line):
                for marker in command_markers:
                    self.assertNotIn(marker, line)

    def test_selector_reads_the_paths_file(self) -> None:
        self.assertIn("--paths-file", self.prompt)
        self.assertIn("check-params", self.prompt)


class TestLoadConcernsTaskTypeCommand(unittest.TestCase):
    """No rendered command may carry --task-type without a value.

    With the default task_type="" the old block rendered
    ``--task-type \\`` then ``--format json``, which argparse rejects.
    """

    _BARE_FLAG = re.compile(r"--task-type\s*(\\\s*)?(--|$)", re.MULTILINE)

    def _select_guides(self, task_type: str) -> str:
        return _prompts(_LOAD_CONCERNS, file_paths="src/a.py", task_type=task_type)["select-guides"]

    def test_default_empty_task_type_has_a_runnable_command(self) -> None:
        prompt = self._select_guides("")
        self.assertIsNone(self._BARE_FLAG.search(prompt))
        self.assertIn('--paths-file "', prompt)
        self.assertIn("--format json", prompt)

    def test_non_empty_task_type_is_passed_with_its_value(self) -> None:
        prompt = self._select_guides("feature")
        self.assertIn('--task-type "feature" --format json', prompt)
        self.assertIsNone(self._BARE_FLAG.search(prompt))

    def test_detector_flags_the_old_rendering(self) -> None:
        old = "./bin/workflow select-concerns \\\n  --paths-file x \\\n  --task-type  \\\n  --format json"
        self.assertIsNotNone(self._BARE_FLAG.search(old))


class TestPlanCriticFallback(unittest.TestCase):
    """cli-standard-conformance has no prepare-target, so pc-critic selects."""

    def setUp(self) -> None:
        self.prompts = _prompts(_CONFORMANCE)
        self.critic = self.prompts["pc-critic"]

    def test_selects_from_a_paths_file_with_the_workflow_floor(self) -> None:
        lines = [ln for ln in self.critic.splitlines() if "select-concerns" in ln]
        self.assertTrue(lines)
        for line in lines:
            with self.subTest(line=line):
                self.assertIn("--paths-file", line)
                self.assertIn("--task-type workflow", line)
                self.assertNotIn("plan.md", line)

    def test_floor_is_never_weaker_than_the_old_fixed_set(self) -> None:
        old = {"workflow.md", "workflow-fanout.md", "workflow-fragments.md", "patterns.md"}
        self.assertLessEqual(old, set(select_guides(paths=[], task_type="workflow")))
        # A plan naming Python paths also gets the Python guides.
        with_py = select_guides(paths=["src/workflow/cli.py"], task_type="workflow")
        self.assertIn("correctness.md", with_py)
        self.assertIn("security.md", with_py)

    def test_critic_declares_every_file_it_writes(self) -> None:
        defn = parse_workflow(str(_CONFORMANCE))
        critic = next(s for s in defn.stages if s.name == "pc-critic")
        self.assertIn("validation/critic-concerns.json", critic.writes_to)
        self.assertIn("validation/critic-paths.txt", critic.writes_to)
        # prepare-target in critique.yaml owns context/concerns.json.
        self.assertNotIn("context/concerns.json", critic.writes_to)

    def test_validate_critique_reads_the_critic_record(self) -> None:
        self.assertIn("critic-concerns.json", self.prompts["pc-validate-critique"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
