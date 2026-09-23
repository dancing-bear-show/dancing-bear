"""Tests for workflow.harness_outputs and its two consumers, lint and compile.

The harness refuses a subagent Write of report.md / summary.md / findings.md. A
stage can name its output literally in writes_to or through a param such as
validate-then-render's {report_artifact}, which that fragment leaves out of
writes_to. Lint sees param defaults; only compile sees a --params override.
These pin both paths, using a real caller of the fragment.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.compiler import WorkflowCompileError, compile_workflow
from workflow.harness_outputs import find_refused_outputs, is_refused
from workflow.linter import lint_workflow
from workflow.models import AgentSpec, StageKind, StageSpec
from workflow.parser import parse_workflow

from tests.fixtures import repo_root

TELEMETRY_REVIEW = repo_root() / "workflows" / "telemetry" / "telemetry-review.yaml"


def _stage(*, description: str = "d", writes_to: tuple[str, ...] = (), executor: str = "agent") -> StageSpec:
    return StageSpec(
        name="s",
        kind=StageKind.execute,
        description=description,
        agent=AgentSpec(role="doc-writer"),
        writes_to=writes_to,
        executor=executor,
    )


class IsRefusedTest(unittest.TestCase):
    def test_exact_basename_in_any_directory_and_case(self) -> None:
        for path in ("report.md", "outputs/report.md", "a/b/SUMMARY.md", "Findings.md"):
            with self.subTest(path=path):
                self.assertTrue(is_refused(path))

    def test_prefixed_and_other_extensions_are_accepted(self) -> None:
        for path in ("run-report.md", "final-report.md", "report.json", "reports.md", "report.md.bak"):
            with self.subTest(path=path):
                self.assertFalse(is_refused(path))


class FindRefusedOutputsTest(unittest.TestCase):
    def test_param_named_only_in_the_description(self) -> None:
        """validate-then-render's shape: the output is a {param} absent from writes_to."""
        stage = _stage(description="write {workspace}/outputs/{report_artifact}")
        found = find_refused_outputs([stage], {"report_artifact": "report.md"})
        self.assertEqual([(f.param, f.refused_name) for f in found], [("report_artifact", "report.md")])
        self.assertEqual(find_refused_outputs([stage], {"report_artifact": "run-report.md"}), [])

    def test_param_inside_writes_to_is_resolved(self) -> None:
        stage = _stage(writes_to=("outputs/{name}",))
        found = find_refused_outputs([stage], {"name": "summary.md"})
        self.assertEqual([(f.declared, f.param) for f in found], [("outputs/{name}", "name")])

    def test_param_directory_with_literal_name_is_literal(self) -> None:
        """'{workspace}/report.md': the refused name is literal, so lint owns it, not compile."""
        stage = _stage(writes_to=("{workspace}/report.md",))
        (item,) = find_refused_outputs([stage], {"workspace": "ws-root"})
        self.assertIsNone(item.param)
        self.assertEqual(find_refused_outputs([stage], {"workspace": "ws-root"}, literal=False), [])

    def test_literal_only_when_asked(self) -> None:
        stage = _stage(writes_to=("outputs/report.md",))
        self.assertEqual(len(find_refused_outputs([stage], {})), 1)
        self.assertEqual(find_refused_outputs([stage], {}, literal=False), [])

    def test_non_agent_executors_are_exempt(self) -> None:
        for executor in ("inline", "local", "skill"):
            with self.subTest(executor=executor):
                stage = _stage(description="{out}", writes_to=("report.md",), executor=executor)
                self.assertEqual(find_refused_outputs([stage], {"out": "report.md"}), [])

    def test_message_never_echoes_the_raw_value(self) -> None:
        """A --params value is caller text; the message names the param and the fixed name only."""
        from workflow.harness_outputs import describe

        stage = _stage(description="{out}")
        (item,) = find_refused_outputs([stage], {"out": "x/$(evil)/REPORT.md"})
        self.assertNotIn("$(evil)", describe(item))
        self.assertIn("'report.md'", describe(item))


class RealCallerTest(unittest.TestCase):
    """telemetry-review includes validate-then-render and binds report_artifact."""

    def test_default_compiles(self) -> None:
        compile_workflow(parse_workflow(TELEMETRY_REVIEW), project_root=repo_root())

    def test_params_override_to_a_refused_name_fails_compile(self) -> None:
        defn = parse_workflow(TELEMETRY_REVIEW)
        with self.assertRaises(WorkflowCompileError) as ctx:
            compile_workflow(defn, project_root=repo_root(), trigger_params={"report_artifact": "report.md"})
        self.assertIn("report_artifact", str(ctx.exception))
        self.assertIn("vtr-render", str(ctx.exception))

    def test_refused_default_fails_lint(self) -> None:
        """The same caller with report_artifact defaulting to report.md, as Copilot described."""
        text = TELEMETRY_REVIEW.read_text(encoding="utf-8")
        old = 'report_artifact: "telemetry-review.md"'
        include = "path: workflows/shared/validate-then-render.yaml"
        self.assertEqual(text.count(old), 1)
        self.assertEqual(text.count(include), 1)
        # The probe lives in a temp dir, never under workflows/: the tree-wide lint
        # test globs that directory and would see it if the two ran concurrently.
        fragment = repo_root() / "workflows" / "shared" / "validate-then-render.yaml"
        probe = text.replace(old, 'report_artifact: "report.md"').replace(include, f"path: {fragment}")
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp) / "probe.yaml"
            wf.write_text(probe, encoding="utf-8")
            result = lint_workflow(wf)
        errors = [e for e in result.errors if e.field == "param:report_artifact"]
        self.assertEqual([e.stage for e in errors], ["vtr-render"])
        self.assertFalse(result.valid)


if __name__ == "__main__":
    unittest.main()
