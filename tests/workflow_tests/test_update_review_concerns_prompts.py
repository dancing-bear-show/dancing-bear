"""Rendered-prompt checks for update-review-concerns' rereview mode.

These render the real YAML through the engine, as an agent would receive it,
and execute the rendered jq lines against a fixture workspace. The rereview
stages are shell-heavy and gate the run on exit status, so a read-through is
not enough: the commands have to be shown to pass on good data and fail on
empty or partial data.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # nosec B404 - runs the workflow's own rendered jq lines in a temp dir
import tempfile
import unittest
from pathlib import Path

from workflow.compiler import WorkflowCompileError, compile_workflow, match_when_expression
from workflow.dispatch import build_agent_prompt
from workflow.models import WorkflowDefinition, WorkflowManifest
from workflow.parser import parse_workflow

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / "workflows/code/update-review-concerns.yaml"
_PROMPT_FILE = _ROOT / "workflows/code/prompts/classify-rereview.md"

_TOPIC_STAGES = {
    "init", "fetch-findings", "fetch-review-threads", "cluster-gaps",
    "propose-concerns", "human-gate", "update-guides",
}
_REREVIEW_ONLY = {"fetch-round-history", "classify-rereview", "aggregate-rereview"}
_PLACEHOLDER_RE = re.compile(r"\{[a-z_][a-z0-9_]*\}")


def _compile(**params: str) -> tuple[WorkflowDefinition, WorkflowManifest]:
    defn = parse_workflow(str(_WORKFLOW))
    return defn, compile_workflow(defn, project_root=_ROOT, trigger_params=params)


def _prompts(workspace: str, **params: str) -> dict[str, str]:
    defn, manifest = _compile(**params)
    return {name: build_agent_prompt(stage, defn.name, workspace)
            for name, stage in manifest.resolved_stages.items()}


def _running(**params: str) -> set[str]:
    defn, manifest = _compile(**params)
    effective = {**defn.trigger.params, **params}
    return {name for name, stage in manifest.resolved_stages.items()
            if stage.spec.when is None or match_when_expression(stage.spec.when, effective)}


class TestParamRules(unittest.TestCase):
    """A caller-controlled param substituted into shell text was the largest
    defect class on PR #391. Every rereview param is rejected before
    substitution when it is not the shape the shell commands expect."""

    def test_both_modes_compile(self) -> None:
        _compile(mode="topics")
        _compile(mode="rereview")
        _compile(mode="rereview", pr_number="406", min_threads="20")

    def test_bad_min_threads_rejected(self) -> None:
        for bad in ("15;id", "0", "015", "1000", "$(id)", ""):
            with self.subTest(value=bad), self.assertRaises(WorkflowCompileError) as ctx:
                _compile(mode="rereview", min_threads=bad)
            self.assertIn("min_threads", str(ctx.exception))
            if "id" in bad:  # a rejected value is untrusted and is never echoed
                self.assertNotIn(bad, str(ctx.exception))

    def test_bad_pr_number_rejected(self) -> None:
        for bad in ("$(id)", "406;id", "0", "406,395", "12a", '406"'):
            with self.subTest(value=bad), self.assertRaises(WorkflowCompileError) as ctx:
                _compile(mode="rereview", pr_number=bad)
            self.assertIn("pr_number", str(ctx.exception))

    def test_bad_mode_rejected(self) -> None:
        for bad in ("both", "topicsrereview", "rereview;id", ""):
            with self.subTest(value=bad), self.assertRaises(WorkflowCompileError):
                _compile(mode=bad)

    def test_in_stage_checks_repeat_engine_rules(self) -> None:
        defn, _ = _compile()
        rules = {c.name: c.pattern for c in defn.trigger.rules.checks}
        text = _WORKFLOW.read_text(encoding="utf-8")
        found = re.findall(r"--check '([a-z_]+)=([^']*)'", text)
        self.assertEqual({n for n, _ in found}, {"mode", "min_threads", "pr_number"})
        for name, pattern in found:
            self.assertEqual(pattern, rules[name], name)


class TestModeRouting(unittest.TestCase):
    """topics must run exactly the stages it ran before rereview existed."""

    def test_topics_runs_the_original_stages(self) -> None:
        self.assertEqual(_running(mode="topics"), _TOPIC_STAGES)
        self.assertEqual(_running(), _TOPIC_STAGES)  # topics is the default

    def test_rereview_adds_its_stages_and_drops_thread_fetch(self) -> None:
        self.assertEqual(
            _running(mode="rereview"),
            (_TOPIC_STAGES - {"fetch-review-threads"}) | _REREVIEW_ONLY,
        )


class TestRenderedPrompts(unittest.TestCase):
    def setUp(self) -> None:
        self.prompts = _prompts("/ws", mode="rereview", pr_number="406", min_threads="20")

    def test_no_unsubstituted_placeholders(self) -> None:
        # {pr} and {fan_out_index} belong to the fan-out: dispatch fills them
        # per item, and the engine leaves them literal on purpose.
        allowed = {"classify-rereview": {"{pr}", "{fan_out_index}"}}
        for name in _REREVIEW_ONLY | {"cluster-gaps", "propose-concerns", "update-guides"}:
            with self.subTest(stage=name):
                left = set(_PLACEHOLDER_RE.findall(self.prompts[name])) - allowed.get(name, set())
                self.assertEqual(left, set())
                self.assertNotIn("{{", self.prompts[name])

    def test_params_reach_shell_quoted(self) -> None:
        text = self.prompts["fetch-round-history"]
        self.assertIn('review-rounds --prs "406" --out-dir "/ws/outputs/rounds"', text)
        self.assertIn('--min-threads "20"', text)
        self.assertIn('--argjson min "20"', text)

    def test_classifier_reads_checked_in_prompt(self) -> None:
        text = self.prompts["classify-rereview"]
        self.assertIn("workflows/code/prompts/classify-rereview.md", text)
        self.assertIn("/ws/outputs/rounds/pr{pr}.json", text)
        self.assertIn("/ws/outputs/classified/pr{pr}.json", text)
        self.assertTrue(_PROMPT_FILE.is_file())

    def test_prompt_file_is_workspace_relative_and_bans_catch_alls(self) -> None:
        body = _PROMPT_FILE.read_text(encoding="utf-8")
        for leaked in ("/private/tmp", "scratchpad", "/Users/"):
            self.assertNotIn(leaked, body)
        self.assertIn("outputs/rounds/prN.json", body)
        self.assertIn("`spec-or-logic-error`", body)
        for category in ("FIX_REGRESSION", "SIBLING", "INCOMPLETE_FIX", "COLLATERAL_DOC",
                         "NEW_SURFACE", "LATE_DISCOVERY", "NOISE", "ROUND0"):
            self.assertIn(category, body)

    def test_cluster_gaps_rejects_with_reasons(self) -> None:
        text = self.prompts["cluster-gaps"]
        for code in ("`catch-all`", "`single-pr`", "`covered`", "`no-sweep`", "`sweep-too-broad`"):
            self.assertIn(code, text)
        self.assertIn("## Rejected clusters", text)
        self.assertIn('"sweep":', text)

    def test_topics_prompt_routes_away_from_rereview(self) -> None:
        text = _prompts("/ws", mode="topics")["cluster-gaps"]
        self.assertIn('this run\'s mode is "topics"', text)


def _jq_lines(prompt: str) -> list[str]:
    return [ln.strip() for ln in prompt.splitlines() if ln.strip().startswith("jq ")]


@unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "needs jq and bash")
class TestRenderedJqExecutes(unittest.TestCase):
    """Run the rendered jq lines, one Bash call each, as the agent would."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = Path(tmp.name)
        (self.ws / "outputs/rounds").mkdir(parents=True)
        (self.ws / "outputs/classified").mkdir(parents=True)
        summary = [{"pr": 406, "threads": 2}, {"pr": 395, "threads": 1}, {"pr": 12, "threads": 0}]
        self._write("outputs/rounds/summary.json", summary)
        for pr, n in ((406, 2), (395, 1), (12, 0)):
            self._write(f"outputs/rounds/pr{pr}.json",
                        {"pr": pr, "threads": [{"thread_id": f"T{pr}-{i}"} for i in range(n)]})
        prompts = _prompts(str(self.ws), mode="rereview", min_threads="1")
        fetch = _jq_lines(prompts["fetch-round-history"])
        self.refuse_empty = next(c for c in fetch if "length > 0' " in c and "items" not in c)
        self.build_index = next(c for c in fetch if "--argjson min" in c)
        agg = _jq_lines(prompts["aggregate-rereview"])
        self.merge, self.counts, self.check, self.explain = agg

    def _write(self, rel: str, doc: object) -> None:
        (self.ws / rel).write_text(json.dumps(doc), encoding="utf-8")

    def _run(self, cmd: str) -> subprocess.CompletedProcess[str]:
        argv = [str(shutil.which("bash")), "-c", cmd]
        return subprocess.run(argv, capture_output=True, text=True, check=False)  # nosec B603 - rendered workflow lines against a temp dir

    def _classify(self, pr: int, n: int) -> None:
        self._write(f"outputs/classified/pr{pr}.json",
                    {"pr": pr, "threads": [{"class": "unquoted-shell-var"}] * n})

    def _index(self) -> None:
        self.assertEqual(self._run(self.build_index).returncode, 0)

    def test_index_applies_thread_floor(self) -> None:
        self._index()
        index = json.loads((self.ws / "outputs/rereview-index.json").read_text())
        self.assertEqual(index, {"items": [{"pr": "406"}, {"pr": "395"}]})

    def test_empty_summary_halts(self) -> None:
        self._write("outputs/rounds/summary.json", [])
        self.assertNotEqual(self._run(self.refuse_empty).returncode, 0)
        self.assertNotEqual(self._run(self.build_index).returncode, 0)

    def test_nothing_over_the_floor_halts(self) -> None:
        self._write("outputs/rounds/summary.json", [{"pr": 12, "threads": 0}])
        self.assertEqual(self._run(self.refuse_empty).returncode, 0)
        self.assertNotEqual(self._run(self.build_index).returncode, 0)

    def test_aggregate_passes_when_complete_and_ignores_stale_files(self) -> None:
        self._index()
        self._classify(406, 2)
        self._classify(395, 1)
        self._classify(12, 0)  # outside the index: a stale file from an earlier run
        for cmd in (self.merge, self.counts, self.check):
            self.assertEqual(self._run(cmd).returncode, 0, cmd)
        merged = json.loads((self.ws / "outputs/rereview-classified.json").read_text())
        self.assertEqual(sorted(d["pr"] for d in merged), [395, 406])

    def test_aggregate_halts_on_missing_pr(self) -> None:
        self._index()
        self._classify(406, 2)
        for cmd in (self.merge, self.counts):
            self.assertEqual(self._run(cmd).returncode, 0, cmd)
        self.assertNotEqual(self._run(self.check).returncode, 0)
        self.assertIn("395: 0 classified files", self._run(self.explain).stdout)

    def test_aggregate_halts_on_partial_classification(self) -> None:
        self._index()
        self._classify(406, 1)
        self._classify(395, 1)
        for cmd in (self.merge, self.counts):
            self.assertEqual(self._run(cmd).returncode, 0, cmd)
        self.assertNotEqual(self._run(self.check).returncode, 0)
        self.assertIn("406: 1 of 2 threads classified", self._run(self.explain).stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
