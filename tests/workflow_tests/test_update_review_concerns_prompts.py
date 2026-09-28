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
_REREVIEW_ONLY = {"fetch-round-history", "seed-class-list", "classify-rereview", "aggregate-rereview"}
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
        self.assertEqual({n for n, _ in found}, {"mode", "min_threads", "max_prs", "pr_number"})
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
        for code in ("`catch-all`", "`single-pr`", "`covered`", "`no-sweep`", "`sweep-too-broad`",
                     "`procedure-not-mechanical`"):
            self.assertIn(code, text)
        self.assertIn("## Rejected clusters", text)
        self.assertIn('"sweep":', text)

    def test_blank_pr_number_scans_max_prs_recent_prs(self) -> None:
        text = _prompts("/ws", mode="rereview", max_prs="30")["fetch-round-history"]
        self.assertIn('review-rounds --recent "30" --out-dir "/ws/outputs/rounds" --min-threads "15"', text)
        self.assertNotIn("--recent 60", text)

    def test_empty_scan_advice_sits_in_step_4(self) -> None:
        text = self.prompts["fetch-round-history"]
        step4, step5 = text.index("Step 4"), text.index("Step 5")
        advice = text.index("suggest a lower min_threads")
        self.assertLess(step4, advice)
        self.assertLess(advice, step5)

    def test_classifier_deletes_its_own_output_first(self) -> None:
        text = self.prompts["classify-rereview"]
        rm = text.index('rm -f "/ws/outputs/classified/pr{pr}.json"')
        self.assertLess(rm, text.index("Write only your own output file"))

    def test_fetch_findings_names_no_guide_list(self) -> None:
        """Guides are found by glob; a hand list drifts (it missed resume-copy.md)."""
        text = _prompts("/ws", mode="topics")["fetch-findings"]
        named = set(re.findall(r"concerns/[A-Za-z0-9_-]+\.md", text))
        self.assertEqual(named, {"concerns/README.md"})
        self.assertIn("concerns/*.md", text)

    def test_update_guides_writes_to_covers_every_guide(self) -> None:
        _, manifest = _compile(mode="topics")
        declared = set(manifest.resolved_stages["update-guides"].spec.writes_to)
        guides = {f"concerns/{p.name}" for p in (_ROOT / "concerns").glob("*.md")}
        self.assertTrue(guides)
        # concerns/collateral-damage.md is a conditional output: it is created
        # only by a rereview run and may not exist in the working tree.  It is
        # declared in writes_to so the contract covers it when it appears, but
        # we exclude it here so this test does not fail on a tree where the
        # file was not yet created.
        conditional = {"concerns/collateral-damage.md"}
        self.assertEqual(guides - declared - conditional, set())

    def test_update_guides_counts_readme_row_after_appending(self) -> None:
        text = self.prompts["update-guides"]
        self.assertLess(text.index("Step 3 — append"), text.index("Step 3b —"))
        self.assertLess(text.index("Step 3b —"), text.index("Step 4"))
        self.assertIn("grep -c '^### ' concerns/collateral-damage.md", text)

    def test_prompt_file_describes_full_oids_and_both_lines(self) -> None:
        body = _PROMPT_FILE.read_text(encoding="utf-8")
        self.assertNotIn("10-character", body)
        self.assertIn("full OID", body)
        self.assertIn("`original_line`", body)
        self.assertIn("`git show <commit>:<path>`", body)
        self.assertIn("aggregate-rereview fails the run", body)
        self.assertNotIn("cluster-gaps' aggregate check", body)

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
        # thread_ids must match the source rounds data (T{pr}-{i}) so the
        # multiset comparison in aggregate-rereview passes on good data.
        threads = [{"thread_id": f"T{pr}-{i}", "class": "unquoted-shell-var"} for i in range(n)]
        self._write(f"outputs/classified/pr{pr}.json", {"pr": pr, "threads": threads})

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

    def test_pr_number_mode_keeps_a_pr_under_the_floor(self) -> None:
        """#429 has 5 threads; with pr_number set, Step 4 and Step 5 must pass it."""
        self._write("outputs/rounds/summary.json", [{"pr": 429, "threads": 5}])
        fetch = _jq_lines(_prompts(str(self.ws), mode="rereview", pr_number="429")["fetch-round-history"])
        refuse_empty = next(c for c in fetch if "length > 0' " in c and "items" not in c)
        build_index = next(c for c in fetch if "select(.items" in c and "--argjson" not in c)
        self.assertEqual(self._run(refuse_empty).returncode, 0)
        self.assertEqual(self._run(build_index).returncode, 0)
        index = json.loads((self.ws / "outputs/rereview-index.json").read_text())
        self.assertEqual(index, {"items": [{"pr": "429"}]})

    def test_cluster_totals_are_computed_by_jq(self) -> None:
        self._write("outputs/rereview-classified.json", [
            {"pr": 406, "threads": [{"category": "SIBLING"}, {"category": "ROUND0"}, {"category": "SIBLING"}]},
            {"pr": 395, "threads": [{"category": "NOISE"}]},
        ])
        self._write("outputs/known-concern-ids.json", ["a", "b", "c"])
        text = _prompts(str(self.ws), mode="rereview")["cluster-gaps"]
        (totals,) = [c for c in _jq_lines(text) if "known concern ids" in c]
        res = self._run(totals)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.splitlines(), [
            "PRs: 2", "threads: 4", "NOISE: 1", "ROUND0: 1", "SIBLING: 2", "known concern ids: 3",
        ])

    def test_classifier_count_jq_executes(self) -> None:
        body = _PROMPT_FILE.read_text(encoding="utf-8")
        (line,) = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("jq '[.threads")]
        out = self.ws / "outputs/classified/pr1.json"
        self._write("outputs/classified/pr1.json",
                    {"pr": 1, "threads": [{"category": "SIBLING"}, {"category": "SIBLING"}, {"category": "NOISE"}]})
        res = self._run(line.replace("<your output file>", f'"{out}"'))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout), {"NOISE": 1, "SIBLING": 2})

    def test_aggregate_halts_on_partial_classification(self) -> None:
        self._index()
        self._classify(406, 1)
        self._classify(395, 1)
        for cmd in (self.merge, self.counts):
            self.assertEqual(self._run(cmd).returncode, 0, cmd)
        self.assertNotEqual(self._run(self.check).returncode, 0)
        self.assertIn("406: thread_id mismatch", self._run(self.explain).stdout)

    def _sweep_gate(self, stage: str, file: str) -> str:
        prompts = _prompts(str(self.ws), mode="rereview")
        (line,) = [c for c in _jq_lines(prompts[stage]) if f"outputs/{file}" in c and "structural" in c]
        return line

    def test_sweep_gate_accepts_data_and_refuses_shell_or_unsafe_paths(self) -> None:
        gate = self._sweep_gate("cluster-gaps", "gap-clusters.json")
        good = [
            {"class": "a", "sweep": {"pattern": "check-params[^|]*--check", "paths": ["workflows/", "src/core"]}},
            {"class": "b", "sweep": {"structural": "every isolated stage that names the workspace"}},
        ]
        self._write("outputs/gap-clusters.json", good)
        res = self._run(gate)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        bad_sweeps = {
            "command-string": "grep -rnE 'x' workflows/; id",
            "dotdot": {"pattern": "x", "paths": ["workflows/../../etc"]},
            "absolute": {"pattern": "x", "paths": ["/etc"]},
            "home": {"pattern": "x", "paths": ["~/x"]},
            "option": {"pattern": "x", "paths": ["-rf"]},
            "substitution": {"pattern": "x", "paths": ["src/$(id)"]},
            "github": {"pattern": "x", "paths": [".github/workflows"]},
            "claude": {"pattern": "x", "paths": [".claude/settings.json"]},
            "git-segment": {"pattern": "x", "paths": ["src/.GIT/hooks"]},
            "envrc": {"pattern": "x", "paths": ["src/.envrc"]},
            "no-paths": {"pattern": "x", "paths": []},
            "extra-key": {"pattern": "x", "paths": ["src"], "cmd": "id"},
            "empty-structural": {"structural": ""},
            "single-quote": {"pattern": "it's", "paths": ["src"]},
            "newline": {"pattern": "a\nb", "paths": ["src"]},
        }
        for label, sweep in bad_sweeps.items():
            with self.subTest(case=label):
                self._write("outputs/gap-clusters.json", [*good, {"class": label, "sweep": sweep}])
                res = self._run(gate)
                self.assertNotEqual(res.returncode, 0)
                self.assertIn(f"{label}: ", res.stdout)
                self.assertNotIn("a: ", res.stdout)

    def test_proposal_gate_is_the_cluster_gate(self) -> None:
        cluster = self._sweep_gate("cluster-gaps", "gap-clusters.json")
        proposal = self._sweep_gate("propose-concerns", "proposed-concerns.json")
        self.assertIn('has("procedure")', cluster)
        self.assertEqual(proposal, cluster.replace("gap-clusters.json", "proposed-concerns.json")
                         .replace('(.class // "?")', '(.concern_id // "?")'))

    def _gate_both(self, entry_sweep: dict[str, object], label: str) -> list[subprocess.CompletedProcess[str]]:
        """Run the cluster gate and the proposal gate over one extra entry."""
        results = []
        for stage, file, key in (("cluster-gaps", "gap-clusters.json", "class"),
                                 ("propose-concerns", "proposed-concerns.json", "concern_id")):
            gate = self._sweep_gate(stage, file)
            self._write(f"outputs/{file}", [
                {key: "a", "sweep": {"pattern": "x", "paths": ["src"]}},
                {key: label, "sweep": entry_sweep},
            ])
            results.append(self._run(gate))
        return results

    def test_sweep_gate_accepts_a_valid_procedure(self) -> None:
        for res in self._gate_both({"procedure": _procedure()}, "guard"):
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertEqual(res.stdout.strip(), "true")

    def test_worked_example_in_the_prompt_passes_the_gate(self) -> None:
        """The example R5 teaches must itself be a valid procedure."""
        text = _prompts(str(self.ws), mode="rereview")["cluster-gaps"]
        (line,) = [ln.strip() for ln in text.splitlines()
                   if ln.strip().startswith('{"procedure": {"trigger": "a function')]
        for res in self._gate_both(json.loads(line), "example"):
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_sweep_gate_refuses_non_mechanical_procedures(self) -> None:
        steps = _STEPS
        bad = {
            "one-step": _procedure(steps=steps[:1]),
            "seven-steps": _procedure(steps=[f"Is item {i} tested?" for i in range(7)]),
            "no-steps": _procedure(steps=[]),
            "empty-step": _procedure(steps=[steps[0], ""]),
            "blank-step": _procedure(steps=[steps[0], "   "]),
            "not-a-question": _procedure(steps=[steps[0], "List every entry point."]),
            "non-string-step": _procedure(steps=[steps[0], 3]),
            "judgement": _procedure(steps=[steps[0], "Was the guard checked carefully?"]),
            "accuracy": _procedure(evidence="review for accuracy"),
            "blank-trigger": _procedure(trigger=" "),
            "no-trigger": {k: v for k, v in _procedure().items() if k != "trigger"},
            "no-evidence": {k: v for k, v in _procedure().items() if k != "evidence"},
            "extra-key": {**_procedure(), "cmd": "id"},
            "steps-as-string": _procedure(steps="Is it tested?"),
        }
        for label, proc in bad.items():
            with self.subTest(case=label):
                for res in self._gate_both({"procedure": proc}, label):
                    self.assertNotEqual(res.returncode, 0)
                    self.assertIn(f"{label}: ", res.stdout)
                    self.assertNotIn("a: ", res.stdout)
        with self.subTest(case="procedure-beside-pattern"):
            for res in self._gate_both({"procedure": _procedure(), "pattern": "x", "paths": ["src"]}, "mixed"):
                self.assertNotEqual(res.returncode, 0)

    def _enforcement_lines(self) -> tuple[str, str]:
        text = _prompts(str(self.ws), mode="rereview")["cluster-gaps"]
        lines = [c for c in _jq_lines(text) if "outputs/enforcement-gaps.json" in c]
        (gate,) = [c for c in lines if "--slurpfile k" in c]
        (table,) = [c for c in lines if "None." in c]
        return gate, table

    def test_enforcement_gap_gate_requires_a_known_concern_and_two_prs(self) -> None:
        gate, _ = self._enforcement_lines()
        self._write("outputs/known-concern-ids.json", ["stale-prose-after-behavior-change", "silent-failure"])
        self._write("outputs/enforcement-gaps.json", [])
        self.assertEqual(self._run(gate).returncode, 0)
        self._write("outputs/enforcement-gaps.json", [_gap()])
        res = self._run(gate)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        bad = {
            "unknown-id": _gap(concern_id="unknown-id"),
            "one-pr": _gap(concern_id="silent-failure", pr_numbers=["406", "406"]),
            "bad-guide": _gap(concern_id="silent-failure", guide_file="../x.md"),
            "no-example": _gap(concern_id="silent-failure", example=""),
        }
        for label, entry in bad.items():
            with self.subTest(case=label):
                self._write("outputs/enforcement-gaps.json", [_gap(), entry])
                res = self._run(gate)
                self.assertNotEqual(res.returncode, 0)
                self.assertEqual(res.stdout.count("\n"), 2, res.stdout)  # one bad line, then false

    def test_enforcement_gap_table_is_rendered_by_jq(self) -> None:
        _, table = self._enforcement_lines()
        self._write("outputs/enforcement-gaps.json", [])
        self.assertEqual(self._run(table).stdout.strip(), "None.")
        self._write("outputs/enforcement-gaps.json", [_gap(example="a.md:3 — x | y")])
        res = self._run(table)
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = res.stdout.splitlines()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2], "| `stale-prose-after-behavior-change` | patterns.md | doc-claims-drift-from-code"
                                  " | COLLATERAL_DOC | 406, 395 | 8 | a.md:3 — x   y |")


_STEPS = [
    "Does the diff list every input form the guard receives?",
    "Does each listed input form have its own test?",
]


def _procedure(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "trigger": "a function that rejects, filters or authorises input is added or modified in `src/**/*.py`",
        "steps": list(_STEPS),
        "evidence": "each input form, paired with the test that covers it",
    }
    return {**base, **over}


def _gap(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "concern_id": "stale-prose-after-behavior-change", "guide_file": "patterns.md",
        "class": "doc-claims-drift-from-code", "cause_category": "COLLATERAL_DOC",
        "pr_numbers": ["406", "395"], "thread_count": 8, "example": "README.md:12 — stale claim",
    }
    return {**base, **over}


class TestPromotionRule(unittest.TestCase):
    """The promotion rule must admit defects no grep can find, and must not
    silently drop a covered class that keeps recurring."""

    def setUp(self) -> None:
        self.prompts = _prompts("/ws", mode="rereview")

    def test_ladder_reason_codes_and_order(self) -> None:
        flat = " ".join(self.prompts["cluster-gaps"].split())
        for code in ("`procedure-not-mechanical`", "`no-sweep`", "`sweep-too-broad`", "`covered`"):
            self.assertIn(code, flat)
        self.assertLess(flat.index("1. pattern"), flat.index("2. structural"))
        self.assertLess(flat.index("2. structural"), flat.index("3. procedure"))
        self.assertIn("Never reject with `no-sweep` or `sweep-too-broad` before attempting a procedure", flat)
        self.assertIn("neither a pattern, a structural check, nor a mechanical procedure could be written", flat)

    def test_catch_all_and_single_pr_precede_covered(self) -> None:
        text = self.prompts["cluster-gaps"]
        r5 = text[text.index("R5 —"):text.index("R6 —")]
        self.assertLess(r5.index("`catch-all`"), r5.index("`single-pr`"))
        self.assertLess(r5.index("`single-pr`"), r5.index("`covered`"))
        self.assertLess(r5.index("`covered`"), r5.index("the sweep ladder"))

    def test_enforcement_gaps_declared(self) -> None:
        for mode in ("topics", "rereview"):
            _, manifest = _compile(mode=mode)
            self.assertIn("outputs/enforcement-gaps.json",
                          manifest.resolved_stages["cluster-gaps"].spec.writes_to)

    def test_every_exit_writes_every_declared_output(self) -> None:
        _, manifest = _compile(mode="rereview")
        declared = [Path(p).name for p in manifest.resolved_stages["cluster-gaps"].spec.writes_to]
        for mode in ("topics", "rereview"):
            flat = " ".join(_prompts("/ws", mode=mode)["cluster-gaps"].split())
            with self.subTest(mode=mode, check="exit rule"):
                start = flat.index("Every exit from this stage, early or not and in either mode")
                rule = flat[start:flat.index("A missing file", start)]
                for name in declared:
                    self.assertIn(name, rule)
            with self.subTest(mode=mode, check="topics path"):
                topics = flat[:flat.index("REREVIEW MODE (only")]
                self.assertIn("write [] to /ws/outputs/enforcement-gaps.json", topics)
            with self.subTest(mode=mode, check="empty-array exits"):
                exits = [m.start() for m in re.finditer(r"write \[\] to gap-clusters\.json", flat, re.IGNORECASE)]
                self.assertEqual(len(exits), 2)  # topics Step 5 and rereview R7
                for at in exits:
                    self.assertIn("enforcement-gaps.json", flat[at:at + 250])
            with self.subTest(mode=mode, check="single-PR rereview"):
                self.assertIn("Write [] when there are none, which is always the case when pr_number is set", flat)

    def test_propose_concerns_forwards_enforcement_gaps_and_never_proposes_them(self) -> None:
        flat = " ".join(self.prompts["propose-concerns"].split())
        self.assertIn('Copy the "## Enforcement gaps" section', flat)
        self.assertIn("never add one to proposed-concerns.json", flat)
        self.assertLess(flat.index('"## Enforcement gaps"'), flat.index('"## Rejected clusters"'))
        self.assertIn("plus those three sections", flat)

    def test_procedure_entry_format(self) -> None:
        flat = " ".join(self.prompts["propose-concerns"].split())
        self.assertIn('**check** is "Answer yes to each step: "', flat)
        self.assertIn("**triggers** is the procedure trigger verbatim", flat)
        self.assertIn("numbered list", flat)
        self.assertIn('{"procedure"} object', flat)

    def test_lint_kind_is_deferred_to_pr_433(self) -> None:
        self.assertIn("PR #433", _WORKFLOW.read_text(encoding="utf-8"))
        self.assertNotIn('"lint":', self.prompts["cluster-gaps"])


_COUNT_SWEEP_CALL = "./bin/workflow count-sweep --pattern='<pattern>' --path <path>"


class TestSweepCounting(unittest.TestCase):
    """Sweeps are counted in-process by count-sweep, never via a spec file and a shell grep."""

    def test_no_stage_prompt_names_the_spec_file_flow(self) -> None:
        for mode in ("topics", "rereview"):
            for name, text in _prompts("/ws", mode=mode).items():
                with self.subTest(mode=mode, stage=name):
                    for banned in ("sweep-spec", "/tmp/", "grep-sweep"):  # nosec B108 - asserted absent, never used as a path
                        self.assertNotIn(banned, text)

    def test_sweeping_stages_call_count_sweep_with_a_single_quoted_pattern(self) -> None:
        prompts = _prompts("/ws", mode="rereview")
        for name in ("cluster-gaps", "propose-concerns"):
            with self.subTest(stage=name):
                text = prompts[name]
                self.assertIn(_COUNT_SWEEP_CALL, text)
                for leaked in ("wc -l", "Grep tool", "grep -rn", "python3 -I -S -c"):
                    self.assertNotIn(leaked, text)
                calls = re.findall(r"count-sweep --pattern[^\n`]*", text)
                self.assertTrue(calls)
                for call in calls:
                    self.assertTrue(call.startswith("count-sweep --pattern='<pattern>' --path <path>"), call)

    def test_quote_and_newline_refusal_is_in_the_stage_text(self) -> None:
        prompts = _prompts("/ws", mode="rereview")
        for name in ("cluster-gaps", "propose-concerns"):
            with self.subTest(stage=name):
                flat = " ".join(prompts[name].split())
                self.assertIn("a pattern containing a single quote or a newline is REFUSED", flat)

    def test_rendered_call_runs_and_refuses_an_escaping_path(self) -> None:
        text = _prompts("/ws", mode="rereview")["cluster-gaps"]
        self.assertIn(_COUNT_SWEEP_CALL, text)
        argv = [str(_ROOT / "bin/workflow"), "count-sweep", "--pattern=check-params", "--path", "workflows/"]
        res = subprocess.run(argv, cwd=_ROOT, capture_output=True, text=True, check=False)  # nosec B603 - fixed argv, repo's own wrapper
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertGreater(json.loads(res.stdout)["hits"], 0)
        argv[-1] = "../x"
        res = subprocess.run(argv, cwd=_ROOT, capture_output=True, text=True, check=False)  # nosec B603 - fixed argv, repo's own wrapper
        self.assertEqual((res.returncode, res.stdout), (2, ""))
        self.assertIn("escapes-repo", res.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
